// ---------------------------------------------------------------------------------------------
// H3Sections: the "Sections" editor of a clip prompt (Plan tab).
// The prompt stays the reference (it is what H3 receives and what takes are checked against).
// In the editor, <Subject N> is shown as @name: the names live in clip._subjects (ignored by the
// nodes) and the numbers are recomputed when the prompt is written back.
// ---------------------------------------------------------------------------------------------
const H3Sections = (() => {
    const _t = typeof H3I18n !== "undefined" ? H3I18n.t : (id) => id;
    const NAME_CHARS = "[A-Za-z0-9][A-Za-z0-9_-]*";
    const NAME_OK = new RegExp(`^${NAME_CHARS}$`);
    const PREFIX = "[reference generation]";
    const MODES = ["fully_preserved", "partially_preserved", "attribute_transfer"];
    const RET_RE = new RegExp(`^@(${NAME_CHARS})\\s*(\\([^)]*\\))?\\s*:\\s*(${MODES.join("|")})\\s*(?:-\\s?)?(.*)$`);

    // ------------------------------------------------------------------ pure helpers (tested in node)
    function cleanName(s) {
        const v = String(s || "").replace(/[^A-Za-z0-9_-]/g, "_").replace(/^[_-]+/, "");
        return v || "subject";
    }
    function maxSubject(text) {
        let m = 0;
        for (const x of String(text || "").matchAll(/<Subject (\d+)>/g)) m = Math.max(m, +x[1]);
        return m;
    }
    // names of <Subject 1..N>: clip._subjects first, then a name taken from the subject's line
    function subjectNames(clip, parts) {
        const given = Array.isArray(clip._subjects) ? clip._subjects.map(cleanName) : [];
        const n = Math.max(given.length, maxSubject(clip.prompt));
        const sec0 = parts ? parts[0] : String(clip.prompt || "");
        const names = [];
        for (let k = 1; k <= n; k++) {
            let name = given[k - 1];
            if (!name) {
                const lines = sec0.split("\n").filter((l) => l.trim().startsWith(`<Subject ${k}>`)).join("\n");
                const m = new RegExp(`\\{(?:picture|voice):(${NAME_CHARS})\\}`).exec(lines);
                name = m ? m[1] : `s${k}`;
            }
            let unique = name, j = 2;
            while (names.includes(unique)) unique = `${name}_${j++}`;
            names.push(unique);
        }
        return names;
    }
    const toDisplay = (text, names) => String(text || "").replace(/<Subject (\d+)>/g, (m, k) => (names[k - 1] ? "@" + names[k - 1] : m));
    const toPrompt = (text, names) => String(text || "").replace(new RegExp(`@(${NAME_CHARS})`, "g"), (m, n) => {
        const i = names.indexOf(n);
        return i < 0 ? m : `<Subject ${i + 1}>`;
    });
    const unknownMentions = (display, names) => [...new Set([...String(display || "").matchAll(new RegExp(`@(${NAME_CHARS})`, "g"))]
        .map((m) => m[1]).filter((n) => !names.includes(n)))];

    // subject_definitions (display form): the lines of each subject, and the lines of nobody
    function parseSubjects(display, names) {
        const rows = names.map((name) => ({ name, lines: [] }));
        const extra = [];
        for (const line of String(display || "").split("\n")) {
            const t = line.trim();
            if (!t) continue;
            const m = new RegExp(`^@(${NAME_CHARS})(?:\\s+([\\s\\S]*))?$`).exec(t);
            const i = m ? names.indexOf(m[1]) : -1;
            if (i >= 0) rows[i].lines.push(m[2] || "");
            else extra.push(t);
        }
        return { rows: rows.map((r) => ({ name: r.name, text: r.lines.join("\n") })), extra: extra.join("\n") };
    }
    function composeSubjects(rows, extra) {
        const out = [];
        for (const r of rows) for (const l of String(r.text || "").split("\n").map((s) => s.trim()).filter(Boolean)) out.push(`@${r.name} ${l}`);
        if (String(extra || "").trim()) out.push(String(extra).trim());
        return out.join("\n");
    }
    // retention_analysis (display form): one row per line, or null when a line has another shape
    function parseRetention(display) {
        const rows = [];
        for (const line of String(display || "").split("\n")) {
            const t = line.trim();
            if (!t) continue;
            const m = RET_RE.exec(t);
            if (!m) return null;
            rows.push({ name: m[1], scope: m[2] || "", mode: m[3], why: m[4] || "" });
        }
        return rows;
    }
    const composeRetention = (rows) => rows.map((r) => `@${r.name}${r.scope ? " " + r.scope : ""}: ${r.mode} - ${String(r.why || "").trim()}`.replace(/\s+$/, "")).join("\n");
    const retentionLine = (name) => ({ name, scope: "(appears throughout [Shot 1])", mode: "fully_preserved", why: "" });

    function splitSummary(display) {
        const m = /^\[reference generation\]\s*/.exec(String(display || ""));
        return m ? { had: true, text: display.slice(m[0].length) } : { had: false, text: String(display || "") };
    }
    const composeSummary = (text) => `${PREFIX} ${String(text || "").trim()}`.trim();

    function sentences() {
        return [H3.CONTINUE_SENTENCE + H3.FREE_CONTINUE_SUFFIX, H3.CONTINUE_SENTENCE, H3.HIDDEN_LEADIN_FREE, H3.HIDDEN_LEADIN_MUSIC];
    }
    // the sentence a clip must open with: continuation, hidden lead-in of a new scene, or none (first clip)
    function expectedSentence(clip, index, free) {
        if (clip.continue) return H3.CONTINUE_SENTENCE + (free ? H3.FREE_CONTINUE_SUFFIX : "");
        if (index > 1) return free ? H3.HIDDEN_LEADIN_FREE : H3.HIDDEN_LEADIN_MUSIC;
        return "";
    }
    function parseDetailed(display) {
        const pieces = String(display || "").split(/\[Shot \d+\]/);
        const style = pieces[0].trim();
        const shots = pieces.slice(1).map((s) => s.trim());
        let found = "";
        if (shots.length) {
            for (const s of sentences()) if (shots[0].startsWith(s)) { found = s; shots[0] = shots[0].slice(s.length).trim(); break; }
        }
        return { style, shots, found };
    }
    // an opening sentence written by hand (an LLM plan often words it its own way): kept as it is
    function customOpening(det) {
        if (det.found || !det.shots.length) return false;
        const first = det.shots[0].split(/(?<=[.;])\s/)[0] || "";
        return /continues? uninterrupted|lead-in|already fully established/i.test(first);
    }
    // the sentence written back before [Shot 1] after an ordinary edit: the one already there, as it is. Only the
    // « use the right sentence » button puts the expected one: changing it would change the prompt, so invalidate
    // the takes, on an edit somewhere else in the section.
    const openingFor = (det) => (customOpening(det) ? "" : det.found);
    function composeDetailed(style, shots, auto) {
        const list = shots.length ? shots : auto ? [""] : [];
        let out = String(style || "").trim();
        list.forEach((b, i) => {
            const body = String(b || "").trim();
            const text = i === 0 && auto ? auto + (body ? " " + body : "") : body;
            out += (out ? "\n" : "") + `[Shot ${i + 1}] ` + text;
        });
        return out.replace(/\s+$/, "");
    }
    // <Subject k> → map(k) everywhere (a number, or a string put instead)
    const remapSubjects = (text, map) => String(text || "").replace(/<Subject (\d+)>/g, (m, k) => {
        const r = map(+k);
        return typeof r === "number" ? `<Subject ${r}>` : r == null ? m : r;
    });

    // the prompt of a new clip that follows `prev`: same subjects, retention, style and soundscape
    function inheritedPrompt(prev, clip, index, free) {
        const parts = H3.parseSections(prev.prompt);
        if (!parts) return null;
        const style = parseDetailed(parts[3]).style;
        return H3.composeSections([
            parts[0],
            PREFIX + " ",
            parts[2],
            composeDetailed(style, [""], expectedSentence(clip, index, free)) + " ",
            parts[4],
            free ? parts[5] : "",
        ]);
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
    const PICTURE_RE = new RegExp(`\\{(picture|voice):(${NAME_CHARS})\\}`, "g");

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
        const glue = after && !/^[\s.,;:!?)]/.test(after) ? " " : (after ? "" : " ");
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
            if (!m) { if (ac && ac.ta === ta) closeAc(); return; }
            const q = m[2].toLowerCase();
            const items = getItems().filter((it) => !q || (it.label + " " + (it.hint || "")).toLowerCase().includes(q)).slice(0, 10);
            if (!items.length) { closeAc(); return; }
            const start = pos - m[2].length - 1;
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
        const { ta, start, end } = ac;
        closeAc();
        insertAt(ta, start, end, item.ins);
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
    function speakerSubject(c, names, speaker) {
        const parts = H3.parseSections(c.prompt);
        const text = parts ? parts[0] : String(c.prompt || "");
        for (const line of text.split("\n")) {
            const m = /^<Subject (\d+)>/.exec(line.trim());
            if (m && line.includes(`{picture:${speaker}}`)) return names[+m[1] - 1] ? "@" + names[+m[1] - 1] : `<Subject ${m[1]}>`;
        }
        return names.includes(speaker) ? "@" + speaker : (names[0] ? "@" + names[0] : "<Subject 1>");
    }
    function snippets(ctx, names) {
        const first = names[0] ? "@" + names[0] : "<Subject 1>";
        const lang = ctx.lastLanguage();
        const list = [];
        if (ctx.free) {
            list.push({ label: _t("sections.silent_character"), ins: `${first} never speaks and keeps its mouth closed.` });
            list.push({ label: _t("sections.silent_ending"), ins: "End with a quiet half second without speech." });
        } else {
            list.push({ label: _t("sections.silent_character"), ins: `${first} never sings and keeps its mouth closed.` });
            list.push({ label: _t("sections.off_screen_singer"), ins: "Nobody sings on screen; the song is performed by an off-screen singer." });
            list.push({ label: _t("sections.ending_in_motion"), ins: "End with the motion still in progress, so the next clip continues the same shot." });
            list.push({ label: _t("sections.music_sync"), ins: "The visible performance stays synchronized to it." });
        }
        list.push({ label: "<d>…</d>", ins: `<d>[${lang}] </d>` });
        return list;
    }
    function dialogueItems(ctx, names) {
        const c = ctx.clip, out = [];
        if (ctx.free) {
            for (const d of c.dialogue || []) {
                if (!String(d.text || "").trim()) continue;
                const who = speakerSubject(c, names, d.speaker);
                out.push({ label: _t("sections.line_of", { v0: d.speaker || "?" }), hint: d.text, ins: `${who} (S${ctx.speakerNumber(d.speaker)}) says: <d>[${d.language || ctx.lastLanguage()}] ${String(d.text).trim()}</d>` });
            }
        } else if (String(c.lyrics || "").trim()) {
            const who = names[0] ? "@" + names[0] : "<Subject 1>";
            out.push({ label: _t("sections.clip_lyrics"), hint: c.lyrics, ins: `${who} (S1) sings with clearly readable mouth and jaw articulation: <d>[${ctx.lastLanguage()}] ${String(c.lyrics).trim()}</d>` });
        }
        return out;
    }
    function refItems(ctx) {
        const c = ctx.clip, out = [];
        (c.refs || []).forEach((r, k) => {
            const desc = (ctx.plan.refs || {})[r] || "";
            out.push({ kind: "R", label: `{picture:${r}}`, hint: _t("sections.ref", { v0: k + 1, v1: desc ? " · " + desc : "" }), ins: `{picture:${r}}`, img: ctx.media ? ctx.media.image(r) : null });
            if (ctx.free) out.push({ kind: "R", label: `{voice:${r}}`, hint: _t("sections.voice"), ins: `{voice:${r}}` });
        });
        return out;
    }
    function items(ctx, names) {
        const out = [];
        names.forEach((n, i) => out.push({ kind: "S", label: "@" + n, hint: `Subject ${i + 1}`, ins: "@" + n, img: subjectImage(ctx, n) }));
        out.push(...refItems(ctx));
        dialogueItems(ctx, names).forEach((d) => out.push({ kind: "D", ...d }));
        snippets(ctx, names).forEach((p) => out.push({ kind: "P", label: p.label, hint: p.ins, ins: p.ins }));
        return out;
    }
    function subjectImage(ctx, name) {
        if (!ctx.media) return null;
        const parts = H3.parseSections(ctx.clip.prompt);
        if (!parts) return null;
        const names = subjectNames(ctx.clip, parts);
        const row = parseSubjects(toDisplay(parts[0], names), names).rows.find((r) => r.name === name);
        const m = row && new RegExp(`\\{picture:(${NAME_CHARS})\\}`).exec(row.text);
        return m ? ctx.media.image(m[1]) : null;
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

    // ------------------------------------------------------------------ the editor
    function render(card, ctx) {
        const c = ctx.clip, free = ctx.free;
        const parts = H3.parseSections(c.prompt);
        const names = subjectNames(c, parts);
        const disp = parts.map((p) => toDisplay(p, names));
        const getItems = () => items(ctx, names);
        const prev = ctx.prevClip;
        const prevParts = prev ? H3.parseSections(prev.prompt) : null;
        const prevDisplay = (k) => {
            if (!prevParts) return null;
            const pn = subjectNames(prev, prevParts);
            return toDisplay(prevParts[k], pn);
        };

        // write one section back (display form → prompt form)
        const commit = (k, display, structural = false) => {
            const now = H3.parseSections(c.prompt) || parts;
            now[k] = toPrompt(display, names);
            c.prompt = H3.composeSections(now);
            ctx.changed(structural);
        };
        const setNames = (list) => { c._subjects = list.slice(); };
        const ta = (value, oninput, { one = false, placeholder = "" } = {}) => {
            const t = h("textarea", { class: `sx-ta${one ? " sx-one" : ""}`, spellcheck: "false", placeholder, value });
            t.addEventListener("input", () => { oninput(t.value); autosize(t); });
            attachAc(t, getItems);
            acceptDrops(t);
            requestAnimationFrame(() => autosize(t));
            return t;
        };
        const box = (code, hint, ...tools) => {
            const head = h("div", { class: "sx-head" }, h("span", { class: "sx-code" }, code), h("span", { class: "sx-hint" }, hint), h("span", { class: "grow" }), ...tools);
            const b = h("div", { class: "sx-box" }, head);
            card.append(b);
            return b;
        };
        const fromPrev = (label, get) => prev ? h("button", { class: "small", title: _t("sections.take_the_text_of_clip", { v0: ctx.index - 1 }), onclick: get }, label) : null;

        // ---- subject_definitions
        const subj = parseSubjects(disp[0], names);
        const commitSubjects = (structural) => commit(0, composeSubjects(subj.rows, subj.extra), structural);
        const s0 = box("subject_definitions:", _t("sections.one_subject_per_reused_element_drag"));
        subj.rows.forEach((row, i) => {
            const tokens = [...row.text.matchAll(PICTURE_RE)].map((m) => ({ kind: m[1], name: m[2] }));
            const preview = h("div", { class: "sx-gen" });
            const showGen = () => { preview.textContent = toPrompt(composeSubjects([row], ""), names) || _t("sections.subject_no_definition_yet", { v0: i + 1 }); };
            showGen();
            const refChoices = (c.refs || []).flatMap((r) => [["picture", r], ...(free ? [["voice", r]] : [])]);
            const addRef = h("select", { class: "sx-addref", onchange: (e) => {
                const [kind, r] = e.target.value.split(":");
                if (!r) return;
                if (kind === "voice") row.text = (row.text ? row.text + "\n" : "") + `speaks with the voice from {voice:${r}}.`;
                else if (!row.text.trim()) row.text = `is ... whose appearance comes from {picture:${r}}.`;
                else row.text = row.text.replace(/\s*$/, "") + ` {picture:${r}}`;
                commitSubjects(true);
            } }, h("option", { value: "" }, _t("sections.reference")), refChoices.map(([k, r]) => h("option", { value: `${k}:${r}` }, k === "voice" ? _t("sections.voice_4", { r }) : r)));
            const nameInput = h("input", { class: "sx-name", value: row.name, title: _t("sections.working_name_letters_digits_and"),
                onchange: (e) => {
                    const v = e.target.value.trim();
                    if (v === row.name) return;
                    if (!NAME_OK.test(v)) { alert(_t("sections.invalid_name_letters_digits_and_only")); e.target.value = row.name; return; }
                    if (names.includes(v)) { alert(_t("sections.the_name_is_already_used_in", { v })); e.target.value = row.name; return; }
                    const list = names.slice(); list[i] = v; setNames(list);
                    ctx.changed(true);
                } });
            const textarea = ta(row.text, (v) => { row.text = v; showGen(); commitSubjects(false); }, { one: true, placeholder: "is the … whose face, hair and clothing come from {picture:…}." });
            s0.append(h("div", { class: "sx-subject" },
                h("div", { class: "sx-row" },
                    h("span", { class: "sx-chip sx-chipS", draggable: "true", title: _t("sections.drag_into_a_section"), ondragstart: dragText("@" + row.name) },
                        subjectImage(ctx, row.name) ? h("img", { src: subjectImage(ctx, row.name), alt: "" }) : null, `@${row.name} · S${i + 1}`),
                    h("label", { class: "sx-hint" }, _t("sections.name"), nameInput),
                    tokens.length ? h("span", { class: "sx-hint" }, _t("sections.references")) : null,
                    tokens.map((t) => h("span", { class: "sx-chip sx-chipR", title: t.kind === "voice" ? _t("sections.voice") : "image" },
                        t.kind === "picture" && ctx.media && ctx.media.image(t.name) ? h("img", { src: ctx.media.image(t.name), alt: "" }) : null,
                        t.kind === "voice" ? `🎙 ${t.name}` : t.name)),
                    refChoices.length ? addRef : null,
                    h("span", { class: "grow" }),
                    h("button", { class: "small", title: _t("sections.move_up_renumbers_everywhere"), disabled: i === 0 || null, onclick: () => moveSubject(i, -1) }, "↑"),
                    h("button", { class: "small", title: _t("sections.move_down_renumbers_everywhere"), disabled: i === subj.rows.length - 1 || null, onclick: () => moveSubject(i, 1) }, "↓"),
                    h("button", { class: "small danger", title: _t("sections.delete_this_subject"), onclick: () => deleteSubject(i) }, "✕")),
                textarea, preview));
        });
        if (subj.extra) {
            s0.append(h("div", { class: "sx-hint", style: "margin-top:6px" }, _t("sections.other_lines_no_subject_at_the")),
                ta(subj.extra, (v) => { subj.extra = v; commitSubjects(false); }, { one: true }));
        }
        s0.append(h("button", { class: "small", onclick: addSubject }, "+ subject"));

        function moveSubject(i, d) {
            const j = i + d;
            const list = names.slice();
            [list[i], list[j]] = [list[j], list[i]];
            c.prompt = remapSubjects(c.prompt, (k) => (k === i + 1 ? j + 1 : k === j + 1 ? i + 1 : k));
            setNames(list);
            // regroup the definitions in the new order
            const p2 = H3.parseSections(c.prompt);
            const d0 = toDisplay(p2[0], list);
            const s = parseSubjects(d0, list);
            p2[0] = toPrompt(composeSubjects(s.rows, s.extra), list);
            const rows = parseRetention(toDisplay(p2[2], list));
            if (rows) { rows.sort((a, b) => list.indexOf(a.name) - list.indexOf(b.name)); p2[2] = toPrompt(composeRetention(rows), list); }
            c.prompt = H3.composeSections(p2);
            ctx.changed(true);
        }
        async function deleteSubject(i) {
            const name = names[i];
            const p2 = H3.parseSections(c.prompt);
            const elsewhere = [1, 3, 4, 5].reduce((a, k) => a + [...p2[k].matchAll(new RegExp(`<Subject ${i + 1}>`, "g"))].length, 0);
            const ok = await H3Dialog.confirm(_t("sections.delete_its_definition_and_its_retention", { name })
                + (elsewhere ? _t("sections.it_is_mentioned_times_elsewhere_those", { elsewhere, name }) : ""), { ok: _t("sections.delete"), danger: true });
            if (!ok) return;
            const list = names.filter((_, k) => k !== i);
            const d = p2.map((p) => toDisplay(p, names));
            const s = parseSubjects(d[0], names);
            s.rows.splice(i, 1);
            d[0] = composeSubjects(s.rows, s.extra);
            const rows = parseRetention(d[2]);
            if (rows) d[2] = composeRetention(rows.filter((r) => r.name !== name));
            setNames(list);
            c.prompt = H3.composeSections(d.map((t) => toPrompt(t, list)));
            ctx.changed(true);
        }
        function addSubject() {
            const d = H3.parseSections(c.prompt).map((p) => toDisplay(p, names));
            const s = parseSubjects(d[0], names);
            const used = new Set(s.rows.flatMap((r) => [...r.text.matchAll(PICTURE_RE)].map((m) => m[2])));
            const ref = (c.refs || []).find((r) => !used.has(r));
            let base = ref || "subject", name = base, j = 2;
            while (names.includes(name)) name = `${base}_${j++}`;
            const list = [...names, name];
            d[0] = composeSubjects([...s.rows, { name, text: ref ? `is ... whose appearance comes from {picture:${ref}}.` : "is ..." }], s.extra);
            const rows = parseRetention(d[2]);
            if (rows) d[2] = composeRetention([...rows, retentionLine(name)]);
            setNames(list);
            c.prompt = H3.composeSections(d.map((t) => toPrompt(t, list)));
            ctx.changed(true);
        }

        // ---- summary
        const sum = splitSummary(disp[1]);
        box("summary:", _t("sections.one_paragraph_the_prefix_is_added")).append(...[
            h("div", { class: "sx-lock" }, PREFIX),
            sum.had ? null : h("div", { class: "sx-warn" }, _t("sections.the_prefix_was_missing_it_will")),
            ta(sum.text, (v) => commit(1, composeSummary(v)), { placeholder: _t("sections.subject_what_the_clip_shows") })].filter(Boolean));

        // ---- retention_analysis
        const ret = parseRetention(disp[2]);
        const s2 = box("retention_analysis:", ret ? _t("sections.one_line_per_subject") : _t("sections.free_form_edited_as_text"));
        if (ret) {
            const commitRet = (structural) => commit(2, composeRetention(ret), structural);
            ret.forEach((r, i) => {
                const known = names.includes(r.name);
                s2.append(h("div", { class: "sx-row sx-ret" },
                    h("span", { class: `sx-chip ${known ? "sx-chipS" : "sx-chipX"}`, title: known ? r.scope : _t("sections.unknown_subject") }, "@" + r.name),
                    h("select", { onchange: (e) => { r.mode = e.target.value; commitRet(false); } }, MODES.map((m) => h("option", { value: m, selected: m === r.mode || null }, m))),
                    ta(r.why, (v) => { r.why = v; commitRet(false); }, { one: true, placeholder: _t("sections.why") }),
                    h("button", { class: "small danger", title: _t("sections.remove_this_line"), onclick: () => { ret.splice(i, 1); commitRet(true); } }, "✕")));
            });
            const missing = names.filter((n) => !ret.some((r) => r.name === n));
            if (missing.length) s2.append(h("div", { class: "sx-row" }, missing.map((n) =>
                h("button", { class: "small", onclick: () => { ret.push(retentionLine(n)); ret.sort((a, b) => names.indexOf(a.name) - names.indexOf(b.name)); commitRet(true); } }, _t("sections.line_for", { n })))));
        } else {
            s2.append(ta(disp[2], (v) => commit(2, v)));
        }

        // ---- detailed_description
        const det = parseDetailed(disp[3]);
        const custom = customOpening(det);
        const auto = custom ? "" : expectedSentence(c, ctx.index, free);
        const commitDet = (structural, fix) => commit(3, composeDetailed(det.style, det.shots, fix ? auto : openingFor(det)), structural);
        const s3 = box("detailed_description:", _t("sections.style_then_one_block_per_shot"),
            fromPrev(_t("sections.style_of_the_previous_clip"), () => { const p = prevDisplay(3); if (p == null) return; det.style = toDisplay(toPrompt(parseDetailed(p).style, subjectNames(prev, prevParts)), names); commitDet(true); }));
        s3.append(h("div", { class: "sx-hint" }, "style"), ta(det.style, (v) => { det.style = v; commitDet(false); }, { one: true, placeholder: "The target video is …" }));
        if (custom) {
            s3.append(h("div", { class: "sx-hint", style: "margin:4px 0" }, _t("sections.shot_1_starts_with_an_opening")));
        } else if (det.found !== auto) {
            s3.append(h("div", { class: "sx-warn" },
                auto ? (det.found ? _t("sections.the_opening_sentence_does_not_match") : _t("sections.the_required_opening_sentence_is_missing"))
                    : _t("sections.the_first_clip_has_no_required"),
                h("button", { class: "small", onclick: () => commitDet(true, true) }, auto ? _t("sections.use_the_right_sentence") : _t("sections.remove_it"))));
        }
        if (!det.shots.length) det.shots.push("");
        det.shots.forEach((body, i) => {
            s3.append(h("div", { class: "sx-shot" },
                h("div", { class: "sx-row" }, h("span", { class: "sx-code" }, `[Shot ${i + 1}]`), h("span", { class: "grow" }),
                    det.shots.length > 1 ? h("button", { class: "small danger", title: _t("sections.delete_this_shot"), onclick: () => { det.shots.splice(i, 1); commitDet(true); } }, "✕") : null),
                i === 0 && auto ? h("div", { class: "sx-lock", title: _t("sections.sentence_required_by_how_the_clip") }, auto) : null,
                ta(body, (v) => { det.shots[i] = v; commitDet(false); }, { placeholder: _t("sections.framing_place_light_action_camera_acting") })));
        });
        s3.append(h("button", { class: "small", onclick: () => { det.shots.push(""); commitDet(true); } }, `+ [Shot ${det.shots.length + 1}]`));

        // ---- overall_soundscape, non_diegetic_music
        box("overall_soundscape:", free ? _t("sections.sounds_of_the_place_never_any") : _t("sections.a_few_quiet_sounds_under_the"),
            fromPrev(_t("sections.from_the_previous_clip"), () => { const p = prevDisplay(4); if (p != null) commit(4, toDisplay(toPrompt(p, subjectNames(prev, prevParts)), names), true); }))
            .append(ta(disp[4], (v) => commit(4, v), { one: true }));
        box("non_diegetic_music:", free ? _t("sections.free_mode_none") : _t("sections.this_part_of_the_song_no"),
            fromPrev(_t("sections.from_the_previous_clip"), () => { const p = prevDisplay(5); if (p != null) commit(5, toDisplay(toPrompt(p, subjectNames(prev, prevParts)), names), true); }))
            .append(ta(disp[5], (v) => commit(5, v), { one: true }));
    }

    // ------------------------------------------------------------------ the palette (right column)
    function palette(side, ctx) {
        const c = ctx.clip;
        const parts = c ? H3.parseSections(c.prompt) : null;
        const names = c ? subjectNames(c, parts) : [];
        const sect = (title, ...kids) => h("section", { class: "box sx-pal" }, h("h2", {}, title), ...kids);
        if (!c) return;

        // references of the clip
        const declared = Object.keys(ctx.plan.refs || {});
        const avail = declared.filter((r) => !(c.refs || []).includes(r));
        const refs = sect(_t("sections.clip_references"),
            h("div", { class: "hint" }, ctx.media ? _t("sections.previews_branch_drag_a_reference_into", { v0: ctx.media.label() }) : _t("sections.drag_a_reference_into_a_text")));
        (c.refs || []).forEach((r, k) => {
            const img = ctx.media ? ctx.media.image(r) : null;
            const voice = ctx.free && ctx.media ? ctx.media.voice(r) : null;
            let thumb;
            if (img) {
                const im = h("img", { src: img, alt: r, class: "sx-thumb" });
                thumb = window.H3Takes && window.H3Takes.zoomable ? window.H3Takes.zoomable(im, r) : im;
            } else thumb = h("div", { class: "sx-thumb sx-thumb-empty", title: ctx.media ? _t("sections.no_picture_in_this_branch") : "" }, "—");
            refs.append(h("div", { class: "sx-refrow" },
                h("span", { class: "sx-num" }, k + 1),
                thumb,
                h("div", { class: "sx-refmain" },
                    h("span", { class: "sx-chip sx-chipR", draggable: "true", ondragstart: dragText(`{picture:${r}}`), title: (ctx.plan.refs || {})[r] || "" }, r),
                    h("span", { class: "sx-desc", title: (ctx.plan.refs || {})[r] || "" }, (ctx.plan.refs || {})[r] || ""),
                    voice ? playButton(voice) : null),
                h("span", { class: "sx-refbtns" },
                    h("button", { class: "small", title: _t("sections.move_earlier"), disabled: k === 0 || null, onclick: () => { [c.refs[k - 1], c.refs[k]] = [c.refs[k], c.refs[k - 1]]; ctx.changed(true); } }, "‹"),
                    h("button", { class: "small", title: _t("sections.move_later"), disabled: k === c.refs.length - 1 || null, onclick: () => { [c.refs[k + 1], c.refs[k]] = [c.refs[k], c.refs[k + 1]]; ctx.changed(true); } }, "›"),
                    h("button", { class: "small", title: _t("sections.remove_from_the_clip"), onclick: () => { c.refs.splice(k, 1); ctx.changed(true); } }, "✕"))));
        });
        const tools = h("div", { class: "sx-row" });
        if (avail.length) tools.append(h("select", { onchange: (e) => { if (e.target.value) { c.refs = [...(c.refs || []), e.target.value]; ctx.changed(true); } } },
            h("option", { value: "" }, _t("sections.plan_reference")), avail.map((r) => h("option", { value: r }, r))));
        else if (!declared.length) tools.append(h("span", { class: "hint" }, _t("sections.declare_the_references_in_plan_settings")));
        if (ctx.prevClip) tools.append(h("button", { class: "small", onclick: () => { c.refs = [...(ctx.prevClip.refs || [])]; ctx.changed(true); } }, _t("sections.those_of_the_previous_clip")));
        refs.append(tools);
        side.append(refs);

        if (parts) {
            side.append(sect(_t("sections.subjects"), h("div", { class: "sx-chips" }, names.length
                ? names.map((n, i) => h("span", { class: "sx-chip sx-chipS", draggable: "true", ondragstart: dragText("@" + n), title: `<Subject ${i + 1}>` },
                    subjectImage(ctx, n) ? h("img", { src: subjectImage(ctx, n), alt: "" }) : null, `@${n}`))
                : h("span", { class: "hint" }, _t("sections.no_subject")))));
            const dl = dialogueItems(ctx, names);
            if (dl.length) side.append(sect(ctx.free ? _t("sections.lines") : _t("sections.lyrics"), ...dl.map((d) => h("div", { class: "sx-dl" },
                h("span", { class: "sx-chip sx-chipD", draggable: "true", ondragstart: dragText(d.ins), title: d.ins }, `⠿ ${d.label}`),
                h("div", { class: "sx-dltext" }, d.hint)))));
            side.append(sect(_t("sections.stock_sentences"), h("div", { class: "sx-chips" }, snippets(ctx, names).map((p) =>
                h("span", { class: "sx-chip sx-chipP", draggable: "true", ondragstart: dragText(p.ins), title: p.ins }, p.label)))));
        }
        side.append(checksBox(ctx));
    }
    function checksBox(ctx) {
        const c = ctx.clip;
        const parts = c ? H3.parseSections(c.prompt) : null;
        const checks = c ? clipChecks(ctx, parts, subjectNames(c, parts)) : [];
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
        const b = h("button", { class: "small", title: _t("sections.play_the_voice"), onclick: () => { if (audio.paused) { audio.currentTime = 0; audio.play(); } else audio.pause(); } }, _t("sections.voice_2"));
        audio.addEventListener("play", () => { b.textContent = _t("sections.voice_3"); });
        audio.addEventListener("pause", () => { b.textContent = _t("sections.voice_2"); });
        audio.addEventListener("ended", () => { b.textContent = _t("sections.voice_2"); });
        return h("span", {}, b, audio);
    }
    // checks of the clip: the plan's own, plus the editor's (@names, subjects)
    function clipChecks(ctx, parts, names) {
        const out = (ctx.messages || []).map((m) => ({ level: m.level, text: m.text }));
        if (!parts) return out;
        const all = parts.map((p) => toDisplay(p, names)).join("\n");
        for (const n of unknownMentions(all, names)) out.push({ level: "error", text: _t("sections.unknown_subject_in_this_clip", { n }) });
        const subj = parseSubjects(toDisplay(parts[0], names), names);
        subj.rows.forEach((r) => { if (!r.text.trim()) out.push({ level: "warning", text: _t("sections.has_no_definition", { name: r.name }) }); });
        const det = parseDetailed(toDisplay(parts[3], names));
        if (!det.shots.some((s) => s.trim())) out.push({ level: "warning", text: _t("sections.no_shot_is_written") });
        if (!splitSummary(toDisplay(parts[1], names)).text.trim()) out.push({ level: "warning", text: _t("sections.summary_is_empty") });
        return out;
    }

    return {
        subjectNames, toDisplay, toPrompt, parseSubjects, composeSubjects, parseRetention, composeRetention, splitSummary, composeSummary,
        parseDetailed, composeDetailed, expectedSentence, customOpening, openingFor, remapSubjects, inheritedPrompt, unknownMentions,
        render, palette, refreshChecks, closeAc,
    };
})();
if (typeof module !== "undefined") module.exports = H3Sections;
