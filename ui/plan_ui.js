// ---------------------------------------------------------------------------------------------
// H3 Clip Plan editor - user interface
// ---------------------------------------------------------------------------------------------
(() => {
    const FPS = H3.FPS;
    const SCENE_COLORS = ["#3a6ea5", "#8a5a9e", "#3f8f6b", "#a8693a", "#9b4b5c", "#4f7f8f", "#7d7a3a", "#5b5fa8"];

    const S = {
        plan: null, sel: 0, fileName: "", handle: null, dirty: false,
        undo: [], redo: [], lastSnap: "", snapTimer: null,
        tab: "sections", focusSection: 3, messages: [],
    };

    // ------------------------------------------------------------------ small helpers
    const $ = (id) => document.getElementById(id);
    function h(tag, attrs = {}, ...kids) {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v === undefined || v === null || v === false) continue;
            if (k === "class") node.className = v;
            else if (k === "style") node.style.cssText = v;
            else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
            else if (k === "value") node.value = v;
            else if (k === "checked") node.checked = !!v;
            else if (k === "selected") node.selected = !!v;
            else if (k === "html") node.innerHTML = v;
            else node.setAttribute(k, v === true ? "" : v);
        }
        for (const kid of kids.flat()) {
            if (kid === null || kid === undefined || kid === false) continue;
            node.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
        }
        return node;
    }
    const sec = (frames, digits = 3) => (frames / FPS).toFixed(digits).replace(".", H3I18n.decimal()) + " s";
    const secv = (seconds, digits = 1) => seconds.toFixed(digits).replace(".", H3I18n.decimal()) + " s";
    const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    const clips = () => S.plan.clips;
    const isFree = () => H3.mode(S.plan) === "free";
    const curClip = () => clips()[S.sel];
    function toast(text) {
        const t = $("toast");
        t.textContent = text;
        t.classList.add("on");
        clearTimeout(toast.timer);
        toast.timer = setTimeout(() => t.classList.remove("on"), 2200);
    }

    // ------------------------------------------------------------------ model changes
    function snapshot() { return JSON.stringify({ plan: S.plan, sel: S.sel }); }
    function pushHistory() {
        clearTimeout(S.snapTimer);
        S.snapTimer = null;
        const snap = snapshot();
        if (snap === S.lastSnap) return;
        if (S.lastSnap) S.undo.push(S.lastSnap);
        if (S.undo.length > 200) S.undo.shift();
        S.redo = [];
        S.lastSnap = snap;
        updateUndoButtons();
    }
    // structural: re-render everything now; otherwise (typing) refresh the live parts only.
    function changed(structural) {
        S.dirty = true;
        if (structural) { pushHistory(); renderAll(); }
        else {
            clearTimeout(S.snapTimer);
            S.snapTimer = setTimeout(pushHistory, 700);
            renderLive();
        }
    }
    function restore(snap, sel) {
        const data = JSON.parse(snap);
        S.plan = data.plan;
        S.sel = Math.max(0, Math.min(sel ?? data.sel, clips().length - 1));
        S.lastSnap = snap;
        S.dirty = true;
        renderAll();
    }
    function undo() {
        if (S.snapTimer) pushHistory();
        if (!S.undo.length) return;
        const where = JSON.parse(S.lastSnap).sel;   // show the clip where the undone change was made
        S.redo.push(S.lastSnap);
        restore(S.undo.pop(), where);
        updateUndoButtons();
    }
    function redo() {
        if (!S.redo.length) return;
        S.undo.push(S.lastSnap);
        restore(S.redo.pop());
        updateUndoButtons();
    }
    function updateUndoButtons() {
        $("btnUndo").disabled = !S.undo.length && !S.snapTimer;
        $("btnRedo").disabled = !S.redo.length;
    }

    function setPlan(plan, fileName, handle) {
        if (!plan || typeof plan !== "object" || Array.isArray(plan)) throw new Error(_t("plan.the_file_does_not_hold_a"));
        if (!Array.isArray(plan.clips)) plan.clips = [];
        if (!plan.clips.length) plan.clips.push(newClip(1, plan));
        if (!plan.refs || typeof plan.refs !== "object" || Array.isArray(plan.refs)) plan.refs = {};
        S.plan = plan;
        S.sel = 0;
        S.fileName = fileName || "plan.json";
        S.handle = handle || null;
        S.dirty = false;
        S.undo = []; S.redo = [];
        S.lastSnap = snapshot();
        renderAll();
        updateUndoButtons();
        if (plan.version !== 3) toast(_t("plan.plan_version_it_will_be_saved", { version: plan.version }));
        if (!$("takesView").hidden) window.H3Takes?.onShow();
    }

    function newPlan(mode) {
        const plan = { version: 3, project: "nouveau_projet", mode, refs: {}, context_frames: 39, crossfade_frames: 0, clips: [] };
        if (mode === "music_video") plan.song = { file: "chanson.mp3", duration_seconds: 60 };
        plan.clips.push(newClip(1, plan));
        return plan;
    }

    function newClip(index, plan, after) {
        const names = new Set((plan.clips || []).map((c) => c.name));
        let k = index, name;
        do { name = `clip_${String(k).padStart(3, "0")}`; k++; } while (names.has(name));
        const free = H3.mode(plan) === "free";
        const clip = { name, frames: after ? after.frames : 209, continue: !!after, refs: after ? [...(after.refs || [])] : [] };
        if (free) clip.dialogue = [];
        // a clip added after another keeps its subjects, retention_analysis, style and soundscape
        const inherited = after && typeof H3Sections !== "undefined" ? H3Sections.inheritedPrompt(after, clip, index, free) : null;
        clip.prompt = inherited || H3.skeleton(clip, index, free);
        if (inherited) {
            const names = H3Sections.subjectNames(after, H3.parseSections(after.prompt));
            if (names.length) clip._subjects = names;
        }
        return clip;
    }

    // ------------------------------------------------------------------ file handling
    async function openFile() {
        if (S.dirty && !await H3Dialog.confirm(_t("plan.unsaved_changes_will_be_lost_continue"))) return;
        if (window.showOpenFilePicker) {
            try {
                const [handle] = await window.showOpenFilePicker({ types: [{ description: _t("plan.h3_plan"), accept: { "application/json": [".json"] } }] });
                const file = await handle.getFile();
                loadFile(file, handle);
                return;
            } catch (e) {
                if (e.name === "AbortError") return;
            }
        }
        $("filePicker").click();
    }
    async function loadFile(file, handle) {
        try {
            const text = await file.text();
            setPlan(JSON.parse(text.replace(/^﻿/, "")), file.name, handle);
            toast(_t("plan.file_opened", { name: file.name }));
        } catch (e) {
            alert(_t("plan.cannot_open_this_file", { message: e.message }));
        }
    }
    function serialize() {
        S.plan.version = 3;
        return JSON.stringify(S.plan, null, 2) + "\n";
    }
    async function save(asNew) {
        if (S.snapTimer) pushHistory();
        if (window.H3Editor && window.H3Editor.saveHook) {     // Encore: the plan lives in the project folder
            try {
                await window.H3Editor.saveHook(S.plan);
                S.dirty = false;
                renderAll();
            } catch (e) { alert(_t("plan.cannot_save", { message: e.message })); }
            return;
        }
        const errors = S.messages.filter((m) => m.level === "error").length;
        if (errors && !await H3Dialog.confirm(_t("plan.the_plan_has_error_s_the", { errors }))) return;
        const text = serialize();
        let handle = asNew ? null : S.handle;
        if (!handle && window.showSaveFilePicker) {
            try {
                handle = await window.showSaveFilePicker({ suggestedName: S.fileName, types: [{ description: _t("plan.h3_plan"), accept: { "application/json": [".json"] } }] });
            } catch (e) {
                if (e.name === "AbortError") return;
                handle = null;
            }
        }
        if (handle) {
            try {
                const writable = await handle.createWritable();
                await writable.write(text);
                await writable.close();
                S.handle = handle;
                S.fileName = handle.name || S.fileName;
                S.dirty = false;
                renderHeader();
                toast(_t("plan.saved_in", { fileName: S.fileName }));
                return;
            } catch (e) {
                console.warn(e);
            }
        }
        let name = S.fileName;
        if (asNew) {
            const answer = await H3Dialog.prompt(_t("plan.file_name"), S.fileName);
            if (!answer) return;
            name = /\.json$/i.test(answer) ? answer : answer + ".json";
        }
        const link = h("a", { href: URL.createObjectURL(new Blob([text], { type: "application/json" })), download: name });
        document.body.appendChild(link);
        link.click();
        setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
        S.fileName = name;
        S.dirty = false;
        renderHeader();
        toast(_t("plan.downloaded", { name }));
    }

    // ------------------------------------------------------------------ rendering
    function renderAll() {
        S.messages = H3.validate(S.plan);
        renderHeader();
        renderTimeline();
        renderPalette();
        if (S.settingsBox && S.settingsBox.isConnected) renderSettings(S.settingsBox);
        renderList();
        renderEditor();
    }
    function renderLive() {
        S.messages = H3.validate(S.plan);
        renderHeader();
        renderTimeline();
        renderValidation();
        renderRefKinds();
        renderList();
        renderClipMessages();
        renderTiming();
        renderRate();
        renderPreview();
        updateUndoButtons();
        clearTimeout(S.checksTimer);
        S.checksTimer = setTimeout(() => { if (curClip()) H3Sections.refreshChecks(sectionsCtx()); }, 300);
    }

    function renderHeader() {
        $("fileName").innerHTML = "";
        $("fileName").append(S.fileName, S.dirty ? h("span", { class: "dirty" }, " ●") : "");
        document.title = _t("plan.h3_plan_editor", { v0: S.dirty ? "● " : "", fileName: S.fileName });
        const e = S.messages.filter((m) => m.level === "error").length;
        const w = S.messages.filter((m) => m.level === "warning").length;
        const badge = $("badge");
        badge.className = "badge " + (e ? "err" : w ? "warn" : "ok");
        badge.textContent = e ? _t("plan.error_s_warning_s", { e, w }) : w ? _t("plan.valid_warning_s", { w }) : _t("plan.valid_plan");
    }

    function clipStatus(n) {
        const own = S.messages.filter((m) => m.clip === n);
        return { e: own.some((m) => m.level === "error"), w: own.some((m) => m.level === "warning") };
    }

    function renderTimeline() {
        const box = $("timeline");
        box.innerHTML = "";
        if (!H3.framesLegal(S.plan)) {
            box.append(h("div", { class: "tl-empty" }, _t("plan.timeline_unavailable_a_clip_length_is")));
            return;
        }
        const rows = H3.timeline(S.plan);
        const total = rows[rows.length - 1].end;
        const songDur = !isFree() && S.plan.song && typeof S.plan.song.duration_seconds === "number" ? S.plan.song.duration_seconds : null;
        const span = Math.max(total / FPS, songDur || 0) + 0.5;
        const width = Math.max(box.clientWidth - 26, 300);
        const pps = Math.max(width / span, 14);
        const x = (frames) => (frames / FPS) * pps;
        const scenes = [];
        let scene = -1;
        rows.forEach((r) => { if (!r.continue) scene++; scenes.push(scene); });
        const nScenes = scene + 1;

        box.append(h("div", { class: "tl-head" },
            h("span", {}, _t("plan.length"), h("b", {}, sec(total, 2))),
            h("span", {}, h("b", {}, rows.length), " clips"),
            h("span", {}, h("b", {}, nScenes), nScenes > 1 ? _t("plan.scenes_continuous_shots") : _t("plan.scene_continuous_shot")),
            h("span", {}, "mode ", h("b", {}, isFree() ? _t("plan.free") : _t("plan.music_video"))),
            songDur !== null ? h("span", {}, _t("plan.song_2"), h("b", {}, secv(songDur, 2))) : null));

        const tl = h("div", { class: "tl", style: `width:${span * pps}px` });
        const ruler = h("div", { class: "ruler" });
        const step = pps > 60 ? 1 : pps > 25 ? 2 : 5;
        for (let t = 0; t <= span; t += step) ruler.append(h("div", { class: "tick", style: `left:${t * pps}px` }, `${t}s`));
        tl.append(ruler);
        rows.forEach((r, i) => {
            const st = clipStatus(r.index);
            const left = x(r.visible), w = Math.max(x(r.end) - x(r.visible) - 1, 3);
            const block = h("div", {
                class: `block${i === S.sel ? " sel" : ""}${st.e ? " has-err" : ""}${st.w ? " has-warn" : ""}`,
                style: `left:${left}px;width:${w}px;background:${SCENE_COLORS[scenes[i] % SCENE_COLORS.length]}`,
                title: `#${r.index} ${r.name}\n${r.continue ? _t("plan.continuation") : r.index === 1 ? _t("plan.start") : _t("plan.new_scene_cut")}\nvisible ${sec(r.visible)} → ${sec(r.end)}\n${r.frames} images`,
                onclick: () => select(i),
            }, h("span", { class: "n" }, r.index), h("span", {}, r.name), " ", h("span", { class: "d" }, secv((r.end - r.visible) / FPS)));
            tl.append(block);
            if (r.context) {
                tl.append(h("div", {
                    class: `lead ${r.continue ? "ctx" : "hidden"}`,
                    style: `left:${x(r.raw_start)}px;width:${x(r.visible) - x(r.raw_start)}px`,
                    title: r.continue ? _t("plan.context_taken_from_the_previous_clip") + (isFree() ? _t("plan.and_sound") : "") + ")" : _t("plan.hidden_lead_in_generated_then_removed"),
                }));
                if (!r.continue) tl.append(h("div", { class: "seam cut", style: `left:${x(r.visible) - 1}px`, title: _t("plan.cut") }, h("span", {}, "✂")));
            }
        });
        if (songDur !== null) tl.append(h("div", { class: "songend", style: `left:${songDur * pps}px` }, h("span", {}, _t("plan.end_of_the_song"))));
        const wrap = h("div", { class: "tl-wrap" }, tl);
        box.append(wrap);
        box.append(h("div", { class: "tl-legend" },
            h("span", {}, h("i", { style: "background:#3a6ea5" }), _t("plan.one_color_per_scene")),
            h("span", {}, h("i", { class: "", style: `background:repeating-linear-gradient(90deg,${H3Theme.c("rgba(255,255,255,.35)")} 0 2px,transparent 2px 5px)` }), _t("plan.context_taken_over_continuation")),
            h("span", {}, h("i", { style: "background:repeating-linear-gradient(135deg,rgba(240,180,76,.7) 0 3px,transparent 3px 7px)" }), _t("plan.hidden_lead_in_new_scene")),
            h("span", {}, "✂ " + _t("plan.cut"))));
        const selBlock = tl.querySelector(".block.sel");
        if (selBlock) {
            const l = selBlock.offsetLeft;
            if (l < wrap.scrollLeft || l > wrap.scrollLeft + wrap.clientWidth - 60) wrap.scrollLeft = Math.max(0, l - 40);
        }
    }

    // ---------------------------------------------------------------- side panel
    function field(label, input) { return [h("label", {}, label), input]; }
    function numOrUndef(v) { return v === "" ? undefined : Number(v); }
    function setKey(obj, key, value) { if (value === undefined || value === "" || Number.isNaN(value)) delete obj[key]; else obj[key] = value; }

    // the right column: what the clip can use (references, subjects, sentences) and the checks
    function renderPalette() {
        const side = $("side");
        side.innerHTML = "";
        if (curClip()) H3Sections.palette(side, sectionsCtx());
        side.append(h("section", { class: "box sx-pal" }, h("h2", {}, _t("plan.plan_checks")), h("ul", { class: "vlist", id: "vlist" })));
        renderValidation();
    }
    function sectionsCtx() {
        const c = curClip();
        return {
            plan: S.plan, clip: c, index: S.sel + 1, free: isFree(), prevClip: S.sel > 0 ? clips()[S.sel - 1] : null,
            changed, toast, lastLanguage: () => lastLanguage(c), speakerNumber,
            media: (window.H3Editor && window.H3Editor.media) || null,
            messages: S.messages.filter((m) => m.clip === S.sel + 1),
        };
    }
    function speakerNumber(speaker) {
        const speakers = [];
        for (const cl of clips()) for (const x of cl.dialogue || []) if (x.speaker && !speakers.includes(x.speaker)) speakers.push(x.speaker);
        return Math.max(1, speakers.indexOf(speaker) + 1);
    }
    // "⚙ Réglages du plan": what used to fill the left column (project fields, references, conversions)
    function openSettings() {
        if (S.settingsBox && S.settingsBox.isConnected) return;
        const body = h("div", { class: "plan-settings" });
        const overlay = h("div", { class: "tk-modal", style: "z-index:65", onclick: (e) => { if (e.target === overlay) close(); } },
            h("div", { class: "tk-box tk-form wide" },
                h("div", { class: "tk-box-head" }, h("b", {}, _t("plan.plan_settings")), h("span", { style: "flex:1" }), h("button", { onclick: () => close() }, _t("plan.close"))), body));
        const close = () => { overlay.remove(); S.settingsBox = null; };
        document.body.append(overlay);
        S.settingsBox = body;
        renderSettings(body);
    }
    function renderSettings(side) {
        side.innerHTML = "";
        const p = S.plan;
        const free = isFree();
        const ctxValues = free ? H3.avContextValues() : [5, 22, 39, 56, 73, 90];
        const ctx = p.context_frames ?? 39;
        if (!ctxValues.includes(ctx)) ctxValues.push(ctx);

        const proj = h("section", { class: "box" }, h("h2", {}, _t("plan.project")),
            h("div", { class: "grid2" },
                field(_t("plan.project_name"), h("input", { value: p.project ?? "", oninput: (e) => { p.project = e.target.value; changed(false); } })),
                field(_t("plan.mode"), h("select", { onchange: (e) => switchMode(e.target.value) },
                    h("option", { value: "free", selected: free }, _t("plan.free_generated_sound")),
                    h("option", { value: "music_video", selected: !free }, _t("plan.music_video")))),
                field(_t("plan.context"), h("select", { onchange: (e) => { p.context_frames = +e.target.value; changed(true); } },
                    ctxValues.map((v) => h("option", { value: v, selected: v === ctx }, `${v} images (${sec(v, 3)})${v === 39 ? _t("plan.recommended") : ""}`)))),
                field(_t("plan.crossfade_at_seams"), h("input", { type: "number", min: 0, max: ctx, value: p.crossfade_frames ?? 0, title: _t("plan.0_hard_cuts"),
                    onchange: (e) => { p.crossfade_frames = Math.max(0, Math.round(+e.target.value || 0)); changed(true); } })),
                free ? field(_t("plan.sound_release"), h("input", { type: "number", min: 0, max: 64, value: p.audio_feather_ticks ?? 8, title: _t("plan.steps_of_25_ms_8_0"),
                    onchange: (e) => { setKey(p, "audio_feather_ticks", numOrUndef(e.target.value)); changed(true); } })) : null,
                field(_t("plan.base_seed"), h("input", { type: "number", min: 0, placeholder: "auto", value: p.seed ?? "",
                    onchange: (e) => { setKey(p, "seed", numOrUndef(e.target.value)); changed(true); } })),
                window.H3Studio ? null : field(_t("plan.reference_size"), h("select", { onchange: (e) => { setKey(p, "ref_image_size", e.target.value === "match" ? undefined : e.target.value); changed(true); } },
                    h("option", { value: "match", selected: p.ref_image_size !== "max" }, _t("plan.match_default")),
                    h("option", { value: "max", selected: p.ref_image_size === "max" }, "max"))),
                free ? null : field(_t("plan.song"), h("input", { value: p.song?.file ?? "", placeholder: _t("plan.file_for_the_record"),
                    oninput: (e) => { p.song = p.song || {}; setKey(p.song, "file", e.target.value); changed(false); } })),
                free ? null : field(_t("plan.song_length_s"), h("input", { type: "number", step: "0.01", min: 0, value: p.song?.duration_seconds ?? "",
                    onchange: (e) => { p.song = p.song || {}; setKey(p.song, "duration_seconds", numOrUndef(e.target.value)); changed(true); } })),
            ),
            h("div", { style: "margin-top:8px" }, h("label", {}, _t("plan.notes")),
                h("textarea", { style: "font-family:inherit;min-height:40px", value: p.notes ?? "",
                    oninput: (e) => { setKey(p, "notes", e.target.value); changed(false); } })));
        if (clips().some(legacyNumbering)) {
            proj.append(h("div", { class: "hint", style: "margin-top:6px" }, _t("plan.some_prompts_use_the_old_picture"),
                h("button", { class: "small", onclick: convertAllLegacy }, _t("plan.convert_all_to"))));
        }
        if (p.width != null || p.height != null) {
            proj.append(h("div", { class: "hint", style: "margin-top:6px" }, _t("plan.fallback_size_in_the_plan", { width: p.width, height: p.height }),
                h("button", { class: "small", onclick: () => { delete p.width; delete p.height; changed(true); } }, _t("plan.remove_it_size_chosen_in_the"))));
        }
        side.append(proj);

        const refs = h("section", { class: "box" }, h("h2", {}, _t("plan.references")),
            h("div", { class: "hint", style: "margin-bottom:8px" }, free
                ? _t("plan.one_name_per_character_or_place")
                : _t("plan.one_name_per_picture_in_the")),
            h("div", { id: "refRows" }),
            h("button", { onclick: addRef }, _t("plan.reference")));
        side.append(refs);
        renderRefRows();
    }

    function renderRefRows() {
        const box = $("refRows");
        if (!box) return;
        box.innerHTML = "";
        for (const [name, desc] of Object.entries(S.plan.refs)) {
            box.append(h("div", { class: "refrow" },
                h("input", { class: "rname", value: name, title: _t("plan.name_letters_digits_and"), onchange: (e) => renameRef(name, e.target.value.trim(), e.target) }),
                h("button", { class: "small danger", title: _t("plan.delete"), onclick: () => deleteRef(name) }, "✕"),
                h("textarea", { style: "grid-column:1/3", placeholder: _t("plan.what_the_user_must_provide_picture"), value: desc ?? "",
                    oninput: (e) => { S.plan.refs[name] = e.target.value; changed(false); } }),
                h("div", { class: "kinds", "data-ref": name })));
        }
        renderRefKinds();
    }
    function renderRefKinds() {
        for (const node of document.querySelectorAll(".kinds[data-ref]")) {
            const name = node.dataset.ref;
            const used = clips().filter((c) => (c.refs || []).includes(name)).length;
            const kinds = H3.referenceKinds(S.plan, name);
            node.innerHTML = "";
            node.append(used ? _t("plan.used_by_clip_s_to_provide", { used }) : _t("plan.used_by_no_clip"),
                used ? h("b", {}, kinds.length ? kinds.map((k) => _t("check." + k)).join(" + ") : _t("plan.nothing_not_cited_in_the_prompts")) : "");
        }
    }
    function addRef() {
        let k = 1, name;
        do { name = `ref_${k++}`; } while (name in S.plan.refs);
        S.plan.refs[name] = "";
        changed(true);
        const inputs = document.querySelectorAll("#refRows input.rname");
        inputs[inputs.length - 1]?.select();
    }
    function renameRef(oldName, newName, input) {
        if (newName === oldName) return;
        if (!H3.NAME_RE.test(newName)) { alert(_t("plan.invalid_name_letters_digits_and_only")); input.value = oldName; return; }
        if (newName in S.plan.refs) { alert(_t("plan.the_name_already_exists", { newName })); input.value = oldName; return; }
        const entries = Object.entries(S.plan.refs).map(([k, v]) => [k === oldName ? newName : k, v]);
        S.plan.refs = Object.fromEntries(entries);
        H3.renameRef(S.plan, oldName, newName);
        changed(true);
        toast(_t("plan.renamed_to_everywhere_references_prompts_lines", { oldName, newName }));
    }
    async function deleteRef(name) {
        const used = clips().filter((c) => (c.refs || []).includes(name)).length;
        if (used && !await H3Dialog.confirm(_t("plan.is_used_by_clip_s_remove", { name, used }))) return;
        delete S.plan.refs[name];
        for (const c of clips()) if (Array.isArray(c.refs)) c.refs = c.refs.filter((r) => r !== name);
        changed(true);
    }
    async function switchMode(mode) {
        const p = S.plan;
        p.mode = mode;
        if (mode === "free") {
            if (p.song && Object.keys(p.song).length && await H3Dialog.confirm(_t("plan.free_mode_has_no_song_remove"))) delete p.song;
            if (!H3.isAvBoundary(p.context_frames ?? 39)) p.context_frames = 39;
            for (const c of clips()) if (!Array.isArray(c.dialogue)) c.dialogue = [];
        } else {
            delete p.audio_feather_ticks;
            if (!p.song) p.song = { file: "", duration_seconds: 60 };
        }
        changed(true);
    }

    function renderValidation() {
        const list = $("vlist");
        if (!list) return;
        list.innerHTML = "";
        if (!S.messages.length) { list.append(h("li", { class: "", style: "border-color:var(--ok)" }, _t("plan.no_problem"))); return; }
        for (const m of S.messages) {
            list.append(h("li", { class: m.level, onclick: () => { if (m.clip) select(m.clip - 1); } },
                h("span", { class: "where" }, m.clip ? `clip ${m.clip}` : "plan"), m.text));
        }
    }

    // ---------------------------------------------------------------- clip list
    function renderList() {
        const list = $("list");
        const scroll = list.scrollTop;
        list.innerHTML = "";
        list.append(h("div", { class: "listbar" },
            h("span", { class: "tk-split" },
                h("button", { onclick: () => addClip(S.sel + 1), title: _t("plan.new_clip_after_the_selected_clip") }, "+ clip"),
                h("button", { class: "tk-split-arrow", title: _t("plan.other_ways_to_add_a_clip"), onclick: (e) => { e.stopPropagation(); addMenu(e.currentTarget); } }, "▾")),
            h("button", { onclick: duplicateClip, title: _t("plan.duplicate_the_selected_clip") }, _t("plan.duplicate")),
            h("button", { onclick: () => moveClip(-1), disabled: S.sel === 0, title: _t("plan.move_up") }, "↑"),
            h("button", { onclick: () => moveClip(1), disabled: S.sel >= clips().length - 1, title: _t("plan.move_down") }, "↓"),
            h("button", { class: "danger", onclick: deleteClip, disabled: clips().length < 2, title: _t("plan.delete_the_selected_clip") }, "✕")));
        const rows = H3.framesLegal(S.plan) ? H3.timeline(S.plan) : null;
        clips().forEach((c, i) => {
            const st = clipStatus(i + 1);
            const r = rows ? rows[i] : null;
            list.append(h("div", { class: `clipitem${i === S.sel ? " sel" : ""}`, onclick: () => select(i) },
                h("span", { class: "num" }, i + 1),
                h("span", { class: "nm", title: c.name }, (c.continue ? "↪ " : i ? "✂ " : "") + (c.name || "")),
                h("span", { class: `dot ${st.e ? "e" : st.w ? "w" : ""}` }),
                h("span", { class: "meta" }, r ? `${sec(r.visible, 1)} → ${sec(r.end, 1)} · ${_t("plan.n_fr", { n: c.frames })}` : _t("plan.n_frames", { n: c.frames }))));
        });
        list.scrollTop = scroll;
    }
    function select(i) {
        if (i === S.sel) return;
        stopSong();
        H3Sections.closeAc();
        if (S.snapTimer) pushHistory();
        S.sel = i;
        renderList();
        renderTimeline();
        renderPalette();
        renderEditor();
    }
    function addClip(at, empty = false) {
        const prev = empty ? null : clips()[at - 1];
        clips().splice(at, 0, newClip(at + 1, S.plan, prev));
        S.sel = at;
        changed(true);
    }
    function addMenu(anchor) {
        document.querySelector(".plan-addmenu")?.remove();
        const r = anchor.getBoundingClientRect();
        const menu = h("div", { class: "plan-addmenu", style: `left:${r.left}px;top:${r.bottom + 2}px` },
            h("button", { onclick: () => { menu.remove(); addClip(S.sel + 1); } }, _t("plan.take_over_the_selected_clip")),
            h("button", { onclick: () => { menu.remove(); addClip(S.sel + 1, true); } }, _t("plan.empty_clip_new_scene")));
        document.body.append(menu);
        setTimeout(() => document.addEventListener("click", () => menu.remove(), { once: true }));
    }
    function duplicateClip() {
        const copy = JSON.parse(JSON.stringify(curClip()));
        const names = new Set(clips().map((c) => c.name));
        let k = 2, name;
        do { name = `${copy.name}_${k++}`; } while (names.has(name));
        copy.name = name;
        delete copy.seed;
        clips().splice(S.sel + 1, 0, copy);
        S.sel++;
        changed(true);
    }
    function moveClip(d) {
        const j = S.sel + d;
        if (j < 0 || j >= clips().length) return;
        const list = clips();
        [list[S.sel], list[j]] = [list[j], list[S.sel]];
        S.sel = j;
        changed(true);
    }
    async function deleteClip() {
        if (clips().length < 2) return;
        if (!await H3Dialog.confirm(_t("plan.delete_clip", { v0: S.sel + 1, name: curClip().name }))) return;
        clips().splice(S.sel, 1);
        S.sel = Math.min(S.sel, clips().length - 1);
        changed(true);
    }

    // ---------------------------------------------------------------- clip editor
    function framesOptions(current, index) {
        const ctx = H3.contextOf(S.plan);
        const out = [];
        const values = [];
        for (let f = 56; f <= 413; f += 17) if (f > ctx) values.push(f);
        if (!values.includes(current)) values.push(current);
        values.sort((a, b) => a - b);
        for (const f of values) {
            const legal = H3.isRun(f) && f > ctx;
            const added = index > 1 ? f - ctx : f;
            let label = legal ? _t("plan.frames_option", { f, length: sec(f), added: sec(added, 2) }) : _t("plan.not_allowed", { f });
            if (legal && f > H3.SOFT_MAX_FRAMES) label += _t("plan.slow");
            out.push(h("option", { value: f, selected: f === current }, label));
        }
        return out;
    }

    function renderEditor() {
        const ed = $("editor");
        ed.innerHTML = "";
        const c = curClip();
        if (!c) { ed.append(h("div", { class: "empty" }, _t("plan.no_clip"))); return; }
        const n = S.sel + 1;
        const free = isFree();

        ed.append(h("div", { class: "ed-head" },
            h("span", { class: "t" }, _t("plan.clip", { n })),
            h("span", { class: "hint" }, c.continue ? _t("plan.continues_the_shot_of_the_previous") : n === 1 ? _t("plan.first_clip") : _t("plan.new_scene_cut"))));

        ed.append(h("div", { class: "fields" },
            h("div", {}, h("label", {}, _t("plan.name")), h("input", { value: c.name ?? "", oninput: (e) => { c.name = e.target.value; changed(false); } })),
            h("div", {}, h("label", {}, _t("plan.raw_length_frames")), h("select", { onchange: (e) => { c.frames = +e.target.value; changed(true); } }, framesOptions(c.frames, n))),
            h("div", {}, h("label", {}, _t("plan.link")), h("label", { class: "toggle", style: "color:var(--text)" },
                h("input", { type: "checkbox", checked: !!c.continue, disabled: n === 1 && !c.continue, onchange: (e) => toggleContinue(c, e.target.checked) }),
                _t("plan.continues_the_previous_clip"))),
            h("div", {}, h("label", {}, _t("plan.seed_empty_auto")), h("input", { type: "number", min: 0, value: c.seed ?? "", placeholder: "auto",
                onchange: (e) => { setKey(c, "seed", numOrUndef(e.target.value)); changed(true); } }))));
        ed.append(h("div", { class: "timing", id: "timing" }));
        ed.append(h("div", { class: "msgs", id: "clipMsgs" }));

        if (!free) ed.append(songCard(c));
        else ed.append(renderDialogue(c));

        // prompt
        ed.append(renderPrompt(c, n));

        const notes = h("details", { class: "card plan-notes" }, h("summary", {}, _t("plan.clip_notes")),
            h("textarea", { style: "font-family:inherit;min-height:34px;margin-top:6px", value: c.notes ?? "", oninput: (e) => { setKey(c, "notes", e.target.value); changed(false); } }));
        if (c.notes) notes.open = true;
        ed.append(notes);

        renderTiming();
        renderClipMessages();
        renderRate();
        renderPreview();
        autosizeAll();
    }

    // ---------------------------------------------------------------- the passage of the song a clip covers
    const song = { audio: null, url: null, from: 0, to: 0, kind: null, raf: 0 };
    function songUrl() {
        const media = window.H3Editor && window.H3Editor.media;
        return (media && media.song()) || S.localSong || null;
    }
    function stopSong() {
        if (song.audio) song.audio.pause();
        cancelAnimationFrame(song.raf);
        song.kind = null;
        drawSong();
    }
    function playSong(kind, from, to) {
        const url = songUrl();
        if (!url) return;
        if (song.kind === kind) { stopSong(); return; }
        if (!song.audio || song.url !== url) {
            if (song.audio) song.audio.pause();
            song.audio = new Audio(url);
            song.url = url;
        }
        const a = song.audio;
        song.kind = kind; song.from = from; song.to = to;
        const start = () => {
            a.currentTime = from;
            a.play().catch((e) => { toast(_t("plan.cannot_play", { message: e.message })); song.kind = null; drawSong(); });
            const tick = () => {
                if (song.kind !== kind) return;
                if (a.currentTime >= song.to || a.ended) { stopSong(); return; }
                drawSong();
                song.raf = requestAnimationFrame(tick);
            };
            song.raf = requestAnimationFrame(tick);
        };
        if (a.readyState >= 1) start(); else a.addEventListener("loadedmetadata", start, { once: true });
        drawSong();
    }
    function drawSong() {
        const box = $("songCard");
        if (!box) return;
        const head = box.querySelector(".song-head");
        const playing = song.kind && song.audio && !song.audio.paused;
        for (const b of box.querySelectorAll("[data-kind]")) {
            const on = song.kind === b.dataset.kind;
            b.classList.toggle("on", !!on);
            b.textContent = on ? _t("plan.stop") : b.dataset.label;
        }
        if (head) {
            head.style.display = playing ? "" : "none";
            const span = +box.dataset.end - +box.dataset.raw;
            if (playing && span > 0) head.style.left = `${Math.max(0, Math.min(100, 100 * (song.audio.currentTime - +box.dataset.raw) / span))}%`;
        }
        const clock = box.querySelector(".song-clock");
        if (clock) clock.textContent = playing ? secv(song.audio.currentTime, 2) : "";
    }
    function songCard(c) {
        const card = h("div", { class: "card", id: "songCard" });
        card.append(h("h2", {}, h("span", { class: "grow" }, _t("plan.passage_of_the_song"))));
        const lyrics = h("textarea", { style: "font-family:inherit;min-height:38px", placeholder: _t("plan.lyrics_heard_in_this_clip"), value: c.lyrics ?? "",
            oninput: (e) => { setKey(c, "lyrics", e.target.value); changed(false); } });
        if (!H3.framesLegal(S.plan)) {
            card.append(h("div", { class: "hint" }, _t("plan.passage_unavailable_while_a_clip_length")), h("label", {}, _t("plan.clip_lyrics")), lyrics);
            return card;
        }
        const r = H3.timeline(S.plan)[S.sel];
        const raw = r.raw_start / FPS, vis = r.visible / FPS, end = r.end / FPS;
        const total = (S.plan.song && S.plan.song.duration_seconds) || Math.max(end, 1);
        card.dataset.raw = raw; card.dataset.end = end;
        const url = songUrl();
        const pct = (x) => `${Math.max(0, Math.min(100, x * 100)).toFixed(2)}%`;
        const btn = (kind, label, from) => h("button", { class: "small", "data-kind": kind, "data-label": label, disabled: !url || null, onclick: () => playSong(kind, from, end) }, label);
        card.append(h("div", { class: "song-bar-row" },
            btn("all", _t("plan.whole_passage"), raw),
            S.sel > 0 ? btn("new", _t("plan.new_part"), vis) : null,
            h("span", { class: "song-range" }, S.sel > 0 ? _t("plan.new_part_from", { v0: secv(raw, 2), v1: secv(end, 2), v2: secv(vis, 2) }) : `0,00 s → ${secv(end, 2)}`),
            h("span", { class: "grow" }),
            h("span", { class: "song-clock" })));
        card.append(h("div", { class: "song-all", title: _t("plan.the_whole_song_the_clip_s") },
            h("div", { style: `left:${pct(raw / total)};width:${pct((end - raw) / total)}` })));
        const span = end - raw;
        card.append(h("div", { class: "song-clip" },
            S.sel > 0 ? h("div", { class: "song-ctx", style: `width:${pct((vis - raw) / span)}`, title: _t("plan.overlap_context_taken_over_or_lead") }, h("span", {}, r.continue ? _t("plan.context") : _t("plan.lead_in"))) : null,
            h("div", { class: "song-new", style: `left:${pct(S.sel > 0 ? (vis - raw) / span : 0)}` }, h("span", {}, _t("plan.new_part_2"))),
            h("div", { class: "song-head", style: "display:none" })));
        if (!url) {
            const media = window.H3Editor && window.H3Editor.media;
            card.append(h("div", { class: "hint" }, media ? _t("plan.no_song_in_branch_takes_branch", { v0: media.label() }) : _t("plan.choose_the_song_file_to_listen"),
                media ? null : h("button", { class: "small", onclick: () => {
                    const input = h("input", { type: "file", accept: "audio/*" });
                    input.onchange = () => { const f = input.files[0]; if (f) { S.localSong = URL.createObjectURL(f); renderEditor(); } };
                    input.click();
                } }, _t("plan.choose"))));
        }
        card.append(h("label", {}, _t("plan.clip_lyrics_for_the_record_and")), lyrics);
        requestAnimationFrame(drawSong);
        return card;
    }

    function toggleContinue(c, value) {
        c.continue = value;
        const parts = H3.parseSections(c.prompt);
        if (parts) {     // the opening sentence of [Shot 1] follows the new link
            const det = H3Sections.parseDetailed(parts[3]);
            if (H3Sections.customOpening(det)) toast(_t("plan.shot_1_starts_with_an_opening"));
            else {
                parts[3] = H3Sections.composeDetailed(det.style, det.shots, H3Sections.expectedSentence(c, S.sel + 1, isFree()));
                c.prompt = H3.composeSections(parts);
            }
        }
        changed(true);
    }

    function renderTiming() {
        const box = $("timing");
        if (!box) return;
        box.innerHTML = "";
        if (!H3.framesLegal(S.plan)) { box.append(_t("plan.timing_unavailable_while_a_length_is")); return; }
        const r = H3.timeline(S.plan)[S.sel];
        const added = r.end - r.visible;
        box.append(_t("plan.generated_from"), h("b", {}, sec(r.raw_start)), _t("plan.to"), h("b", {}, sec(r.end)),
            _t("plan.visible_from"), h("b", {}, sec(r.visible)),
            _t("plan.adds"), h("b", {}, sec(added, 2)), _t("plan.to_the_video"),
            r.context ? (r.continue ? _t("plan.the_first_take_over_the_end", { v0: sec(r.context), v1: r.index - 1 }) : _t("plan.the_first_are_a_hidden_lead", { v0: sec(r.context) })) : "");
    }
    function renderClipMessages() {
        const box = $("clipMsgs");
        if (!box) return;
        box.innerHTML = "";
        for (const m of S.messages.filter((m) => m.clip === S.sel + 1)) box.append(h("div", { class: m.level }, m.text));
    }

    function renderDialogue(c) {
        if (!Array.isArray(c.dialogue)) c.dialogue = [];
        const card = h("div", { class: "card" }, h("h2", {}, h("span", { class: "grow" }, _t("plan.lines")),
            h("button", { class: "small", onclick: () => { c.dialogue.push({ speaker: (c.refs || [])[0] || "", text: "", language: lastLanguage(c) }); changed(true); } }, _t("plan.line"))));
        c.dialogue.forEach((d, k) => {
            const speakers = [...new Set([...(c.refs || []), d.speaker].filter(Boolean))];
            card.append(h("div", { class: "dlg" },
                h("select", { onchange: (e) => { d.speaker = e.target.value; changed(true); } },
                    speakers.length ? null : h("option", { value: "" }, _t("plan.no_ref")),
                    speakers.map((s) => h("option", { value: s, selected: s === d.speaker }, s))),
                h("input", { value: d.text ?? "", placeholder: _t("plan.text_of_the_line"), oninput: (e) => { d.text = e.target.value; changed(false); } }),
                h("input", { value: d.language ?? "", placeholder: "French", oninput: (e) => { setKey(d, "language", e.target.value); changed(false); } }),
                h("span", {},
                    h("button", { class: "small", title: _t("plan.insert_into_the_prompt_at_the"), onclick: () => insertDialogue(c, d) }, _t("plan.to_prompt")), " ",
                    h("button", { class: "small", title: _t("plan.move_up"), disabled: k === 0, onclick: () => { [c.dialogue[k - 1], c.dialogue[k]] = [c.dialogue[k], c.dialogue[k - 1]]; changed(true); } }, "↑"), " ",
                    h("button", { class: "small danger", title: _t("plan.delete"), onclick: () => { c.dialogue.splice(k, 1); changed(true); } }, "✕"))));
        });
        if (!c.dialogue.length) card.append(h("div", { class: "hint" }, _t("plan.no_lines_they_are_used_for")));
        card.append(h("div", { class: "rate", id: "rate" }));
        return card;
    }
    function lastLanguage(c) {
        for (const cl of [c, ...clips()]) for (const d of cl.dialogue || []) if (d.language) return d.language;
        return "French";
    }
    function renderRate() {
        const box = $("rate");
        if (!box) return;
        const c = curClip();
        const words = (c.dialogue || []).reduce((a, d) => a + (String(d.text || "").trim() ? String(d.text).trim().split(/\s+/).length : 0), 0);
        if (!words || !H3.isRun(c.frames)) { box.textContent = ""; return; }
        const ctx = H3.contextOf(S.plan);
        const speaking = (c.frames - (S.sel > 0 ? ctx : 0)) / FPS;
        const rate = words / speaking;
        box.className = "rate" + (rate > 3 ? " bad" : "");
        box.textContent = _t("plan.words_for_of_new_picture_words", { words, v1: secv(speaking), v2: rate.toFixed(1).replace(".", H3I18n.decimal()), v3: rate > 3 ? _t("plan.too_fast_max_3") : rate > 2.5 ? _t("plan.brisk") : _t("plan.comfortable") });
    }

    // ---------------------------------------------------------------- prompt editor
    function renderPrompt(c, n) {
        const parts = H3.parseSections(c.prompt);
        const tab = parts ? S.tab : "raw";
        const card = h("div", { class: "card" }, h("h2", {}, h("span", { class: "grow" }, _t("plan.prompt")),
            h("span", { class: "tabs" },
                h("button", { class: tab === "sections" ? "on" : "", disabled: !parts, onclick: () => { S.tab = "sections"; renderEditor(); } }, _t("plan.sections")),
                h("button", { class: tab === "raw" ? "on" : "", onclick: () => { S.tab = "raw"; renderEditor(); } }, _t("plan.raw_text")),
                h("button", { class: tab === "preview" ? "on" : "", onclick: () => { S.tab = "preview"; renderEditor(); } }, _t("plan.preview_sent_to_h3")))));
        if (!parts && S.tab !== "raw" && S.tab !== "preview") {
            card.append(h("div", { class: "msgs" }, h("div", { class: "warning" },
                _t("plan.this_prompt_does_not_have_the"),
                h("button", { class: "small", onclick: () => { c.prompt = restructure(c.prompt); S.tab = "sections"; changed(true); } }, _t("plan.create_the_missing_sections")))));
        }
        if (legacyNumbering(c)) {
            card.append(h("div", { class: "msgs" }, h("div", { class: "warning" },
                _t("plan.this_prompt_numbers_the_pictures_itself"),
                h("button", { class: "small", onclick: () => { convertLegacy(c); } }, _t("plan.convert_to")),
                _t("plan.the_insert_buttons_write_picture_n"))));
        }
        if (tab === "raw") card.append(insertBar(c, n, tab));
        if (tab === "sections") {
            H3Sections.render(card, sectionsCtx());
        } else if (tab === "raw") {
            const ta = h("textarea", { id: "rawPrompt", value: c.prompt ?? "", spellcheck: "false", style: "min-height:320px",
                oninput: (e) => { c.prompt = e.target.value; changed(false); autosize(e.target); } });
            card.append(ta);
        } else {
            card.append(h("div", { class: "hint", style: "margin-bottom:6px" }, previewHint()), h("div", { class: "preview", id: "preview" }));
        }
        return card;
    }
    function legacyNumbering(c) {
        const p = String(c.prompt || "");
        return /<Picture \d+>/.test(p) && !H3.placeholders(p).some((x) => x.kind === "picture");
    }
    function convertLegacy(c) {
        const refs = c.refs || [];
        let missing = 0;
        c.prompt = String(c.prompt).replace(/<Picture (\d+)>/g, (m, k) => {
            const name = refs[+k - 1];
            if (!name) { missing++; return m; }
            return `{picture:${name}}`;
        });
        changed(true);
        toast(missing ? _t("plan.picture_n_without_a_matching_reference", { missing }) : _t("plan.prompt_converted_to_placeholders"));
    }
    function convertAllLegacy() {
        let count = 0;
        for (const c of clips()) if (legacyNumbering(c)) {
            const refs = c.refs || [];
            c.prompt = String(c.prompt).replace(/<Picture (\d+)>/g, (m, k) => (refs[+k - 1] ? `{picture:${refs[+k - 1]}}` : m));
            count++;
        }
        if (count) { changed(true); toast(_t("plan.prompt_s_converted_to_placeholders", { count })); }
    }
    function previewHint() {
        return isFree()
            ? _t("plan.simulated_with_one_picture_for_each")
            : _t("plan.music_video_mode_the_lines_are");
    }
    function restructure(prompt) {
        const text = String(prompt || "");
        const parts = H3.SECTIONS.map(() => "");
        let rest = text;
        const found = H3.SECTIONS.map((s) => text.indexOf(s));
        if (found.every((v) => v < 0)) { parts[3] = text.trim(); return H3.composeSections(parts); }
        // keep what can be found, in order; text before the first header goes to detailed_description
        const order = H3.SECTIONS.map((s, k) => ({ s, k, at: found[k] })).filter((o) => o.at >= 0).sort((a, b) => a.at - b.at);
        const head = text.slice(0, order[0].at).trim();
        order.forEach((o, i) => {
            const end = i + 1 < order.length ? order[i + 1].at : text.length;
            parts[o.k] = text.slice(o.at + o.s.length, end).trim();
        });
        if (head) parts[3] = (head + "\n" + parts[3]).trim();
        rest = H3.composeSections(parts);
        return rest;
    }
    function targetArea() {
        if (S.tab === "raw" || !H3.parseSections(curClip().prompt)) return $("rawPrompt");
        return document.querySelector(`textarea[data-sec="${S.focusSection}"]`) || document.querySelector('textarea[data-sec="3"]');
    }
    function insertText(area, text, { ownLine = false } = {}) {
        if (!area) return;
        const v = area.value;
        let start = area.selectionStart ?? v.length, end = area.selectionEnd ?? v.length;
        if (document.activeElement !== area && area.dataset.lastPos) start = end = +area.dataset.lastPos;
        let insert = text;
        if (ownLine) {
            const before = v.slice(0, start), after = v.slice(end);
            if (before && !before.endsWith("\n")) insert = "\n" + insert;
            if (after && !after.startsWith("\n")) insert = insert + "\n";
        } else {
            const before = v.slice(0, start);
            if (before && !/\s$/.test(before)) insert = " " + insert;
        }
        area.value = v.slice(0, start) + insert + v.slice(end);
        const pos = start + insert.length;
        area.focus();
        area.setSelectionRange(pos, pos);
        area.dispatchEvent(new Event("input"));
    }
    function appendLine(sectionIndex, line) {
        // Used for voice lines: always at the end of subject_definitions, on a line of its own.
        const c = curClip();
        const parts = H3.parseSections(c.prompt);
        if (!parts) { insertText($("rawPrompt"), line, { ownLine: true }); return; }
        parts[sectionIndex] = (parts[sectionIndex] ? parts[sectionIndex] + "\n" : "") + line;
        c.prompt = H3.composeSections(parts);
        S.focusSection = sectionIndex;
        changed(true);
    }
    function subjectNumberFor(c, name) {
        const parts = H3.parseSections(c.prompt);
        const text = parts ? parts[0] : String(c.prompt || "");
        for (const line of text.split("\n")) {
            const m = /^<Subject (\d+)>/.exec(line.trim());
            if (m && line.includes(`{picture:${name}}`)) return +m[1];
        }
        const used = [...text.matchAll(/<Subject (\d+)>/g)].map((m) => +m[1]);
        return used.length ? Math.max(...used) + 1 : 1;
    }
    function insertDialogue(c, d) {
        if (!String(d.text || "").trim()) { toast(_t("plan.the_line_is_empty")); return; }
        const n = subjectNumberFor(c, d.speaker);
        const speakers = [];
        for (const cl of clips()) for (const x of cl.dialogue || []) if (x.speaker && !speakers.includes(x.speaker)) speakers.push(x.speaker);
        const s = Math.max(1, speakers.indexOf(d.speaker) + 1);
        if (S.tab === "sections") S.focusSection = 3;
        const area = targetArea();
        insertText(area, `<Subject ${n}> (S${s}) says: <d>[${d.language || "French"}] ${d.text.trim()}</d>`);
    }
    function insertBar(c, n, tab) {
        const free = isFree();
        const bar = h("div", { class: "insert" }, h("span", { class: "lbl" }, _t("plan.insert")));
        const legacy = legacyNumbering(c);
        (c.refs || []).forEach((r, k) => {
            const tag = legacy ? `<Picture ${k + 1}>` : `{picture:${r}}`;
            bar.append(h("button", { class: "small", title: _t("plan.inserts_at_the_cursor", { tag }), onmousedown: (e) => e.preventDefault(), onclick: () => insertText(targetArea(), tag) }, `🖼 ${r}`));
        });
        if (free) {
            bar.append(h("span", { class: "sep" }));
            for (const r of c.refs || []) {
                bar.append(h("button", { class: "small", title: _t("plan.adds_the_voice_line_of_at", { r }),
                    onmousedown: (e) => e.preventDefault(),
                    onclick: () => {
                        if (H3.placeholders(c.prompt).some((p) => p.kind === "voice" && p.name === r)) { toast(_t("plan.the_voice_of_is_already_cited", { r })); return; }
                        appendLine(0, `<Subject ${subjectNumberFor(c, r)}> speaks with the voice from {voice:${r}}.`);
                    } }, `🎙 ${r}`));
            }
        }
        bar.append(h("span", { class: "sep" }));
        const snip = (label, text, title) => h("button", { class: "small", title, onmousedown: (e) => e.preventDefault(), onclick: () => insertText(targetArea(), text) }, label);
        bar.append(snip("[Shot 1]", "[Shot 1] ", _t("plan.start_of_the_shot")));
        if (n > 1) {
            bar.append(snip(_t("plan.continuation"), H3.CONTINUE_SENTENCE + (free ? H3.FREE_CONTINUE_SUFFIX : ""), _t("plan.opening_sentence_of_a_clip_that")));
            bar.append(snip(_t("plan.hidden_lead_in"), free ? H3.HIDDEN_LEADIN_FREE : H3.HIDDEN_LEADIN_MUSIC, _t("plan.opening_sentence_of_a_new_scene")));
        }
        bar.append(snip("<d>…</d>", `<d>[${lastLanguage(c)}] </d>`, _t("plan.lyrics_tag")));
        if (free) bar.append(snip(_t("plan.silent_ending"), "End with a quiet half second without speech.", _t("plan.end_of_a_clip_without_speech")));
        else bar.append(snip(_t("plan.ending_in_motion"), "End with the motion still in progress, so the next clip continues the same shot.", _t("plan.end_of_a_clip_continued_by")));
        if (tab === "sections") bar.append(h("span", { class: "hint", style: "margin-left:6px" }, _t("plan.in_the_active_section_framed")));
        return bar;
    }

    function renderPreview() {
        const box = $("preview");
        if (!box) return;
        const c = curClip();
        const ph = H3.placeholders(c.prompt);
        const refs = c.refs || [];
        const hasImage = new Set(ph.filter((p) => p.kind === "picture").map((p) => p.name));
        const hasVoice = new Set(ph.filter((p) => p.kind === "voice").map((p) => p.name));
        const images = refs.filter((r) => hasImage.has(r));
        const voices = isFree() ? refs.filter((r) => hasVoice.has(r)) : [];
        const lines = String(c.prompt || "").split("\n").filter((line) => {
            const v = H3.placeholders(line).filter((p) => p.kind === "voice");
            return !v.length || v.every((p) => voices.includes(p.name));
        });
        let html = esc(lines.join("\n"));
        html = html.replace(/\{(picture|voice):([A-Za-z0-9][A-Za-z0-9_-]*)\}/g, (m, kind, name) => {
            if (kind === "picture") { const i = images.indexOf(name); return `<span class="ph-pic">&lt;Picture ${i + 1}&gt;</span>`; }
            const i = voices.indexOf(name);
            return `<span class="ph-voice">&lt;Audio ${i + 1}&gt;</span>`;
        });
        html = html.replace(/&lt;d&gt;([\s\S]*?)&lt;\/d&gt;/g, '<span class="ph-d">&lt;d&gt;$1&lt;/d&gt;</span>');
        const legend = _t("plan.pictures_sent", { v0: images.map((r, i) => `${i + 1}=${r}`).join(", ") || _t("plan.none") }) +
            (isFree() ? _t("plan.voices_sent", { v0: voices.map((r, i) => `${i + 1}=${r}`).join(", ") || _t("plan.none") }) : "");
        box.innerHTML = `<div class="hint" style="margin-bottom:8px">${esc(legend)}</div>` + html;
    }

    function autosize(ta) {
        ta.style.height = "auto";
        ta.style.height = Math.max(ta.scrollHeight + 2, 44) + "px";
    }
    function autosizeAll() { for (const ta of document.querySelectorAll("#editor textarea")) autosize(ta); }

    // ---------------------------------------------------------------- wiring
    function init() {
        const menu = $("newMenu");
        $("btnNew").onclick = (e) => { e.stopPropagation(); menu.classList.toggle("open"); };
        document.addEventListener("click", () => menu.classList.remove("open"));
        for (const b of menu.querySelectorAll(".items button")) {
            b.onclick = async () => {
                menu.classList.remove("open");
                if (S.dirty && !await H3Dialog.confirm(_t("plan.unsaved_changes_will_be_lost_continue"))) return;
                setPlan(newPlan(b.dataset.mode), b.dataset.mode === "free" ? "nouveau_plan_libre.json" : "nouveau_plan_musical.json", null);
                S.dirty = true;
                renderHeader();
            };
        }
        $("btnOpen").onclick = openFile;
        $("btnSave").onclick = () => save(false);
        $("btnSaveAs").onclick = () => save(true);
        $("btnUndo").onclick = undo;
        $("btnPlanSettings").onclick = openSettings;
        $("btnRedo").onclick = redo;
        $("badge").onclick = () => document.getElementById("vlist")?.scrollIntoView({ behavior: "smooth" });
        $("filePicker").onchange = (e) => { const f = e.target.files[0]; if (f) loadFile(f, null); e.target.value = ""; };

        // remember the caret of prompt textareas, so toolbar buttons insert at the right place
        document.addEventListener("selectionchange", () => {
            const a = document.activeElement;
            if (a && a.tagName === "TEXTAREA" && (a.dataset.sec !== undefined || a.id === "rawPrompt")) a.dataset.lastPos = a.selectionStart;
        });
        document.addEventListener("keydown", (e) => {
            const mod = e.ctrlKey || e.metaKey;
            if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(false); return; }
            const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
            if (mod && !typing && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
            if (mod && !typing && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
            if (!typing && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
                e.preventDefault();
                select(Math.max(0, Math.min(clips().length - 1, S.sel + (e.key === "ArrowUp" ? -1 : 1))));
            }
        });
        let depth = 0;
        window.addEventListener("dragenter", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { depth++; $("drop").classList.add("on"); } });
        window.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) $("drop").classList.remove("on"); });
        window.addEventListener("dragover", (e) => e.preventDefault());
        window.addEventListener("drop", async (e) => {
            e.preventDefault();
            depth = 0;
            $("drop").classList.remove("on");
            const item = [...(e.dataTransfer?.items || [])].find((i) => i.kind === "file");
            if (!item) return;
            const plainFile = item.getAsFile();         // read the drop before any await: the data transfer expires
            let handle = null;
            try { handle = item.getAsFileSystemHandle ? await item.getAsFileSystemHandle() : null; } catch (_) { handle = null; }
            const file = handle && handle.kind === "file" ? await handle.getFile() : plainFile;
            if (S.dirty && !await H3Dialog.confirm(_t("plan.unsaved_changes_will_be_lost_continue"))) return;
            if (file) loadFile(file, handle && handle.kind === "file" ? handle : null);
        });
        window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
        window.addEventListener("resize", () => { clearTimeout(init.rt); init.rt = setTimeout(renderTimeline, 150); });

        setPlan(newPlan("free"), "nouveau_plan_libre.json", null);
    }
    window.H3Editor = { state: S, setPlan, render: renderAll, toast };
    // Plan / Prises tabs
    for (const b of document.querySelectorAll("#viewTabs button")) {
        b.onclick = () => {
            const takes = b.dataset.view === "takes";
            for (const x of document.querySelectorAll("#viewTabs button")) x.classList.toggle("on", x === b);
            $("planView").hidden = takes;
            $("planView").style.display = takes ? "none" : "";
            $("timeline").style.display = takes ? "none" : "";
            $("takesView").hidden = !takes;
            if (takes) window.H3Takes?.onShow(); else renderAll();
        };
    }
    init();
})();
