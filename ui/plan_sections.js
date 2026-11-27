// ---------------------------------------------------------------------------------------------
// H3Sections (plan v7, chantier B): the editor of a clip (anchors, texts with @subjects, the settings of the subjects
// it uses, the H3 prompt composed by the server or written by hand) and the library of the plan screen (subjects of the
// plan, files of the project). The H3 wording itself (numbers, sections, retention markers) is the server's
// (POST /plan/compose); this module never writes it.
// ---------------------------------------------------------------------------------------------
const H3Sections = (() => {
    const _t = typeof H3I18n !== "undefined" ? H3I18n.t : (id) => id;
    const KIND_ICON = { person: "👤", place: "🏞", object: "📦", outfit: "👗", style: "🎨", action: "🏃", pose: "🧍" };
    const view = { tab: "fields", files: "images" };       // the tab of the prompt card, the tab of the library's files

    // ------------------------------------------------------------------ pure helpers (tested in node)
    // the label of a project file in plan.files (made from its name the first time it is used)
    function fileLabel(plan, rel, kind) {
        plan.files = plan.files || {};
        for (const [label, item] of Object.entries(plan.files)) if (item && item.file === rel && item.kind === kind) return label;
        const stem = String(rel || "").split("/").pop().replace(/\.[^.]*$/, "");
        let base = stem.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^[_-]+|_+$/g, "") || kind;
        if (!/^[A-Za-z0-9]/.test(base)) base = kind + "_" + base;
        if (kind === "voice" && !/voice$/.test(base)) base += "_voice";
        let label = base, k = 2;
        while (label in plan.files) label = `${base}_${k++}`;
        plan.files[label] = { kind, file: rel };
        return label;
    }
    // files no subject, anchor or video of the plan names any more (the 'defs' of generated clips keep their own)
    function pruneFiles(plan) {
        const used = new Set();
        for (const s of Object.values(plan.subjects || {})) {
            for (const p of (s && s.pictures) || []) if (p && p.file) used.add(p.file);
            if (s && s.voice) used.add(s.voice);
        }
        for (const c of plan.clips || []) {
            const a = (c && c.anchors) || {};
            for (const f of [a.first, a.last, ...(a.keyframes || []).map((k) => k && k.file)]) if (f) used.add(f);
        }
        for (const v of [plan.start_video, plan.edit_video]) if (v && v.ref) used.add(v.ref);
        for (const label of Object.keys(plan.files || {})) if (!used.has(label)) delete plan.files[label];
    }
    function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
    // @old -> @new in the texts of the clips from `from` on (the generated ones keep theirs), the edit instruction,
    // the dialogue speakers and the subject settings
    function renameSubject(plan, oldName, newName, from = 0) {
        const re = new RegExp(`(?<![\\p{L}\\p{N}_@])@${escapeRe(oldName)}(?![\\p{L}\\p{N}_-])`, "gu");
        const swap = (t) => (typeof t === "string" ? t.replace(re, "@" + newName) : t);
        if (plan.subjects && oldName in plan.subjects) {
            plan.subjects = Object.fromEntries(Object.entries(plan.subjects).map(([k, v]) => [k === oldName ? newName : k, v]));
        }
        if (plan.edit_video && typeof plan.edit_video.instruction === "string") plan.edit_video.instruction = swap(plan.edit_video.instruction);
        (plan.clips || []).forEach((c, i) => {
            if ((typeof from === "function" ? from(i) : i < from) || !c) return;   // from: a locked clip (0.49: a function)
            for (const k of [...H3.TEXT_KEYS, "prompt_override"]) if (typeof c[k] === "string") c[k] = swap(c[k]);
            for (const d of c.dialogue || []) if (d && d.speaker === oldName) d.speaker = newName;
            for (const u of c.subjects || []) if (u && u.name === oldName) u.name = newName;
        });
    }
    // the settings of a subject in a clip (created when first changed; removed when back to the defaults)
    function useOf(clip, name) { return (clip.subjects || []).find((u) => u && u.name === name) || { name }; }
    function setUse(clip, name, key, value, def) {
        clip.subjects = (clip.subjects || []).filter((u) => u && u.name);
        let u = clip.subjects.find((x) => x.name === name);
        if (!u) { u = { name }; clip.subjects.push(u); }
        if (value === def || value === "" || value == null) delete u[key]; else u[key] = value;
        clip.subjects = clip.subjects.filter((x) => Object.keys(x).length > 1);
        if (!clip.subjects.length) delete clip.subjects;
    }
    // a next clip: the subjects, settings, style and soundscape of the one before, without what was its own
    function inheritedClip(prev, clip) {
        for (const k of ["subjects"]) if (prev[k]) clip[k] = JSON.parse(JSON.stringify(prev[k]));
        const style = String(prev.description || "").split(/\[Shot \d+\]/)[0].trim();
        clip.description = (style ? style + "\n" : "") + "[Shot 1] ";
        clip.summary = "";
        if (prev.soundscape) clip.soundscape = prev.soundscape;
        if (prev.music) clip.music = prev.music;
        return clip;
    }

    // ------------------------------------------------------------------ DOM helpers
    function h(tag, attrs = {}, ...kids) {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v === undefined || v === null || v === false) continue;
            if (k === "class") node.className = v;
            else if (k === "style") node.style.cssText = v;
            else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
            else if (k === "value") node.value = v;
            else if (k === "selected") node.selected = !!v;
            else node.setAttribute(k, v === true ? "" : v);
        }
        for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid instanceof Node ? kid : String(kid));
        return node;
    }
    function autosize(ta) {
        ta.style.height = "auto";
        ta.style.height = Math.max(ta.scrollHeight + 2, ta.classList.contains("sx-one") ? 30 : 44) + "px";
    }

    // ------------------------------------------------------------------ "@" completion
    let ac = null;    // {ta, start, items, active, node}
    function closeAc() { if (ac) { ac.node.remove(); ac = null; } }
    // pixel position of the caret inside a textarea (mirror element)
    function caretXY(ta, pos) {
        const cs = getComputedStyle(ta);
        const div = document.createElement("div");
        for (const p of ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "paddingTop", "paddingLeft", "paddingRight", "borderTopWidth", "borderLeftWidth", "boxSizing", "tabSize"]) div.style[p] = cs[p];
        Object.assign(div.style, { position: "absolute", visibility: "hidden", whiteSpace: "pre-wrap", wordWrap: "break-word", width: ta.clientWidth + "px", top: "0", left: "-9999px" });
        div.textContent = ta.value.slice(0, pos);
        const mark = document.createElement("span");
        mark.textContent = "​";
        div.append(mark);
        document.body.append(div);
        const x = mark.offsetLeft, y = mark.offsetTop + mark.offsetHeight;
        div.remove();
        const r = ta.getBoundingClientRect();
        return { x: r.left + x - ta.scrollLeft, y: r.top + y - ta.scrollTop + 2 };
    }
    function insertAt(ta, start, end, text) {
        const v = ta.value;
        const after = v.slice(end);
        const glue = /\s$/.test(text) ? "" : after && !/^[\s.,;:!?)]/.test(after) ? " " : (after ? "" : " ");
        ta.value = v.slice(0, start) + text + glue + after;
        const pos = start + text.length + glue.length;
        ta.focus();
        ta.setSelectionRange(pos, pos);
        ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    function attachAc(ta, getItems) {
        const update = () => {
            const pos = ta.selectionStart;
            if (pos !== ta.selectionEnd) { closeAc(); return; }
            const before = ta.value.slice(0, pos);
            const m = /(^|[^\p{L}\p{N}_@{-])@([\p{L}\p{N}_-]*)$/u.exec(before);
            const cam = m ? null : /(^|\s)\/([\p{L}\p{N}_ -]*)$/u.exec(before);      // « / »: camera moves, cuts, framing
            if (!m && !cam) { if (ac && ac.ta === ta) closeAc(); return; }
            const q = (m || cam)[2].toLowerCase();
            const pool = m ? getItems() : cameraItems(ta, cam.index + cam[1].length);
            const items = pool.filter((it) => !q || (it.label + " " + (it.hint || "")).toLowerCase().includes(q)).slice(0, cam ? 30 : 10);
            if (!items.length) { closeAc(); return; }
            const start = pos - (m || cam)[2].length - 1;
            if (!ac || ac.ta !== ta) {
                closeAc();
                ac = { ta, node: h("div", { class: "sx-ac", role: "listbox" }) };
                document.body.append(ac.node);
            }
            ac.start = start; ac.end = pos; ac.items = items; ac.active = Math.min(ac.active || 0, items.length - 1);
            drawAc();
            const xy = caretXY(ta, start);
            const w = ac.node.offsetWidth, hgt = ac.node.offsetHeight;
            ac.node.style.left = Math.max(8, Math.min(xy.x, window.innerWidth - w - 8)) + "px";
            ac.node.style.top = (xy.y + hgt > window.innerHeight - 8 ? Math.max(8, xy.y - hgt - 22) : xy.y) + "px";
        };
        ta.addEventListener("input", update);
        ta.addEventListener("click", update);
        ta.addEventListener("keydown", (e) => {
            if (!ac || ac.ta !== ta) return;
            if (e.key === "ArrowDown") { e.preventDefault(); ac.active = (ac.active + 1) % ac.items.length; drawAc(); }
            else if (e.key === "ArrowUp") { e.preventDefault(); ac.active = (ac.active - 1 + ac.items.length) % ac.items.length; drawAc(); }
            else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(ac.items[ac.active]); }
            else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeAc(); }
        });
        ta.addEventListener("blur", () => setTimeout(() => { if (ac && ac.ta === ta && document.activeElement !== ta) closeAc(); }, 150));
    }
    function pick(item) {
        if (!ac || !item) return;
        if (item.more) {          // a camera move: then its amplitude and speed
            ac.items = item.more();
            ac.active = 0;
            drawAc();
            return;
        }
        const { ta, start, end } = ac;
        closeAc();
        insertAt(ta, start, end, item.ins);
        if (item.select) {        // a value to type at once (the time of a cut)
            const at = ta.value.indexOf(item.select, start);
            if (at >= 0) ta.setSelectionRange(at, at + item.select.length);
        }
    }
    // ---- « / » in a text: the camera vocabulary of MiniMax's guide (moves with their amplitude and speed), cuts to a
    // new shot, framings. What is inserted is plain English text, ready to finish.
    const MOVES = [
        ["push_in", "The camera pushes in{a}{s} toward "], ["pull_out", "The camera pulls out{a}{s}, revealing "],
        ["zoom_in", "The camera zooms in{a}{s} on "], ["zoom_out", "The camera zooms out{a}{s}, revealing "],
        ["pan_left", "The camera pans left{a}{s}, "], ["pan_right", "The camera pans right{a}{s}, "],
        ["truck_left", "The camera trucks left{a}{s}, following "], ["truck_right", "The camera trucks right{a}{s}, following "],
        ["tilt_up", "The camera tilts up{a}{s} to "], ["tilt_down", "The camera tilts down{a}{s} to "],
        ["pedestal_up", "The camera pedestals up{a}{s}, "], ["pedestal_down", "The camera pedestals down{a}{s}, "],
        ["arc", "The camera moves in an arc shot{a}{s} around "], ["tracking", "The camera follows in a tracking shot{s} as "],
        ["roll_cw", "The camera rolls clockwise{a}{s}, "], ["roll_ccw", "The camera rolls counterclockwise{a}{s}, "],
    ];
    const FIXED = [
        ["static", "The camera holds a static shot as "], ["shake_slightly", "The camera shakes slightly. "],
        ["shake_strongly", "The camera shakes strongly. "], ["pov", "Point-of-view shot: "],
    ];
    const FRAMINGS = [["extreme_close_up", "Extreme close-up on "], ["close_up", "Close-up on "], ["medium_shot", "Medium shot of "],
        ["medium_wide_shot", "Medium-wide shot of "], ["wide_shot", "Wide shot of "], ["over_shoulder", "Over-the-shoulder shot of "]];
    const AMPS = [["", "amp_medium"], [" with small amplitude", "amp_small"], [" with large amplitude", "amp_large"]];
    const SPEEDS = [["", "speed_normal"], [" at slow speed", "speed_slow"], [" at fast speed", "speed_fast"]];
    function cameraItems(ta, slash) {
        const out = [];
        const shots = (ta.value.slice(0, slash).match(/\[Shot \d+\]/g) || []).length;
        if (ta.dataset.sec === "description" || ta.id === "rawPrompt") {
            const time = "00:00.000";
            out.push({ kind: "C", label: _t("sx.cam_cut"), hint: `[Shot ${shots + 1}] At ${time}, the shot cuts to …`,
                ins: `${slash > 0 && ta.value[slash - 1] !== "\n" ? "\n" : ""}[Shot ${shots + 1}] At ${time}, the shot cuts to `, select: time });
        }
        for (const [key, text] of MOVES) {
            const label = _t("sx.cam_" + key);
            out.push({ kind: "C", label, hint: text.replace("{a}", "").replace("{s}", "").trim() + " …", more: () => {
                const list = [];
                for (const [a, al] of key === "tracking" ? [AMPS[0]] : AMPS) for (const [sp, sl] of SPEEDS) {
                    const ins = text.replace("{a}", a).replace("{s}", sp);
                    list.push({ kind: "C", label: `${label} · ${_t("sx.cam_" + al)} · ${_t("sx.cam_" + sl)}`, hint: ins.trim() + " …", ins });
                }
                return list;
            } });
        }
        for (const [key, ins] of FIXED) out.push({ kind: "C", label: _t("sx.cam_" + key), hint: ins.trim(), ins });
        for (const [key, ins] of FRAMINGS) out.push({ kind: "F", label: _t("sx.cam_" + key), hint: ins.trim() + " …", ins });
        return out;
    }
    function drawAc() {
        ac.node.replaceChildren(...ac.items.map((it, i) => h("div", { class: `sx-ac-item${i === ac.active ? " on" : ""}`, role: "option",
            onmousedown: (e) => { e.preventDefault(); pick(it); },
            onmousemove: () => { if (ac.active !== i) { ac.active = i; drawAc(); } } },
            h("span", { class: `sx-k sx-k${it.kind}` }, it.kind),
            it.img ? h("img", { src: it.img, alt: "" }) : null,
            h("span", { class: "sx-ac-label" }, it.label),
            it.hint ? h("span", { class: "sx-ac-hint" }, it.hint) : null)));
    }


    // ------------------------------------------------------------------ what can be inserted
    const subjectsOf = (ctx) => H3.definitions(ctx.plan, ctx.clip).subjects;
    function fileUrl(ctx, label) {
        const item = H3.definitions(ctx.plan, ctx.clip).files[label];
        return item && item.file && ctx.media && ctx.media.fileUrl ? ctx.media.fileUrl(item.file) : null;
    }
    function subjectThumb(ctx, name, subjects) {
        const s = (subjects || subjectsOf(ctx))[name];
        const pic = s && (s.pictures || [])[0];
        return pic ? fileUrl(ctx, pic.file) : null;
    }
    function snippets(ctx, first) {
        const who = first ? "@" + first : "";
        const lang = ctx.lastLanguage();
        const list = [];
        if (ctx.free) {
            list.push({ label: _t("sections.silent_character"), ins: `${who} never speaks and keeps its mouth closed.` });
            list.push({ label: _t("sections.silent_ending"), ins: "End with a quiet half second without speech." });
        } else {
            list.push({ label: _t("sections.silent_character"), ins: `${who} never sings and keeps its mouth closed.` });
            list.push({ label: _t("sections.off_screen_singer"), ins: "Nobody sings on screen; the song is performed by an off-screen singer." });
            list.push({ label: _t("sections.music_sync"), ins: "The visible performance stays synchronized to it." });
        }
        list.push({ label: _t("sections.ending_in_motion"), ins: "End with the motion still in progress, so the next clip continues the same shot." });
        list.push({ label: "<d>…</d>", ins: `<d>[${lang}] </d>` });
        return list;
    }
    function dialogueItems(ctx) {
        const c = ctx.clip, out = [];
        if (ctx.free) {
            for (const d of c.dialogue || []) {
                if (!String(d.text || "").trim()) continue;
                out.push({ label: _t("sections.line_of", { v0: d.speaker || "?" }), hint: d.text,
                    ins: `@${d.speaker} says: <d>[${d.language || ctx.lastLanguage()}] ${String(d.text).trim()}</d>` });
            }
        } else if (String(c.lyrics || "").trim()) {
            const first = H3.clipSubjects(ctx.plan, c, ctx.index)[0];
            out.push({ label: _t("sections.clip_lyrics"), hint: c.lyrics,
                ins: `${first ? "@" + first + " " : ""}sings with clearly readable mouth and jaw articulation: <d>[${ctx.lastLanguage()}] ${String(c.lyrics).trim()}</d>` });
        }
        return out;
    }
    function items(ctx) {
        const subjects = subjectsOf(ctx);
        const out = Object.entries(subjects).map(([n, s]) => ({ kind: "S", label: "@" + n, hint: `${KIND_ICON[s.kind || "person"] || ""} ${s.description || ""}`,
            ins: "@" + n, img: subjectThumb(ctx, n, subjects) }));
        dialogueItems(ctx).forEach((d) => out.push({ kind: "D", ...d }));
        snippets(ctx, H3.clipSubjects(ctx.plan, ctx.clip, ctx.index)[0]).forEach((p) => out.push({ kind: "P", label: p.label, hint: p.ins, ins: p.ins }));
        return out;
    }
    const dragText = (text) => (e) => { e.dataTransfer.setData("text/x-h3", text); e.dataTransfer.setData("text/plain", text); e.dataTransfer.effectAllowed = "copy"; };
    // character index under a point of a textarea (mirror element, one span per character)
    function indexFromPoint(ta, x, y) {
        const cs = getComputedStyle(ta), r = ta.getBoundingClientRect();
        const div = document.createElement("div");
        for (const p of ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "paddingTop", "paddingLeft", "paddingRight", "paddingBottom", "borderTopWidth", "borderLeftWidth", "borderRightWidth", "borderStyle", "boxSizing", "tabSize"]) div.style[p] = cs[p];
        Object.assign(div.style, { position: "fixed", left: r.left + "px", top: (r.top - ta.scrollTop) + "px", width: r.width + "px", whiteSpace: "pre-wrap", wordWrap: "break-word", visibility: "hidden", borderColor: "transparent" });
        const spans = [...ta.value].map((ch) => { const sp = document.createElement("span"); sp.textContent = ch; return sp; });
        div.append(...spans);
        document.body.append(div);
        let best = ta.value.length, bestD = Infinity;
        spans.forEach((sp, i) => {
            const b = sp.getBoundingClientRect();
            if (!b.height) return;
            const dy = y < b.top ? b.top - y : y > b.bottom ? y - b.bottom : 0;
            const dx = x < b.left ? b.left - x : x > b.right ? x - b.right : 0;
            const d = dy * 1000 + dx;
            if (d < bestD) { bestD = d; best = i + (x > b.left + b.width / 2 ? 1 : 0); }
        });
        div.remove();
        return best;
    }
    function acceptDrops(ta) {
        ta.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("text/x-h3")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
        ta.addEventListener("drop", (e) => {
            const text = e.dataTransfer.getData("text/x-h3");
            if (!text) return;
            e.preventDefault();
            const i = indexFromPoint(ta, e.clientX, e.clientY);
            const before = ta.value.slice(0, i);
            insertAt(ta, i, i, (before && !/[\s(]$/.test(before) ? " " : "") + text);
        });
    }


    // a project file dragged from the library (onto an anchor or a subject): {rel, kind}
    const dragFile = (rel, kind) => (e) => { e.dataTransfer.setData("text/x-h3-file", JSON.stringify({ rel, kind })); e.dataTransfer.effectAllowed = "copy"; };
    // 0.48.2: files dragged from the computer (Explorer, Finder) are imported into the project first; single: only the
    // first one (a place that takes one file: a missing picture, a picture to replace, an anchor)
    const isOsDrag = (e) => [...e.dataTransfer.types].includes("Files");
    const FOLDER_OF_KIND = { image: "images", voice: "voices" };
    const fitsKind = (file, kind) => (file.type || "").startsWith(kind === "image" ? "image/" : "audio/")
        || (kind === "image" ? /\.(png|jpe?g|webp|gif|bmp)$/i : /\.(wav|mp3|flac|ogg|m4a|aac)$/i).test(file.name);
    async function importDropped(e, kind, single) {
        const media = (window.H3Editor && window.H3Editor.media) || {};
        const files = [...e.dataTransfer.files];
        const ok = files.filter((f) => fitsKind(f, kind));
        if (!ok.length) { alert(_t(kind === "image" ? "sx.drop_an_image" : "sx.drop_a_voice")); return []; }
        if (!media.importDropped) return [];
        return media.importDropped(FOLDER_OF_KIND[kind], single ? ok.slice(0, 1) : ok);
    }
    function dropFile(node, kind, onFile, { single = false } = {}) {
        node.addEventListener("dragover", (e) => {
            if ([...e.dataTransfer.types].includes("text/x-h3-file") || isOsDrag(e)) { e.preventDefault(); e.stopPropagation(); node.classList.add("sx-over"); }
        });
        node.addEventListener("dragleave", () => node.classList.remove("sx-over"));
        node.addEventListener("drop", async (e) => {
            node.classList.remove("sx-over");
            if (isOsDrag(e) && e.dataTransfer.files.length) {
                e.preventDefault(); e.stopPropagation();
                for (const rel of await importDropped(e, kind, single)) onFile(rel);
                return;
            }
            const raw = e.dataTransfer.getData("text/x-h3-file");
            if (!raw) return;
            e.preventDefault(); e.stopPropagation();
            const f = JSON.parse(raw);
            if (f.kind !== kind) { alert(_t(kind === "image" ? "sx.drop_an_image" : "sx.drop_a_voice")); return; }
            onFile(f.rel);
        });
    }
    const KIND_OF_FOLDER = { images: "image", voices: "voice" };
    // a picture chosen among the project's images, or imported from the computer: a small window of thumbnails
    function pickImage() {
        const media = (window.H3Editor && window.H3Editor.media) || {};
        const res = media.resources ? media.resources() : { images: [] };
        return new Promise((resolve) => {
            const overlay = h("div", { class: "tk-modal sx-picker", style: "z-index:80" });
            const done = (rel) => { overlay.remove(); document.removeEventListener("keydown", onKey, true); resolve(rel || null); };
            const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(null); } };
            const grid = h("div", { class: "sx-picker-grid" }, res.images.map((f) => h("button", { class: "sx-picker-item", title: f.name, onclick: () => done(f.path) },
                h("img", { src: media.fileUrl(f.path), alt: "", class: "sx-thumb" }), h("div", { class: "sx-file-name" }, f.name))));
            const box = h("div", { class: "tk-box tk-form wide" },
                h("div", { class: "tk-box-head" }, h("b", {}, _t("sx.pick_image")), h("span", { style: "flex:1" }),
                    media.importFiles ? h("button", { class: "primary sx-picker-import", onclick: async () => { const [p] = await media.importFiles("images"); if (p) done(p); } }, _t("sx.import_from_computer")) : null,
                    h("button", { onclick: () => done(null) }, _t("plan.close"))),
                h("div", { class: "hint" }, _t("sx.pick_image_hint")),
                res.images.length ? grid : h("div", { class: "hint" }, _t("sx.no_file")));
            dropFile(box, "image", (rel) => done(rel), { single: true });
            overlay.append(box);
            overlay.addEventListener("click", (e) => { if (e.target === overlay) done(null); });
            document.addEventListener("keydown", onKey, true);
            document.body.append(overlay);
        });
    }

    // ------------------------------------------------------------------ the editor of a clip
    // ctx: plan, clip, index, free, prevClip, changed(structural), toast, media, messages, compose (the server's result
    // for this clip, or null), lastLanguage(), locked (a generated clip, read-only)
    function render(card, ctx) {
        const c = ctx.clip;
        const override = typeof c.prompt_override === "string" && c.prompt_override.trim() !== "";
        const tabs = h("span", { class: "tabs sx-tabs" },
            h("button", { class: view.tab === "fields" ? "on" : "", onclick: () => { view.tab = "fields"; ctx.redraw(); } }, _t("sx.tab_fields")),
            h("button", { class: `sx-tab-h3 ${view.tab === "h3" ? "on" : ""}`, onclick: () => { view.tab = "h3"; ctx.redraw(); } },
                _t("sx.tab_h3") + (override ? " ✎" : "")));
        card.append(h("h2", {}, h("span", { class: "grow" }, _t("plan.prompt")), tabs));
        if (override) card.append(h("div", { class: "sx-warn sx-override" }, h("span", {}, _t(view.tab === "fields" ? "sx.override_fields" : "sx.override_h3")),
            h("button", { class: "small", onclick: () => { delete c.prompt_override; ctx.changed(true); } }, _t("sx.back_to_composed"))));
        if (view.tab === "h3") { renderH3(card, ctx); return; }
        card.append(anchorsRow(ctx));
        const getItems = () => items(ctx);
        const area = (key, label, hint, { one = false } = {}) => {
            const t = h("textarea", { class: `sx-ta${one ? " sx-one" : ""}`, "data-sec": key, spellcheck: "false", placeholder: hint, value: c[key] ?? "" });
            t.addEventListener("input", () => { if (t.value) c[key] = t.value; else delete c[key]; autosize(t); ctx.changed(false); });
            attachAc(t, getItems);
            acceptDrops(t);
            requestAnimationFrame(() => autosize(t));
            return h("div", { class: "sx-box", "data-field": key }, h("div", { class: "sx-head" }, h("span", { class: "sx-code" }, label), h("span", { class: "sx-hint" }, hint)), t);
        };
        card.append(area("summary", _t("sx.summary"), _t("sx.summary_hint"), { one: true }));
        card.append(area("description", _t("sx.description"), _t("sx.description_hint")));
        card.append(area("soundscape", _t("sx.soundscape"), ctx.free ? _t("sx.soundscape_hint_free") : _t("sx.soundscape_hint_music"), { one: true }));
        card.append(area("music", _t("sx.music"), ctx.free ? _t("sx.music_hint_free") : _t("sx.music_hint_music"), { one: true }));
        const uses = h("div", { class: "sx-box", id: "sxUses" });
        card.append(uses);
        drawUses(ctx, uses);
    }
    // ---- anchors: first frame, keyframes, last frame (pictures of the project dropped or chosen)
    function anchorsRow(ctx) {
        const c = ctx.clip;
        const continues = !!c.continue && (ctx.index > 1 || !!ctx.plan.start_video);
        const a = c.anchors || {};
        const set = (mut) => { c.anchors = { ...(c.anchors || {}) }; mut(c.anchors); for (const k of ["first", "last"]) if (!c.anchors[k]) delete c.anchors[k];
            if (c.anchors.keyframes && !c.anchors.keyframes.length) delete c.anchors.keyframes; if (!Object.keys(c.anchors).length) delete c.anchors;
            pruneFiles(ctx.plan); ctx.changed(true); };
        const images = (ctx.media && ctx.media.resources ? ctx.media.resources().images : null) || [];
        const slot = (title, label, onSet, onClear, disabledWhy) => {
            const url = label ? fileUrl(ctx, label) : null;
            const choose = h("select", { class: "sx-anchor-pick", disabled: !!disabledWhy || null, title: disabledWhy || _t("sx.anchor_choose"),
                onchange: (e) => { if (e.target.value) onSet(fileLabel(ctx.plan, e.target.value, "image")); } },
                h("option", { value: "" }, label ? "…" : "+"), images.map((f) => h("option", { value: f.path }, f.name)));
            const node = h("div", { class: `sx-anchor${disabledWhy ? " off" : ""}`, title: disabledWhy || "" },
                h("div", { class: "sx-anchor-t" }, title),
                url ? h("img", { src: url, alt: "", class: "sx-thumb" }) : h("div", { class: "sx-thumb sx-thumb-empty" }, disabledWhy ? "🔒" : "—"),
                h("div", { class: "sx-row" }, choose, label ? h("button", { class: "small", title: _t("sx.anchor_remove"), onclick: onClear }, "✕") : null));
            if (!disabledWhy) dropFile(node, "image", (rel) => onSet(fileLabel(ctx.plan, rel, "image")));
            return node;
        };
        const keys = (a.keyframes || []).map((k, i) => {
            const at = h("input", { type: "number", class: "sx-at", step: "0.1", min: 0, value: k.at ?? "", title: _t("sx.keyframe_at_hint"),
                onchange: (e) => set((x) => { x.keyframes = [...x.keyframes]; x.keyframes[i] = { ...x.keyframes[i], at: Math.round((+e.target.value || 0) * 1000) / 1000 }; }) });
            const s = slot(_t("sx.anchor_keyframe"), k.file, (label) => set((x) => { x.keyframes = [...x.keyframes]; x.keyframes[i] = { ...x.keyframes[i], file: label }; }),
                () => set((x) => { x.keyframes = x.keyframes.filter((_y, j) => j !== i); }));
            s.append(h("div", { class: "sx-row sx-hint" }, _t("sx.keyframe_at"), at, "s"));
            return s;
        });
        const secs = H3.isRun(c.frames) ? c.frames / H3.FPS : 0;
        return h("div", { class: "sx-box sx-anchors" },
            h("div", { class: "sx-head" }, h("span", { class: "sx-code" }, _t("sx.anchors")), h("span", { class: "sx-hint" }, _t("sx.anchors_hint"))),
            h("div", { class: "sx-anchor-row" },
                slot(_t("sx.anchor_first"), a.first, (label) => set((x) => { x.first = label; }), () => set((x) => { delete x.first; }),
                    continues ? _t("sx.anchor_first_off") : null),
                ...keys,
                h("button", { class: "small sx-addkey", title: _t("sx.add_keyframe_hint"), onclick: () => {
                    const first = images[0];
                    if (!first) { alert(_t("sx.import_pictures_first")); return; }
                    set((x) => { x.keyframes = [...(x.keyframes || []), { at: Math.round(secs * 500) / 1000 || 1, file: fileLabel(ctx.plan, first.path, "image") }]; });
                } }, _t("sx.add_keyframe")),
                slot(_t("sx.anchor_last"), a.last, (label) => set((x) => { x.last = label; }), () => set((x) => { delete x.last; }))));
    }
    // ---- the subjects of the clip (the ones its texts name), with their settings, and the counts H3 allows
    function drawUses(ctx, node) {
        const box = node || document.getElementById("sxUses");
        if (!box) return;
        const c = ctx.clip;
        const subjects = subjectsOf(ctx);
        const names = H3.clipSubjects(ctx.plan, c, ctx.index);
        const rows = names.map((name) => {
            const s = subjects[name];
            if (!s) return h("div", { class: "sx-row sx-use" }, h("span", { class: "sx-chip sx-chipX" }, "@" + name),
                h("span", { class: "sx-hint" }, _t("sx.unknown_subject")),
                ctx.locked ? null : h("button", { class: "small", onclick: () => editSubject(ctx, null, name) }, _t("sx.create_subject", { name })));
            const u = useOf(c, name);
            const keep = h("select", { class: "sx-keep", title: _t("sx.keep_hint"), onchange: (e) => { setUse(c, name, "keep", e.target.value, "identical"); ctx.changed(true); } },
                H3.KEEPS.map((k) => h("option", { value: k, selected: (u.keep || "identical") === k || null, title: _t("sx.keep_h3_" + k) }, _t("sx.keep_" + k))));
            const voice = ctx.free && s.voice ? h("select", { class: "sx-voicekeep", title: _t("sx.voice_keep_hint"),
                onchange: (e) => { setUse(c, name, "voice_keep", e.target.value, "timbre"); ctx.changed(true); } },
                H3.VOICE_KEEPS.map((k) => h("option", { value: k, selected: (u.voice_keep || "timbre") === k || null }, "🎙 " + _t("sx.voice_keep_" + k)))) : null;
            const note = h("input", { class: "sx-note", value: u.note || "", placeholder: _t("sx.note_placeholder"), title: _t("sx.note_hint"),
                oninput: (e) => { setUse(c, name, "note", e.target.value.trim() ? e.target.value : "", ""); ctx.changed(false); } });
            const img = subjectThumb(ctx, name, subjects);
            const spk = ctx.compose && (ctx.compose.speakers || []).find(([n]) => n === name);
            return h("div", { class: "sx-row sx-use", "data-subject": name },
                spk ? h("span", { class: "sx-speaker", title: _t("sx.speaker_hint", { k: spk[1] }) }, `🗣 S${spk[1]}`) : null,
                h("span", { class: "sx-chip sx-chipS", draggable: "true", ondragstart: dragText("@" + name), title: s.description || "" },
                    img ? h("img", { src: img, alt: "" }) : h("span", {}, KIND_ICON[s.kind || "person"]), "@" + name),
                keep, voice, note);
        });
        const got = H3.clipFiles(ctx.plan, c, ctx.index);
        const edits = !!H3.editSlice(ctx.plan, ctx.index);
        const total = got.pictures.length + got.voices.length + (edits ? 1 : 0);
        const count = (n, max, label) => h("span", { class: n > max ? "sx-over-limit" : "" }, `${n}/${max} ${label}`);
        box.replaceChildren(h("div", { class: "sx-head" }, h("span", { class: "sx-code" }, _t("sx.clip_subjects")), h("span", { class: "sx-hint" }, _t("sx.clip_subjects_hint"))),
            rows.length ? h("div", {}, ...rows) : h("div", { class: "hint" }, _t("sx.no_subject_named")),
            h("div", { class: "sx-quota" }, count(got.pictures.length, H3.MAX_REFS, "🖼"), " · ",
                ctx.free ? count(got.voices.length, H3.MAX_VOICES, "🎙") : null, ctx.free ? " · " : null,
                count(total, H3.MAX_REF_FILES, _t("sx.files"))));
    }
    // ---- the H3 prompt: composed by the server, editable (prompt_override); the numbers of the clip beside it
    function renderH3(card, ctx) {
        const c = ctx.clip;
        const made = ctx.compose;
        const override = typeof c.prompt_override === "string" && c.prompt_override.trim() !== "";
        const legend = h("div", { class: "sx-legend", id: "sxLegend" });
        const ta = h("textarea", { class: "sx-ta sx-h3", spellcheck: "false", id: "rawPrompt",
            value: override ? c.prompt_override : made ? made.prompt : "" });
        ta.addEventListener("input", () => { c.prompt_override = ta.value; autosize(ta); ctx.changed(false); });
        attachAc(ta, () => items(ctx));
        requestAnimationFrame(() => autosize(ta));
        card.append(h("div", { class: "hint" }, _t(override ? "sx.h3_hint_override" : "sx.h3_hint")), legend, made || override ? ta : h("div", { class: "hint" }, _t("sx.composing")));
        drawLegend(ctx, legend);
    }
    function drawLegend(ctx, node) {
        const box = node || document.getElementById("sxLegend");
        if (!box) return;
        const made = ctx.compose;
        if (!made) { box.replaceChildren(); return; }
        const L = made.legend;
        const subjects = subjectsOf(ctx);
        const fileName = (label) => { const f = H3.definitions(ctx.plan, ctx.clip).files[label]; return f && f.file ? f.file.split("/").pop() : label; };
        box.replaceChildren(
            ...L.subjects.map((n, i) => h("span", { class: "sx-chip sx-chipS", title: (subjects[n] || {}).description || "" }, `<Subject ${i + 1}> = @${n}`)),
            ...L.pictures.map((f, i) => h("span", { class: "sx-chip sx-chipR", title: fileName(f) },
                fileUrl(ctx, f) ? h("img", { src: fileUrl(ctx, f), alt: "" }) : null, `<Picture ${i + 1}>`)),
            ...L.audio.map((f, i) => h("span", { class: "sx-chip sx-chipD", title: f === "<video sound>" ? _t("sx.video_sound") : fileName(f) },
                `<Audio ${i + 1}> ${f === "<video sound>" ? "🎞" : "🎙 " + fileName(f)}`)),
            ...(L.video ? [h("span", { class: "sx-chip sx-chipP" }, `<Video 1> 🎞`)] : []),
            ...(made.speakers || []).map(([n, k]) => h("span", { class: "sx-chip sx-chipD", title: _t("sx.speaker_hint", { k }) }, `(S${k}) = @${n}`)));
    }
    // the parts of the editor that follow the server's answer (the whole editor is not drawn again: the caret stays)
    function refreshCompose(ctx) {
        drawLegend(ctx);
        const ta = document.querySelector("textarea.sx-h3");
        const c = ctx.clip;
        if (ta && !(typeof c.prompt_override === "string" && c.prompt_override.trim()) && ctx.compose && document.activeElement !== ta) {
            ta.value = ctx.compose.prompt;
            autosize(ta);
        }
        drawUses(ctx);
        refreshChecks(ctx);
    }

    // ------------------------------------------------------------------ a subject of the plan (window)
    // name null: a new subject (`suggest`: the name typed in a text)
    function editSubject(ctx, name, suggest) {
        const plan = ctx.plan;
        plan.subjects = plan.subjects || {};
        const isNew = !name;
        const s = JSON.parse(JSON.stringify(isNew ? { kind: "person", description: "", pictures: [] } : plan.subjects[name]));
        const media = ctx.media || {};
        const res = media.resources ? media.resources() : { images: [], voices: [] };
        const nameIn = h("input", { class: "sx-sname", value: name || suggest || "", placeholder: _t("sx.subject_name_placeholder") });
        const kind = h("select", { class: "sx-skind" }, H3.SUBJECT_KINDS.map((k) => h("option", { value: k, selected: (s.kind || "person") === k || null }, `${KIND_ICON[k]} ${_t("sx.kind_" + k)}`)));
        const desc = h("textarea", { class: "sx-ta sx-sdesc", placeholder: _t("sx.subject_desc_placeholder"), value: s.description || "" });
        const pics = h("div", { class: "sx-pics" });
        const frozen = !isNew && (ctx.frozenSubjects || []).includes(name);
        // 0.48.2: a file the plan declares without an image yet (an imported plan) gets one here; applied on « save »,
        // under its own label: its note, the role of the picture and every other use of the label keep it
        const fills = {};
        const relOf = (label) => fills[label] || (plan.files[label] || {}).file || null;
        const drawPics = () => {
            pics.replaceChildren(...(s.pictures || []).map((p, i) => {
                const rel = relOf(p.file);
                const note = (plan.files[p.file] || {}).note || "";
                // an empty label gets the image; a picture already there is replaced for this subject only
                const setRel = (r) => { if (!r) return; if (rel) p.file = fileLabel(plan, r, "image"); else fills[p.file] = r; drawPics(); };
                const choose = async () => { if (!frozen) setRel(await pickImage()); };
                const thumb = rel
                    ? h("img", { src: media.fileUrl ? media.fileUrl(rel) : "", alt: "", class: "sx-thumb sx-pic-thumb", title: frozen ? "" : _t("sx.replace_picture"), onclick: choose })
                    : h("div", { class: "sx-thumb sx-pic-missing", title: _t("sx.missing_picture_title", { label: p.file }) + (note ? "\n" + note : ""), onclick: choose },
                        h("b", {}, p.file), note ? h("span", {}, note) : null, h("span", { class: "sx-pic-missing-act" }, _t("sx.missing_picture_choose")));
                const item = h("div", { class: `sx-pic${rel ? "" : " missing"}`, "data-label": p.file },
                    thumb,
                    h("input", { class: "sx-role", value: p.role || "", placeholder: _t("sx.role_placeholder", { v0: _t("sx.role_default_" + kind.value) }),
                        oninput: (e) => { if (e.target.value.trim()) p.role = e.target.value; else delete p.role; } }),
                    h("button", { class: "small", title: _t("sx.remove_picture"), onclick: () => { s.pictures.splice(i, 1); drawPics(); } }, "✕"));
                if (!frozen) dropFile(item, "image", setRel, { single: true });
                return item;
            }),
            h("div", { class: "sx-pic sx-pic-add" },
                h("select", { class: "sx-addpic", onchange: (e) => { if (e.target.value) { s.pictures = [...(s.pictures || []), { file: fileLabel(plan, e.target.value, "image") }]; drawPics(); } } },
                    h("option", { value: "" }, _t("sx.add_picture")), res.images.map((f) => h("option", { value: f.path }, f.name))),
                media.importFiles ? h("button", { class: "small", onclick: async () => {
                    const paths = await media.importFiles("images");
                    for (const p of paths || []) s.pictures = [...(s.pictures || []), { file: fileLabel(plan, p, "image") }];
                    drawPics();
                } }, _t("sx.import")) : null,
                h("span", { class: "hint" }, _t("sx.or_drop_a_picture"))));
        };
        if (!frozen) dropFile(pics, "image", (rel) => { s.pictures = [...(s.pictures || []), { file: fileLabel(plan, rel, "image") }]; drawPics(); });
        kind.addEventListener("change", drawPics);
        drawPics();
        // a voice the plan declares without a file yet stays chosen (« to supply ») until another one is picked
        const missingVoice = s.voice && !relOf(s.voice) ? s.voice : null;
        const voice = h("select", { class: "sx-svoice", disabled: !ctx.free || null, title: ctx.free ? "" : _t("sx.voice_music_video") },
            h("option", { value: "" }, _t("sx.no_voice")),
            missingVoice ? h("option", { value: "label:" + missingVoice, selected: true }, _t("sx.voice_to_supply", { label: missingVoice })) : null,
            res.voices.map((f) => h("option", { value: f.path, selected: (s.voice && relOf(s.voice) === f.path) || null }, f.name)));
        if (ctx.free && !frozen) dropFile(voice, "voice", (rel) => { voice.append(h("option", { value: rel, selected: true }, rel.split("/").pop())); voice.value = rel; }, { single: true });
        const body = h("div", { class: "sx-subject-form" },
            h("div", { class: "grid2" }, h("label", {}, _t("sx.subject_name")), nameIn, h("label", {}, _t("sx.subject_kind")), kind),
            h("label", {}, _t("sx.subject_desc")), desc,
            h("label", {}, _t("sx.subject_pictures")), h("div", { class: "hint" }, _t("sx.subject_pictures_hint")), pics,
            h("label", {}, _t("sx.subject_voice")), h("div", { class: "sx-row" }, voice,
                media.importFiles && ctx.free ? h("button", { class: "small", onclick: async () => {
                    const [p] = await media.importFiles("voices");
                    if (p) { voice.append(h("option", { value: p, selected: true }, p.split("/").pop())); voice.value = p; }
                } }, _t("sx.import")) : null));
        const overlay = h("div", { class: "tk-modal", style: "z-index:70" });
        const close = () => overlay.remove();
        const save = () => {
            const newName = nameIn.value.trim();
            if (!H3.SUBJECT_NAME_RE.test(newName)) { alert(_t("sx.subject_name_invalid")); return; }
            if (newName !== name && newName in plan.subjects) { alert(_t("sx.subject_name_taken", { name: newName })); return; }
            for (const [label, rel] of Object.entries(fills)) if (plan.files[label]) plan.files[label].file = rel;
            s.kind = kind.value;
            if (desc.value.trim()) s.description = desc.value.trim(); else delete s.description;
            if (voice.value.startsWith("label:")) s.voice = voice.value.slice(6);
            else if (voice.value && missingVoice && plan.files[missingVoice]) { plan.files[missingVoice].file = voice.value; s.voice = missingVoice; }   // the declared voice gets its file
            else if (voice.value) s.voice = fileLabel(plan, voice.value, "voice"); else delete s.voice;
            if (!isNew && newName !== name) renameSubject(plan, name, newName, ctx.isLocked || ctx.lockedCount || 0);
            plan.subjects[newName] = s;
            pruneFiles(plan);
            close();
            ctx.changed(true);
            if (isNew && ctx.toast) ctx.toast(_t("sx.subject_created", { name: newName }));
        };
        const remove = async () => {
            const users = (plan.clips || []).filter((c, i) => !(ctx.isLocked ? ctx.isLocked(i) : i < (ctx.lockedCount || 0)) && H3.clipSubjects(plan, c, i + 1).includes(name)).length;
            if (!(await H3Dialog.confirm(users ? _t("sx.delete_subject_used", { name, count: users }) : _t("sx.delete_subject", { name })))) return;
            delete plan.subjects[name];
            pruneFiles(plan);
            close();
            ctx.changed(true);
        };
        // 0.48: a subject of a master plan frozen by the takes of its branch is shown, not changed
        if (frozen) {
            for (const el of body.querySelectorAll("input, textarea, select, button")) { el.disabled = true; if (el.tagName !== "SELECT") el.readOnly = true; }
            body.prepend(h("div", { class: "locked-banner sx-frozen-subject" }, _t("sx.subject_frozen")));
        }
        overlay.append(h("div", { class: "tk-box tk-form wide" },
            h("div", { class: "tk-box-head" }, h("b", {}, isNew ? _t("sx.new_subject") : _t("sx.subject_title", { name })), h("span", { style: "flex:1" }),
                isNew || frozen ? null : h("button", { class: "danger", onclick: remove }, _t("sx.delete")),
                h("button", { onclick: close }, _t("plan.close")), frozen ? null : h("button", { class: "primary sx-save", onclick: save }, _t("sx.save"))),
            body));
        overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
        document.body.append(overlay);
        requestAnimationFrame(() => { autosize(desc); (isNew ? nameIn : desc).focus(); });
    }

    // ------------------------------------------------------------------ the library (right column)
    function palette(side, ctx) {
        const plan = ctx.plan;
        const sect = (title, ...kids) => h("section", { class: "box sx-pal" }, h("h2", {}, title), ...kids);
        const media = ctx.media || {};
        // subjects of the plan
        const subjects = plan.subjects || {};
        const used = ctx.clip ? H3.clipSubjects(plan, ctx.clip, ctx.index) : [];
        const list = Object.entries(subjects).map(([n, s]) => {
            const thumbs = (s.pictures || []).map((p) => { const rel = (plan.files[p.file] || {}).file; return rel && media.fileUrl ? h("img", { src: media.fileUrl(rel), alt: "", title: p.role || "", class: "sx-mini" })
                : h("span", { class: "sx-mini sx-mini-missing", title: _t("sx.missing_picture_title", { label: p.file }) }, "?"); });
            return h("div", { class: `sx-lib-subject${used.includes(n) ? " in-clip" : ""}`, "data-subject": n },
                h("span", { class: "sx-chip sx-chipS", draggable: "true", ondragstart: dragText("@" + n), title: _t("sx.drag_subject") }, `${KIND_ICON[s.kind || "person"]} @${n}`),
                h("span", { class: "sx-lib-thumbs" }, ...thumbs, s.voice ? h("span", { title: _t("sx.has_voice") }, "🎙") : null),
                h("button", { class: "small sx-edit", title: (ctx.frozenSubjects || []).includes(n) ? _t("sx.subject_frozen_short") : _t("sx.edit_subject"), onclick: () => editSubject(ctx, n) },
                    (ctx.frozenSubjects || []).includes(n) ? "🔒" : "✎"),
                h("div", { class: "sx-desc" }, s.description || ""));
        });
        side.append(sect(_t("sx.library_subjects"),
            h("div", { class: "hint" }, _t("sx.library_subjects_hint")),
            list.length ? h("div", {}, ...list) : h("div", { class: "hint" }, _t("sx.no_subject_yet")),
            h("button", { class: "small sx-newsubject", onclick: () => editSubject(ctx, null) }, _t("sx.new_subject_button"))));
        // 0.48.2: the files the plan declares without an image or a voice yet (an imported plan): filled here, under their label
        const missing = Object.entries(plan.files || {}).filter(([, f]) => f && !f.file && (f.kind === "image" || (f.kind === "voice" && ctx.free)));
        if (missing.length && media.fileUrl) {
            const users = (label) => Object.entries(subjects).filter(([, s]) => (s.pictures || []).some((p) => p.file === label) || s.voice === label).map(([n]) => "@" + n);
            const set = (label) => (rel) => { if (!rel || !plan.files[label]) return; plan.files[label].file = rel; ctx.changed(true); };
            side.append(sect(_t("sx.missing_files"), h("div", { class: "hint" }, _t("sx.missing_files_hint")),
                ...missing.map(([label, f]) => {
                    const row = h("div", { class: "sx-missing", "data-label": label },
                        h("div", { class: "sx-missing-head" }, h("b", {}, (f.kind === "voice" ? "🎙 " : "🖼 ") + label),
                            h("span", { class: "hint" }, users(label).join(" ")), h("span", { style: "flex:1" }),
                            f.kind === "image" ? h("button", { class: "small", onclick: async () => set(label)(await pickImage()) }, _t("sx.missing_picture_choose"))
                                : media.importFiles ? h("button", { class: "small", onclick: async () => { const [p] = await media.importFiles("voices"); set(label)(p); } }, _t("sx.import")) : null),
                        f.note ? h("div", { class: "hint" }, f.note) : null);
                    dropFile(row, f.kind, set(label), { single: true });
                    return row;
                })));
        }
        // files of the project
        const res = media.resources ? media.resources() : null;
        if (res) {
            const tab = (k) => h("button", { class: view.files === k ? "on" : "", onclick: () => { view.files = k; ctx.redraw(); } }, _t("sx.files_" + k));
            const files = (res[view.files] || []).map((f) => {
                const kind = KIND_OF_FOLDER[view.files];
                const url = media.fileUrl(f.path);
                return h("div", { class: "sx-file", draggable: "true", ondragstart: dragFile(f.path, kind), title: f.name },
                    kind === "image" ? h("img", { src: url, alt: f.name, class: "sx-thumb" }) : h("div", { class: "sx-thumb sx-thumb-empty" }, "🎙"),
                    h("div", { class: "sx-file-name" }, f.name),
                    kind === "voice" ? playButton(url) : null);
            });
            const box = sect(_t("sx.library_files"),
                h("div", { class: "tabs sx-filetabs" }, tab("images"), tab("voices"),
                    media.importFiles ? h("button", { class: "small", onclick: async () => { await media.importFiles(view.files); ctx.redraw(); } }, _t("sx.import")) : null),
                h("div", { class: "hint" }, _t("sx.library_files_hint")),
                files.length ? h("div", { class: "sx-files" }, ...files) : h("div", { class: "hint" }, _t("sx.no_file")));
            // files dropped from the computer are imported (images, or voices on the voices tab)
            box.classList.add("sx-files-box");
            box.addEventListener("dragover", (e) => { if (isOsDrag(e)) { e.preventDefault(); box.classList.add("sx-over"); } });
            box.addEventListener("dragleave", () => box.classList.remove("sx-over"));
            box.addEventListener("drop", async (e) => {
                box.classList.remove("sx-over");
                if (!isOsDrag(e) || !e.dataTransfer.files.length) return;
                e.preventDefault();
                const done = await importDropped(e, KIND_OF_FOLDER[view.files], false);
                if (done.length) ctx.redraw();
            });
            side.append(box);
        }
        if (ctx.clip) {
            const dl = dialogueItems(ctx);
            if (dl.length) side.append(sect(ctx.free ? _t("sections.lines") : _t("sections.lyrics"), ...dl.map((d) => h("div", { class: "sx-dl" },
                h("span", { class: "sx-chip sx-chipD", draggable: "true", ondragstart: dragText(d.ins), title: d.ins }, `⠿ ${d.label}`),
                h("div", { class: "sx-dltext" }, d.hint)))));
            side.append(sect(_t("sections.stock_sentences"), h("div", { class: "sx-chips" }, snippets(ctx, used[0]).map((p) =>
                h("span", { class: "sx-chip sx-chipP", draggable: "true", ondragstart: dragText(p.ins), title: p.ins }, p.label)))));
            side.append(checksBox(ctx));
        }
    }
    function checksBox(ctx) {
        const checks = (ctx.messages || []).map((m) => ({ level: m.level, text: m.text }));
        return h("section", { class: "box sx-pal", id: "sxChecks" }, h("h2", {}, _t("sections.clip_checks")),
            checks.length ? h("ul", { class: "vlist" }, checks.map((m) => h("li", { class: m.level }, m.text)))
                : h("div", { class: "hint", style: "color:var(--ok)" }, _t("sections.nothing_to_report")));
    }
    function refreshChecks(ctx) {
        const old = document.getElementById("sxChecks");
        if (old) old.replaceWith(checksBox(ctx));
    }
    function playButton(url) {
        const audio = h("audio", { src: url, preload: "none" });
        const b = h("button", { class: "small", title: _t("sections.play_the_voice"), onclick: (e) => { e.stopPropagation(); if (audio.paused) { audio.currentTime = 0; audio.play(); } else audio.pause(); } }, _t("sections.voice_2"));
        audio.addEventListener("play", () => { b.textContent = _t("sections.voice_3"); });
        audio.addEventListener("pause", () => { b.textContent = _t("sections.voice_2"); });
        audio.addEventListener("ended", () => { b.textContent = _t("sections.voice_2"); });
        return h("span", {}, b, audio);
    }

    return {
        fileLabel, pruneFiles, renameSubject, useOf, setUse, inheritedClip,
        render, palette, refreshChecks, refreshCompose, editSubject, closeAc, attachAc, acceptDrops, KIND_ICON,
    };
})();
if (typeof module !== "undefined") module.exports = H3Sections;
