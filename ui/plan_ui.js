// ---------------------------------------------------------------------------------------------
// H3 Clip Plan editor - user interface
// ---------------------------------------------------------------------------------------------
(() => {
    const FPS = H3.FPS;
    const SCENE_COLORS = ["#3a6ea5", "#8a5a9e", "#3f8f6b", "#a8693a", "#9b4b5c", "#4f7f8f", "#7d7a3a", "#5b5fa8"];

    const S = {
        plan: null, sel: 0, fileName: "", handle: null, dirty: false,
        locked: 0, lockedTakes: {},          // Encore: clips 1..locked are generated takes, shown read-only
        undo: [], redo: [], lastSnap: "", snapTimer: null,
        messages: [], compose: null, composeKey: "", composeTimer: null,   // compose: the server's answer (POST /plan/compose)
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
    const INSTR = -1;       // the « common instruction » entry of an edited video, before clip 1
    const onInstr = () => S.sel === INSTR && !!S.plan.edit_video;
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

    // opts (Encore): {locked: clips 1..n generated, read-only; takes: {index: take id}; sel: clip to show}
    function setPlan(plan, fileName, handle, opts = {}) {
        if (!plan || typeof plan !== "object" || Array.isArray(plan)) throw new Error(_t("plan.the_file_does_not_hold_a"));
        if (!Array.isArray(plan.clips)) plan.clips = [];
        if (!plan.clips.length) plan.clips.push(newClip(1, plan));
        for (const k of ["files", "subjects"]) if (!plan[k] || typeof plan[k] !== "object" || Array.isArray(plan[k])) plan[k] = {};
        S.plan = plan;
        S.locked = Math.max(0, Math.min(Number(opts.locked) || 0, plan.clips.length));
        S.lockedTakes = opts.takes || {};
        S.frozen = opts.frozen || null;
        S.lineCell = !!opts.lineCell;
        S.lockLength = new Set((opts.lockLength || []).map(Number));   // 0.49: clips whose length and link stay (before clips taken over)
        S.free = new Set((opts.free || []).map(Number));               // 0.49: clips left free in a duplicate, editable among the locked ones            // 0.48: the launch panel of a cell of the master line (its clip read-only)           // 0.48: a master plan frozen by the takes of its branch: {clips, subjects}
        S.sel = Math.max(0, Math.min(opts.sel ?? (S.locked < plan.clips.length ? S.locked : 0), plan.clips.length - 1));
        S.fileName = fileName || "plan.json";
        S.handle = handle || null;
        S.dirty = false;
        S.undo = []; S.redo = [];
        S.lastSnap = snapshot();
        renderAll();
        updateUndoButtons();
        if (plan.version !== H3.PLAN_VERSION) toast(_t("plan.plan_version_refused", { version: plan.version }));
        if (!$("takesView").hidden) window.H3Takes?.onShow();
    }

    function newPlan(mode) {
        const plan = { version: H3.PLAN_VERSION, project: "nouveau_projet", mode, files: {}, subjects: {}, context_frames: 39, crossfade_frames: 0, clips: [] };
        if (mode === "music_video") plan.song = { file: "chanson.mp3", duration_seconds: 60 };
        plan.clips.push(newClip(1, plan));
        return plan;
    }

    function newClip(index, plan, after) {
        const names = new Set((plan.clips || []).map((c) => c.name));
        let k = index, name;
        do { name = `clip_${String(k).padStart(3, "0")}`; k++; } while (names.has(name));
        const free = H3.mode(plan) === "free";
        const clip = { name, frames: after ? after.frames : 209, continue: !!after, summary: "", description: "[Shot 1] " };
        if (free) clip.dialogue = [];
        // a clip added after another keeps its subject settings, style, soundscape and music
        if (after && typeof H3Sections !== "undefined") H3Sections.inheritedClip(after, clip);
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
        S.plan.version = H3.PLAN_VERSION;
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
        if (S.sel === INSTR && !S.plan.edit_video) S.sel = 0;
        S.messages = messages();
        scheduleCompose();
        renderHeader();
        renderTimeline();
        renderPalette();
        if (S.settingsBox && S.settingsBox.isConnected) renderSettings(S.settingsBox);
        renderList();
        renderEditor();
    }
    function renderLive() {
        S.messages = messages();
        renderHeader();
        renderTimeline();
        renderValidation();
        renderList();
        renderClipMessages();
        renderTiming();
        renderRate();
        updateUndoButtons();
        scheduleCompose();
        clearTimeout(S.checksTimer);
        S.checksTimer = setTimeout(() => { if (curClip()) H3Sections.refreshCompose(sectionsCtx()); }, 300);
    }
    // the checks: the page's own (ui/plan_core.js), and for a prompt written by hand, the server's (they need it composed)
    function messages() {
        const out = H3.validate(S.plan);
        const made = S.compose && S.compose.clips;
        if (made) clips().forEach((c, i) => {
            if (!(typeof c.prompt_override === "string" && c.prompt_override.trim())) return;
            const own = made[i];
            if (!own) return;
            for (const t of own.errors) out.push({ level: "error", clip: i + 1, text: t });
            for (const t of own.warnings) out.push({ level: "warning", clip: i + 1, text: t });
        });
        return out;
    }
    // the H3 prompt of every clip, composed by the server a moment after a change (Encore; nothing without a server)
    function scheduleCompose() {
        const composer = window.H3Editor && window.H3Editor.composer;
        if (!composer) return;
        const key = JSON.stringify(S.plan);
        if (key === S.composeKey) return;
        clearTimeout(S.composeTimer);
        S.composeTimer = setTimeout(async () => {
            S.composeKey = key;
            let res;
            try { res = await composer(JSON.parse(key)); } catch (_) { S.composeKey = ""; return; }
            if (key !== JSON.stringify(S.plan)) return;         // changed meanwhile: the next answer will do
            S.compose = { clips: res.clips || [], errors: res.errors || [] };
            S.messages = messages();
            renderHeader();
            renderValidation();
            renderList();
            renderClipMessages();
            if (curClip()) H3Sections.refreshCompose(sectionsCtx());
        }, 350);
    }

    function renderHeader() {
        $("fileName").innerHTML = "";
        $("fileName").append(S.fileName, S.dirty ? h("span", { class: "dirty" }, " ●") : "");
        const planTitle = document.getElementById("studioPlanTitle");     // Encore: the title of the plan screen shows the unsaved changes
        if (planTitle) planTitle.classList.toggle("dirty", !!S.dirty);
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
        const sv = H3.startVideo(S.plan), first = H3.finalStart(S.plan), songAt = H3.songOffset(S.plan) / FPS;
        const songDur = !isFree() && S.plan.song && typeof S.plan.song.duration_seconds === "number" ? S.plan.song.duration_seconds : null;
        const span = Math.max(total / FPS, songDur !== null ? songDur + songAt : 0) + 0.5;
        const width = Math.max(box.clientWidth - 26, 300);
        const pps = Math.max(width / span, 14);
        const x = (frames) => (frames / FPS) * pps;
        const scenes = [];
        let scene = -1;
        rows.forEach((r) => { if (!r.continue) scene++; scenes.push(scene); });
        const nScenes = scene + 1;

        box.append(h("div", { class: "tl-head" },
            h("span", {}, _t("plan.length"), h("b", {}, sec(total - first, 2))),
            sv ? h("span", {}, _t("plan.starts_from_video"), h("b", {}, `${sv.ref} ${secv(sv.frames / FPS, 2)}`)) : null,
            H3.editVideo(S.plan) ? (() => { const ev = H3.editVideo(S.plan); return h("span", { class: "tl-edit", title: _t("plan.edit_video_timeline_title"), onclick: () => openSettings() },
                _t("plan.edits_video"), h("b", {}, `${ev.ref} ${secv(ev.start_frame / FPS, 2)} → ${secv(ev.end_frame / FPS, 2)}`)); })() : null,
            h("span", {}, h("b", {}, rows.length), " clips"),
            h("span", {}, h("b", {}, nScenes), nScenes > 1 ? _t("plan.scenes_continuous_shots") : _t("plan.scene_continuous_shot")),
            h("span", {}, "mode ", h("b", {}, isFree() ? _t("plan.free") : _t("plan.music_video"))),
            songDur !== null ? h("span", {}, _t("plan.song_2"), h("b", {}, secv(songDur, 2))) : null));

        const tl = h("div", { class: "tl", style: `width:${span * pps}px` });
        const ruler = h("div", { class: "ruler" });
        const step = pps > 60 ? 1 : pps > 25 ? 2 : 5;
        for (let t = 0; t <= span; t += step) ruler.append(h("div", { class: "tick", style: `left:${t * pps}px` }, `${t}s`));
        tl.append(ruler);
        if (sv) {               // the start video segment, before clip 1 (hatched when it is not in the final video)
            tl.append(h("div", {
                class: `block startvid${sv.in_assembly ? "" : " out"}`, style: `left:0;width:${Math.max(x(sv.frames) - 1, 3)}px`,
                title: _t("plan.start_video_block", { ref: sv.ref, v1: secv(sv.start_frame / FPS, 2), v2: secv(sv.end_frame / FPS, 2) })
                    + (sv.in_assembly ? "" : "\n" + _t("plan.start_video_not_in_video")),
                onclick: () => openSettings(),
            }, h("span", { class: "n" }, "▶"), h("span", {}, sv.ref), " ", h("span", { class: "d" }, secv(sv.frames / FPS))));
            if (songAt > 0 && songDur !== null) tl.append(h("div", { class: "songend", style: `left:${songAt * pps}px` }, h("span", {}, _t("plan.start_of_the_song"))));
        }
        const editedTl = H3.editClipCount(S.plan);
        rows.forEach((r, i) => {
            const st = clipStatus(r.index);
            const left = x(r.visible), w = Math.max(x(r.end) - x(r.visible) - 1, 3);
            const block = h("div", {
                class: `block${i === S.sel ? " sel" : ""}${st.e ? " has-err" : ""}${st.w ? " has-warn" : ""}`,
                style: `left:${left}px;width:${w}px;background:${SCENE_COLORS[scenes[i] % SCENE_COLORS.length]}`,
                title: `#${r.index} ${r.name}\n${r.continue ? _t("plan.continuation") : r.index === 1 ? _t("plan.start") : _t("plan.new_scene_cut")}\nvisible ${sec(r.visible)} → ${sec(r.end)}\n${r.frames} images`,
                onclick: () => select(i),
            }, h("span", { class: "n" }, r.index), i < editedTl ? h("span", { title: _t("plan.edits_the_video_hint") }, "🎞 ") : null, h("span", {}, r.name), " ", h("span", { class: "d" }, secv((r.end - r.visible) / FPS)));
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
        if (songDur !== null) tl.append(h("div", { class: "songend", style: `left:${(songDur + songAt) * pps}px` }, h("span", {}, _t("plan.end_of_the_song"))));
        const evt = H3.editVideo(S.plan);
        if (evt) tl.append(h("div", { class: "songend segend", style: `left:${x(evt.frames)}px`, title: _t("plan.segment_end_title") }, h("span", {}, _t("plan.segment_end"))));
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
        if (onInstr()) instructionPalette(side);
        else if (curClip()) H3Sections.palette(side, sectionsCtx());
        side.append(h("section", { class: "box sx-pal" }, h("h2", {}, _t("plan.plan_checks")), h("ul", { class: "vlist", id: "vlist" })));
        renderValidation();
    }
    function sectionsCtx() {
        const c = curClip();
        const made = S.compose && S.compose.clips ? S.compose.clips[S.sel] : null;
        return {
            plan: S.plan, clip: c, index: S.sel + 1, free: isFree(), prevClip: S.sel > 0 ? clips()[S.sel - 1] : null,
            changed, toast, lastLanguage: () => lastLanguage(c), redraw: () => { renderPalette(); renderEditor(); },
            media: (window.H3Editor && window.H3Editor.media) || null,
            messages: S.messages.filter((m) => m.clip === S.sel + 1),
            compose: made && made.index === S.sel + 1 ? made : null,
            locked: isLocked(S.sel), lockedCount: S.locked, isLocked,
            frozenSubjects: (S.frozen && S.frozen.subjects) || [],
        };
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

        const studio = !!(window.H3Editor && H3Editor.media && H3Editor.media.studio);
        const proj = h("section", { class: "box" }, h("h2", {}, _t("plan.project")),
            studio ? h("div", { class: "hint", style: "margin-bottom:6px" }, _t("plan.essence_in_project_settings"), " ",
                h("button", { class: "small", onclick: () => { const ov = side.closest(".tk-modal"); if (ov) ov.remove(); S.settingsBox = null; H3Editor.media.openProjectSettings(); } }, _t("plan.open_project_settings"))) : null,
            h("div", { class: "grid2" },
                studio ? null : field(_t("plan.project_name"), h("input", { value: p.project ?? "", oninput: (e) => { p.project = e.target.value; changed(false); } })),
                studio ? null : field(_t("plan.mode"), h("select", { onchange: (e) => switchMode(e.target.value) },
                    h("option", { value: "free", selected: free }, _t("plan.free_generated_sound")),
                    h("option", { value: "music_video", selected: !free }, _t("plan.music_video")))),
                studio ? null : field(_t("plan.context"), h("select", { onchange: (e) => { p.context_frames = +e.target.value; changed(true); } },
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
                free || studio ? null : field(_t("plan.song"), h("input", { value: p.song?.file ?? "", placeholder: _t("plan.file_for_the_record"),
                    oninput: (e) => { p.song = p.song || {}; setKey(p.song, "file", e.target.value); changed(false); } })),
                free || studio ? null : field(_t("plan.song_length_s"), h("input", { type: "number", step: "0.01", min: 0, value: p.song?.duration_seconds ?? "",
                    onchange: (e) => { p.song = p.song || {}; setKey(p.song, "duration_seconds", numOrUndef(e.target.value)); changed(true); } })),
            ),
            h("div", { style: "margin-top:8px" }, h("label", {}, _t("plan.notes")),
                h("textarea", { style: "font-family:inherit;min-height:40px", value: p.notes ?? "",
                    oninput: (e) => { setKey(p, "notes", e.target.value); changed(false); } })));
        if (p.width != null || p.height != null) {
            proj.append(h("div", { class: "hint", style: "margin-top:6px" }, _t("plan.fallback_size_in_the_plan", { width: p.width, height: p.height }),
                h("button", { class: "small", onclick: () => { delete p.width; delete p.height; changed(true); } }, _t("plan.remove_it_size_chosen_in_the"))));
        }
        side.append(proj);
        side.append(startVideoBox());
    }

    // « Video » of the plan: none, a start video (clip 1 continues or cuts from a segment of a video file), or an
    // edited video (every clip edits its slice of the segment; free mode). One file for the project (chosen here, the
    // same in every branch); the plan names it with a reference of its own, kept out of the reference lists.
    const startVideoRef = () => ((S.plan.start_video || S.plan.edit_video || {}).ref) || null;
    function startVideoBox() {
        const p = S.plan;
        const free = isFree();
        const editing = !!p.edit_video && !p.start_video;
        const sv = p.start_video || p.edit_video;
        const kind = p.start_video ? "continue" : p.edit_video ? "edit" : "none";
        const media = window.H3Editor && window.H3Editor.media;
        const box = h("section", { class: "box start-video" }, h("h2", {}, _t("plan.video_of_the_plan")));
        const redraw = () => box.replaceWith(startVideoBox());
        const setKind = (next) => {
            if (next === kind) return;
            const old = p.start_video || p.edit_video;
            let ref = old && old.ref;
            if (!ref) { ref = "video"; let k = 2; while (ref in (p.files || {})) ref = `video_${k++}`; }
            delete p.start_video; delete p.edit_video;
            p.files = { ...(p.files || {}) };
            if (next === "none") {
                delete p.files[ref];
                if (clips()[0] && clips()[0].continue) setContinue(clips()[0], false, 1);
            } else if (next === "continue") {
                p.files[ref] = { kind: "video", note: _t("plan.start_video_ref_desc") };
                p.start_video = { ref, start: old ? old.start ?? 0 : 0, end: old ? old.end : 4 };
                if (clips()[0]) setContinue(clips()[0], true, 1);
            } else {
                p.files[ref] = { kind: "video", note: _t("plan.edit_video_ref_desc") };
                p.edit_video = { ref, start: old ? old.start ?? 0 : 0, end: old ? old.end : 10 };
                if (clips()[0] && clips()[0].continue) setContinue(clips()[0], false, 1);
            }
            changed(true);
        };
        const kindSel = h("select", { class: "sv-kind", onchange: (e) => setKind(e.target.value) },
            h("option", { value: "none", selected: kind === "none" || null }, _t("plan.video_none")),
            h("option", { value: "continue", selected: kind === "continue" || null }, _t("plan.video_continue")),
            h("option", { value: "edit", selected: kind === "edit" || null, disabled: (!free && kind !== "edit") || null }, _t("plan.video_edit")));
        const studio = !!(media && media.studio);
        const frozenWhy = studio && media.segmentFrozen ? media.segmentFrozen() : null;
        const parts = [h("div", { class: "tk-inline" }, studio ? h("b", { class: "sv-kind-label" }, _t(kind === "edit" ? "plan.video_edit" : kind === "continue" ? "plan.video_continue" : "plan.video_none")) : kindSel),
            h("div", { class: "hint" }, kind === "edit" ? _t("plan.edit_video_hint") : kind === "continue" ? _t("plan.start_video_hint")
                : _t("plan.video_none_hint") + (free ? "" : " " + _t("plan.edit_video_needs_free")))];
        if (!sv) { box.append(...parts); return box; }

        // the file: one of the imported videos, or a new one imported from here
        const current = media && media.startVideoFile ? media.startVideoFile() : null;
        const choose = async (rel) => {
            try { await media.setStartVideoFile(rel); } catch (err) { H3Dialog.alert(err.message); }
            redraw();
        };
        if (media && media.videos && !studio) {
            parts.push(h("div", { class: "tk-inline sv-file" },
                h("select", { onchange: (e) => choose(e.target.value || null) },
                    h("option", { value: "" }, _t("plan.start_video_choose")),
                    media.videos().map((v) => h("option", { value: v.path, selected: v.path === current || null }, v.name))),
                h("button", { onclick: async () => {
                    try { const path = await media.importVideo(); if (path) await choose(path); } catch (err) { if (err.code !== "cancelled") H3Dialog.alert(err.message); redraw(); }
                } }, _t("plan.start_video_import"))));
            if (!editing) {
                const warn = h("div", { class: "hint sv-takes" });
                parts.push(warn);
                if (media.clip1Takes) media.clip1Takes().then((count) => { if (count) warn.textContent = _t("plan.start_video_takes_warning", { count }); }).catch(() => {});
            }
        } else if (!studio) {
            parts.push(h("div", { class: "hint" }, _t("plan.start_video_no_file_editor")));
        } else if (!current) {
            parts.push(h("div", { class: "hint" }, _t("plan.video_file_in_project_settings")));
        }
        const url = media && media.video ? media.video() : null;
        const playable = url && media.playableVideo ? media.playableVideo(media.startVideoFile(), "sv-player") : null;   // a copy if the browser cannot play it
        const player = playable ? playable.video : url ? h("video", { controls: true, preload: "metadata", src: url, class: "sv-player" }) : null;
        if (player) parts.push(playable ? playable.wrap : player);

        // the segment
        const segment = () => (editing ? H3.editVideo(p) : H3.startVideo(p));
        const info = h("div", { class: "hint sv-info" });
        const num = (key, value) => h("input", { type: "number", step: (1 / FPS).toFixed(5), min: 0, value: value ?? "", style: "width:110px",
            onchange: (e) => { const v = Math.max(0, Math.round((+e.target.value || 0) * FPS) / FPS); sv[key] = v; e.target.value = v; changed(false); showInfo(); } });
        const startIn = num("start", sv.start ?? 0), endIn = num("end", sv.end);
        const fromPlayer = (key, input) => h("button", { class: "small", disabled: !player || null, title: _t("plan.start_video_from_player_hint"),
            onclick: () => { const v = Math.round(player.currentTime * FPS) / FPS; sv[key] = v; input.value = v; changed(false); showInfo(); } },
            key === "start" ? _t("plan.start_video_set_start") : _t("plan.start_video_set_end"));
        let stopAt = null;
        const playSegment = h("button", { class: "small", disabled: !player || null, onclick: () => {
            const n = segment();
            if (!n || !player) return;
            player.currentTime = n.start_frame / FPS; stopAt = n.end_frame / FPS; player.play();
        } }, _t("plan.start_video_play"));
        const sizeWarn = h("div", { class: "hint sv-size", hidden: true });
        if (player) player.addEventListener("timeupdate", () => { if (stopAt !== null && player.currentTime >= stopAt) { player.pause(); stopAt = null; } });
        if (player) player.addEventListener("loadedmetadata", () => { showInfo(); if (editing) checkSize(); });
        function showInfo() {
            const n = segment();
            if (!n) { info.textContent = _t("plan.start_video_invalid"); return; }
            const moved = !editing && Math.abs(n.start_frame / FPS - (sv.start ?? 0)) > 1e-6;
            const dur = player && Number.isFinite(player.duration) && player.videoWidth ? player.duration : null;
            info.textContent = _t(editing ? "plan.edit_video_used" : "plan.start_video_used",
                { v0: secv(n.start_frame / FPS, 3), v1: secv(n.end_frame / FPS, 3), v2: secv(n.frames / FPS, 2), frames: n.frames })
                + (moved ? " " + _t("plan.start_video_moved") : "")
                + (dur !== null && n.end_frame / FPS > dur + 0.01 ? " " + _t("plan.start_video_after_end", { v0: secv(dur, 2) }) : "");
            if (editing && H3.framesLegal(p)) {
                const edited = H3.editClipCount(p), total = clips().length;
                info.textContent += " " + (edited < total ? _t("plan.edit_video_clips_split", { v0: edited ? `1–${edited}` : "—", v1: `${edited + 1}–${total}` })
                    : _t("plan.edit_video_clips_all", { count: total }));
            }
        }
        // the branches should have the proportions of the edited video, or its picture is cropped
        function checkSize() {
            const vw = player.videoWidth, vh = player.videoHeight;
            if (!vw || !vh || !media.branchSizes) return;
            const off = media.branchSizes().filter((b) => b.width && b.height && Math.abs(b.width / b.height - vw / vh) / (vw / vh) > 0.03);
            if (!off.length) { sizeWarn.hidden = true; return; }
            sizeWarn.hidden = false;
            sizeWarn.replaceChildren(h("span", {}, _t("plan.edit_video_size_warning", { v0: off.map((b) => `${b.name} (${b.width} × ${b.height})`).join(", "), v1: `${vw} × ${vh}` })),
                " ", media.fitBranchSizes ? h("button", { class: "small", onclick: async () => {
                    try { await media.fitBranchSizes(vw, vh, off.map((b) => b.id)); } catch (err) { H3Dialog.alert(err.message); }
                    checkSize();
                } }, _t("plan.edit_video_fit_size")) : null);
        }
        const fromStart = fromPlayer("start", startIn), fromEnd = fromPlayer("end", endIn);
        if (frozenWhy) for (const el of [startIn, endIn, fromStart, fromEnd]) { el.disabled = true; el.title = frozenWhy; }
        parts.push(h("div", { class: "tk-inline sv-range" }, h("span", {}, _t("plan.start_video_from")), startIn, fromStart,
            h("span", {}, _t("plan.start_video_to")), endIn, fromEnd, playSegment, frozenWhy ? h("span", { class: "tk-lock", title: frozenWhy }, "🔒") : null), info);

        if (editing) {
            parts.push(sizeWarn);
            const sound = sv.sound || "original";
            parts.push(h("label", { class: "tk-inline" }, h("input", { type: "radio", name: "evsound", checked: sound === "original",
                onchange: () => { delete sv.sound; changed(true); } }), _t("plan.edit_video_sound_original")),
            h("label", { class: "tk-inline" }, h("input", { type: "radio", name: "evsound", checked: sound === "h3",
                onchange: () => { sv.sound = "h3"; changed(true); } }), _t("plan.edit_video_sound_h3")));
            parts.push(h("div", { class: "tk-inline sv-instr" }, h("span", {}, _t("plan.common_instruction") + " : "),
                h("i", { class: "hint", style: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:520px" }, sv.instruction || _t("plan.common_instruction_empty")),
                h("button", { class: "small", onclick: () => {
                    const overlay = box.closest(".tk-modal");
                    if (overlay) { overlay.remove(); S.settingsBox = null; }
                    S.sel = INSTR - 1; select(INSTR);
                } }, _t("plan.common_instruction_edit"))));
            // cut the segment into clips: a new scene at each change of shot, long shots in equal parts that continue
            const maxSel = h("select", { class: "ev-max" }, [141, 175, 209, 243, 277, 311, 345].map((f) =>
                h("option", { value: f, selected: f === 243 || null }, secv(f / FPS, 1))));
            const state = h("span", { class: "hint ev-state" });
            const splitBtn = h("button", { class: "ev-split", onclick: async () => {
                const n = H3.editVideo(p);
                if (!n || !media || !media.sceneCuts || !current) { H3Dialog.alert(_t("plan.edit_video_choose_first")); return; }
                const keptAfter = H3.framesLegal(p) ? clips().slice(H3.editClipCount(p)) : [];
                const replaced = clips().length - keptAfter.length;
                if (replaced && !(await H3Dialog.confirm(keptAfter.length ? _t("plan.edit_video_replace_clips_keep", { count: replaced, kept: keptAfter.length })
                    : _t("plan.edit_video_replace_clips", { count: replaced })))) return;
                splitBtn.disabled = true; state.textContent = _t("plan.edit_video_finding_shots");
                let cuts;
                try { cuts = await media.sceneCuts(current, n.start_frame, n.end_frame); }
                catch (err) { splitBtn.disabled = false; state.textContent = ""; H3Dialog.alert(err.message); return; }
                const made = H3.editCuts(n.frames, cuts.map((c) => c - n.start_frame), H3.contextOf(p), +maxSel.value);
                if (!made.length) { splitBtn.disabled = false; state.textContent = ""; H3Dialog.alert(_t("plan.edit_video_too_short")); return; }
                p.clips = made.map((c, i) => editClip(c, i + 1)).concat(keptAfter);
                S.sel = 0;
                changed(true);
                toast(_t("plan.edit_video_split_done", { count: made.length, shots: cuts.length + 1 }));
            } }, _t("plan.edit_video_split"));
            parts.push(h("div", { class: "tk-inline ev-cut" }, splitBtn, h("span", {}, _t("plan.edit_video_max")), maxSel, state),
                h("div", { class: "hint" }, _t("plan.edit_video_split_hint")));
        } else {
            // how it goes on
            const first = clips()[0];
            parts.push(h("div", { class: "tk-inline" },
                h("label", {}, h("input", { type: "radio", name: "svlink", checked: !!(first && first.continue), onchange: () => { setContinue(first, true, 1); changed(true); } }), _t("plan.start_video_continue")),
                h("label", {}, h("input", { type: "radio", name: "svlink", checked: !(first && first.continue), onchange: () => { setContinue(first, false, 1); changed(true); } }), _t("plan.start_video_cut"))));
            const inVideo = sv.in_assembly !== false;
            parts.push(h("label", { class: "tk-inline" }, h("input", { type: "checkbox", checked: inVideo,
                onchange: (e) => { if (e.target.checked) delete sv.in_assembly; else sv.in_assembly = false; changed(true); } }), _t("plan.start_video_in_assembly")));
            if (!free) {
                parts.push(h("label", { class: "tk-inline" }, h("input", { type: "radio", name: "svsong", disabled: !inVideo || null, checked: (sv.song || "with_video") === "with_video",
                    onchange: () => { delete sv.song; changed(true); } }), _t("plan.start_video_song_with")),
                h("label", { class: "tk-inline" }, h("input", { type: "radio", name: "svsong", disabled: !inVideo || null, checked: sv.song === "after_video",
                    onchange: () => { sv.song = "after_video"; changed(true); } }), _t("plan.start_video_song_after")));
                if (!inVideo) parts.push(h("div", { class: "hint" }, _t("plan.start_video_song_not_in")));
            }
        }
        box.append(...parts);
        showInfo();
        return box;
    }
    // a clip made by « cut on the shots »: framing, motion and timing of <Video 1>; only the edit is left to write
    // (the common instruction opens its summary)
    function editClip(c, index) {
        return { name: `edit_${String(index).padStart(2, "0")}`, frames: c.frames, continue: c.continue, summary: "",
            description: "Same framing, camera motion, actions and timing as <Video 1>, frame by frame.\n[Shot 1] Everything the edit does not change stays as in <Video 1>.",
            soundscape: "The sound of <Video 1>, unchanged." };
    }
    // the link of a clip to the one before it (the composed prompt says it; a first-frame anchor no longer fits)
    function setContinue(c, value) {
        c.continue = value;
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
        const lockedSel = S.sel < S.locked;        // a generated clip: nothing moves before the end of the twig
        list.append(h("div", { class: "listbar" },
            h("span", { class: "tk-split" },
                h("button", { onclick: () => addClip(S.sel + 1), title: _t("plan.new_clip_after_the_selected_clip") }, "+ clip"),
                h("button", { class: "tk-split-arrow", title: _t("plan.other_ways_to_add_a_clip"), onclick: (e) => { e.stopPropagation(); addMenu(e.currentTarget); } }, "▾")),
            h("button", { onclick: duplicateClip, disabled: S.sel < 0 || S.sel + 1 < S.locked || null, title: _t("plan.duplicate_the_selected_clip") }, _t("plan.duplicate")),
            h("button", { onclick: () => moveClip(-1), disabled: S.sel <= S.locked || null, title: _t("plan.move_up") }, "↑"),
            h("button", { onclick: () => moveClip(1), disabled: lockedSel || S.sel < 0 || S.sel >= clips().length - 1 || null, title: _t("plan.move_down") }, "↓"),
            h("button", { class: "danger", onclick: deleteClip, disabled: lockedSel || S.sel < 0 || clips().length < 2 || null, title: _t("plan.delete_the_selected_clip") }, "✕")));
        const rows = H3.framesLegal(S.plan) ? H3.timeline(S.plan) : null;
        const edited = rows ? H3.editClipCount(S.plan) : 0;
        const ev = S.plan.edit_video;
        if (ev) {               // the common instruction of the edited video, worked like a prompt
            const users = edited;
            list.append(h("div", { class: `clipitem instr${S.sel === INSTR ? " sel" : ""}`, onclick: () => select(INSTR), title: _t("plan.common_instruction_hint") },
                h("span", { class: "num" }, "✎"),
                h("span", { class: "nm" }, _t("plan.common_instruction")),
                h("span", { class: "dot" }),
                h("span", { class: "meta" }, ev.instruction ? _t("plan.common_instruction_used", { count: users }) : _t("plan.common_instruction_empty"))));
        }
        clips().forEach((c, i) => {
            const st = clipStatus(i + 1);
            const r = rows ? rows[i] : null;
            const isEdit = i < edited;
            const own = isEdit && c.defs && typeof c.defs === "object" && "edit_instruction" in c.defs;
            const lock = isLocked(i);
            list.append(h("div", { class: `clipitem${i === S.sel ? " sel" : ""}${lock ? " locked" : ""}`, onclick: () => select(i),
                title: lock ? (S.frozen && !S.lockedTakes[i + 1] ? _t("plan.frozen_clip_title") : _t("plan.locked_clip_title", { take: S.lockedTakes[i + 1] || "?" })) : null },
                h("span", { class: "num" }, (lock ? "🔒" : "") + (i + 1)),
                h("span", { class: "nm", title: c.name + (isEdit ? "\n" + _t("plan.edits_the_video_hint") : "") }, (isEdit ? "🎞 " : "") + (c.continue ? "↪ " : i ? "✂ " : "") + (c.name || "")),
                h("span", { class: `dot ${st.e ? "e" : st.w ? "w" : ""}` }),
                h("span", { class: "meta" }, (r ? `${sec(r.visible, 1)} → ${sec(r.end, 1)} · ${_t("plan.n_fr", { n: c.frames })}` : _t("plan.n_frames", { n: c.frames }))
                    + (own ? " · " + _t("plan.own_text") : ""))));
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
        at = Math.max(at, S.locked);               // never among the generated clips of a twig
        const prev = empty ? null : clips()[at - 1];
        clips().splice(at, 0, newClip(at + 1, S.plan, prev));
        // edited video: a clip added after the segment continues the video, it cannot name <Video 1>
        const added = clips()[at];
        if (S.plan.edit_video && H3.framesLegal(S.plan) && at + 1 > H3.editClipCount(S.plan)
            && H3.TEXT_KEYS.some((k) => /<Video \d+>/.test(added[k] || ""))) {
            added.continue = at > 0;
            for (const k of H3.TEXT_KEYS) if (/<Video \d+>/.test(added[k] || "")) added[k] = k === "description" ? "[Shot 1] " : "";
        }
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
        delete copy.defs;          // a copy of a generated clip uses the plan's subjects as they are now
        clips().splice(S.sel + 1, 0, copy);
        S.sel++;
        changed(true);
    }
    function moveClip(d) {
        const j = S.sel + d;
        if (j < 0 || j >= clips().length || j < S.locked || S.sel < S.locked) return;
        const list = clips();
        [list[S.sel], list[j]] = [list[j], list[S.sel]];
        S.sel = j;
        changed(true);
    }
    async function deleteClip() {
        if (clips().length < 2 || S.sel < S.locked) return;
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
        if (onInstr()) { renderInstruction(ed); return; }
        const c = curClip();
        if (!c) { ed.append(h("div", { class: "empty" }, _t("plan.no_clip"))); return; }
        const n = S.sel + 1;
        const free = isFree();

        ed.append(h("div", { class: "ed-head" },
            h("span", { class: "t" }, _t("plan.clip", { n })),
            h("span", { class: "hint" }, c.continue ? _t("plan.continues_the_shot_of_the_previous") : n === 1 ? _t("plan.first_clip") : _t("plan.new_scene_cut"))));

        ed.append(h("div", { class: "fields" },
            h("div", {}, h("label", {}, _t("plan.name")), h("input", { value: c.name ?? "", oninput: (e) => { c.name = e.target.value; changed(false); } })),
            h("div", {}, h("label", {}, _t("plan.raw_length_frames")), h("select", { class: "ed-frames", disabled: S.lockLength.has(n) || null,
                title: S.lockLength.has(n) ? _t("plan.length_locked_title") : null, onchange: (e) => { c.frames = +e.target.value; changed(true); } }, framesOptions(c.frames, n))),
            h("div", {}, h("label", {}, _t("plan.link")), h("label", { class: "toggle", style: "color:var(--text)" },
                h("input", { type: "checkbox", checked: !!c.continue, disabled: (n === 1 && !c.continue && !S.plan.start_video) || S.lockLength.has(n) || null, onchange: (e) => toggleContinue(c, e.target.checked) }),
                _t("plan.continues_the_previous_clip"))),
            document.body.classList.contains("studio") ? null      // Encore: a seed belongs to a take, never to the plan
                : h("div", {}, h("label", {}, _t("plan.seed_empty_auto")), h("input", { type: "number", min: 0, value: c.seed ?? "", placeholder: "auto",
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
        autosizeAll();
        if (isLocked(S.sel)) lockEditor(ed, n);
    }
    // a clip shown read-only: generated (or frozen), but a clip left free in a duplicate (0.49); nothing moves before
    // S.locked all the same
    function isLocked(i) { return i < S.locked && !S.free.has(i + 1); }
    // a generated clip of a twig: shown as it was made, read-only, with « new take of this clip »
    function lockEditor(ed, n) {
        for (const el of ed.querySelectorAll("input, textarea, select, button")) {
            if (el.closest("#songCard") && el.tagName === "BUTTON") continue;     // listening to the song stays possible
            if (el.closest(".sx-tabs")) continue;                               // so does reading the H3 prompt
            if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") el.readOnly = true;
            el.disabled = true;
        }
        const take = S.lockedTakes[n];
        if (S.lineCell) { ed.prepend(h("div", { class: "locked-banner" }, h("span", {}, _t("plan.line_cell_banner")))); return; }
        const text = !S.frozen ? _t("plan.locked_clip_banner", { take: take || "?" })
            : take ? _t("plan.frozen_clip_banner_line", { take }) : _t("plan.frozen_clip_banner");
        ed.prepend(h("div", { class: "locked-banner" },
            h("span", {}, text),
            take && window.H3Editor.onLockedRetake ? h("button", { class: "small", onclick: () => window.H3Editor.onLockedRetake(n, take) }, _t("plan.locked_clip_retake")) : null));
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
        const off = H3.songOffset(S.plan);     // a start video can move the song: its time = timeline - offset
        const raw = Math.max(0, (r.raw_start - off) / FPS), vis = Math.max(0, (r.visible - off) / FPS), end = (r.end - off) / FPS;
        const shared = r.context > 0;
        const total = (S.plan.song && S.plan.song.duration_seconds) || Math.max(end, 1);
        card.dataset.raw = raw; card.dataset.end = end;
        const url = songUrl();
        const pct = (x) => `${Math.max(0, Math.min(100, x * 100)).toFixed(2)}%`;
        const btn = (kind, label, from) => h("button", { class: "small", "data-kind": kind, "data-label": label, disabled: !url || null, onclick: () => playSong(kind, from, end) }, label);
        card.append(h("div", { class: "song-bar-row" },
            btn("all", _t("plan.whole_passage"), raw),
            shared ? btn("new", _t("plan.new_part"), vis) : null,
            h("span", { class: "song-range" }, shared ? _t("plan.new_part_from", { v0: secv(raw, 2), v1: secv(end, 2), v2: secv(vis, 2) }) : `${secv(raw, 2)} → ${secv(end, 2)}`),
            h("span", { class: "grow" }),
            h("span", { class: "song-clock" })));
        card.append(h("div", { class: "song-all", title: _t("plan.the_whole_song_the_clip_s") },
            h("div", { style: `left:${pct(raw / total)};width:${pct((end - raw) / total)}` })));
        const span = end - raw;
        card.append(h("div", { class: "song-clip" },
            shared ? h("div", { class: "song-ctx", style: `width:${pct((vis - raw) / span)}`, title: _t("plan.overlap_context_taken_over_or_lead") }, h("span", {}, r.continue ? _t("plan.context") : _t("plan.lead_in"))) : null,
            h("div", { class: "song-new", style: `left:${pct(shared ? (vis - raw) / span : 0)}` }, h("span", {}, _t("plan.new_part_2"))),
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
        c.continue = value;          // the opening sentence of [Shot 1] is the server's: it follows the link
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
            h("button", { class: "small", onclick: () => { c.dialogue.push({ speaker: H3.clipSubjects(S.plan, c, S.sel + 1)[0] || Object.keys(S.plan.subjects || {})[0] || "", text: "", language: lastLanguage(c) }); changed(true); } }, _t("plan.line"))));
        c.dialogue.forEach((d, k) => {
            const speakers = [...new Set([...Object.keys(H3.definitions(S.plan, c).subjects), d.speaker].filter(Boolean))];
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
    // ---------------------------------------------------------------- the common instruction of an edited video
    function renderInstruction(ed) {
        const ev = S.plan.edit_video;
        ed.append(h("div", { class: "ed-head" }, h("span", { class: "t" }, _t("plan.common_instruction")),
            h("span", { class: "hint" }, _t("plan.common_instruction_replaces"))));
        const info = h("div", { class: "card instr-info" });
        const ta = h("textarea", { class: "instr-text", value: ev.instruction ?? "", spellcheck: "true", style: "min-height:110px;font-family:inherit",
            placeholder: _t("plan.common_instruction_placeholder"),
            oninput: (e) => { if (e.target.value.trim()) ev.instruction = e.target.value; else delete ev.instruction; changed(false); drawInfo(); autosize(e.target); } });
        H3Sections.attachAc(ta, () => instructionItems());
        H3Sections.acceptDrops(ta);
        const card = h("div", { class: "card" }, h("h2", {}, _t("plan.common_instruction")), ta,
            h("div", { class: "hint" }, _t("plan.common_instruction_tip")));
        ed.append(card, info);
        function drawInfo() {
            const rows = H3.framesLegal(S.plan) ? H3.timeline(S.plan) : [];
            const edited = rows.length ? H3.editClipCount(S.plan) : 0;
            const own = [];
            clips().forEach((c, i) => { if (i < edited && c.defs && typeof c.defs === "object" && "edit_instruction" in c.defs) own.push(i + 1); });
            const named = H3.mentions(ev.instruction || "");
            const subjects = S.plan.subjects || {};
            info.replaceChildren(...[
                h("div", { class: "lab" }, _t("plan.common_instruction_users")),
                h("div", {}, edited ? _t("plan.clips_list", { v0: `1–${edited}` }) : _t("plan.common_instruction_nobody"),
                    own.length ? h("span", { class: "hint" }, " · " + _t("plan.common_instruction_own", { v0: own.join(", ") })) : null),
                named.length ? h("div", { class: "lab" }, _t("plan.common_instruction_subjects")) : null,
                named.length ? h("div", {}, ...named.map((n) => h("span", { class: `sx-chip ${n in subjects ? "sx-chipS" : "sx-chipX"} instr-chip` }, "@" + n))) : null].filter(Boolean));
        }
        drawInfo();
        autosizeAll();
    }
    function instructionItems() {
        return Object.entries(S.plan.subjects || {}).map(([n, s]) => ({ kind: "S", label: "@" + n, hint: s.description || "", ins: "@" + n }));
    }
    function instructionPalette(side) {
        H3Sections.palette(side, { ...sectionsCtx(), clip: null });
    }

    function renderPrompt(c, n) {
        const card = h("div", { class: "card prompt-card" });
        H3Sections.render(card, sectionsCtx());
        return card;
    }
    // the text of a line of dialogue, at the caret of the description (its speaker named with @)
    function insertDialogue(c, d) {
        if (!String(d.text || "").trim()) { toast(_t("plan.the_line_is_empty")); return; }
        const area = document.querySelector('textarea[data-sec="description"]');
        if (!area) return;
        const v = area.value;
        let start = area.selectionStart ?? v.length;
        if (document.activeElement !== area && area.dataset.lastPos) start = +area.dataset.lastPos;
        const before = v.slice(0, start);
        const text = `${before && !/\s$/.test(before) ? " " : ""}@${d.speaker} says: <d>[${d.language || "French"}] ${d.text.trim()}</d>`;
        area.value = before + text + v.slice(start);
        area.focus();
        area.setSelectionRange(start + text.length, start + text.length);
        area.dispatchEvent(new Event("input"));
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
            // in Encore, only where the plan is edited: the plan screen or the launch panel (not the takes screen)
            const editing = !window.H3Studio || document.body.classList.contains("planscreen") || document.body.classList.contains("launching");
            if (editing && mod && !typing && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
            if (editing && mod && !typing && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
            if (!typing && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
                e.preventDefault();
                select(Math.max(0, Math.min(clips().length - 1, S.sel + (e.key === "ArrowUp" ? -1 : 1))));
            }
        });
        let depth = 0;
        // a plan file dropped on the page opens it (the editor alone). In Encore files are dropped on the places that import
        // them (Resources, library, subject window: 0.48.2): no full-page overlay over them, and a file dropped elsewhere
        // is ignored (never opened by the browser)
        const studio = () => document.body.classList.contains("studio");
        window.addEventListener("dragenter", (e) => { if (!studio() && [...(e.dataTransfer?.types || [])].includes("Files")) { depth++; $("drop").classList.add("on"); } });
        window.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) $("drop").classList.remove("on"); });
        window.addEventListener("dragover", (e) => e.preventDefault());
        window.addEventListener("drop", async (e) => {
            e.preventDefault();
            if (studio()) { depth = 0; return; }
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
    // the « Start video » section of the plan settings (from the Takes tab)
    function openStartVideo() {
        openSettings();
        setTimeout(() => { const el = document.querySelector(".start-video"); if (el) el.scrollIntoView({ block: "start" }); }, 50);
    }
    // the Takes view or the plan view (tabs of the stand-alone editor; in Encore, the Takes screen and the plan screen)
    function showView(takes) {
        for (const x of document.querySelectorAll("#viewTabs button")) x.classList.toggle("on", (x.dataset.view === "takes") === takes);
        $("planView").hidden = takes;
        $("planView").style.display = takes ? "none" : "";
        $("timeline").style.display = takes ? "none" : "";
        $("takesView").hidden = !takes;
        document.body.classList.toggle("planscreen", !takes);
        if (takes) window.H3Takes?.onShow(); else renderAll();
    }
    window.H3Editor = { state: S, setPlan, render: renderAll, toast, openStartVideo, showView, select, onLockedRetake: null,
        newClip: (index, plan, after) => newClip(index, plan, after) };
    for (const b of document.querySelectorAll("#viewTabs button")) b.onclick = () => showView(b.dataset.view === "takes");
    init();
})();
