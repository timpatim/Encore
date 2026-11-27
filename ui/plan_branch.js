// ---------------------------------------------------------------------------------------------
// Encore - the branch windows (chantier A, lot A2):
//   « + nouvelle branche »: empty, from a plan file, or a duplicate of a branch (without clips, or taking over the
//   clips 1..k of the selection, by reference);
//   « Réglages de la branche »: size, song, reference files, LoRA, upscale; what the takes fix is greyed, with why.
// Works with the helpers of plan_studio.js (H3Studio.kit) and the takes screen (H3Takes).
// ---------------------------------------------------------------------------------------------
(() => {
    function h(tag, attrs = {}, ...kids) {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v === undefined || v === null || v === false) continue;
            if (k === "class") node.className = v;
            else if (k === "style") node.style.cssText = v;
            else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
            else if (k === "value") node.value = v;
            else node.setAttribute(k, v === true ? "" : v);
        }
        for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) node.append(kid instanceof Node ? kid : String(kid));
        return node;
    }
    const _t = (k, v) => H3I18n.t(k, v);
    const K = () => window.H3Studio.kit;
    const S = () => window.H3Studio.state;
    const tk = () => window.H3Takes;

    // the project as the server sees it now: branches, what each one has fixed (branch_states)
    async function project() {
        const data = await K().api(K().base());
        S().branches = data.branches || S().branches;
        return data;
    }
    // a control greyed out with the reason (the server refuses it anyway)
    function frozen(el, why) {
        el.disabled = true;
        el.title = why;
        return el;
    }
    const lock = (why) => h("span", { class: "tk-lock", title: why }, "🔒");

    // ------------------------------------------------------------------ « + nouvelle branche »
    async function create(opts = {}) {
        let data;
        try { data = await project(); } catch (e) { alert(e.message); return; }
        const branches = data.branches || [];
        const twig = S().twig || {};
        // 0.48: « + nouvelle branche » makes an empty branch or one from a plan file; « dupliquer » (branch header)
        // copies a branch, without its clips (its master plan free again) or with the clips 1..k of the selection
        const dup = !!opts.duplicate;
        let how = dup ? (opts.how === "clips" ? "clips" : "copy") : (opts.how === "file" ? "file" : "empty");
        let source = opts.source || twig.branch || (branches[branches.length - 1] || {}).id || null;
        const nameIn = h("input", { placeholder: _t("branch.name_auto"), style: "flex:1" });
        const body = h("div", { class: "br-new" });
        const choice = (value, label, hint) => h("label", { class: `br-opt${how === value ? " on" : ""}` },
            h("input", { type: "radio", name: "brhow", checked: how === value || null, onchange: () => { how = value; draw(); } }),
            h("b", {}, label), hint ? h("span", { class: "hint" }, " — " + hint) : null);
        // 0.49: the clips taken over, in portions that each start a scene: clicking a clip keeps its scene from its
        // start up to it, clicking a clip kept frees it and the rest of its scene
        let keep = null;
        const thumbs = new Map();          // take id → <video>, kept between redraws
        const thumb = (id) => {
            if (thumbs.has(id)) return thumbs.get(id);
            const v = h("video", { muted: true, preload: "metadata", playsinline: true });
            v.muted = true;
            thumbs.set(id, v);
            if (tk() && tk().previewUrl) tk().previewUrl(id).then((url) => {
                if (!url) return;
                v.addEventListener("loadeddata", () => { v.currentTime = Math.min(0.5, (v.duration || 1) / 3); }, { once: true });
                v.src = url;
            });
            return v;
        };
        const ranges = (list) => {
            const out = [];
            for (const i of list) { const last = out[out.length - 1]; if (last && last[1] === i - 1) last[1] = i; else out.push([i, i]); }
            return out.map(([a, b]) => (a === b ? String(a) : `${a}→${b}`)).join(", ");
        };
        const draw = () => {
            const src = branches.find((b) => b.id === source) || {};
            const sel = twig.branch === source && twig.leaf ? twig : null;
            const chain = sel ? Object.keys(sel.takes || {}).map(Number).sort((a, b) => a - b) : [];
            const n = chain.length;
            const cont = (i) => i > 1 && !!(((sel && sel.plan && sel.plan.clips) || [])[i - 1] || {}).continue;
            if (keep === null) keep = new Set(chain);
            const sceneStart = (i) => { let a = i; while (a > 1 && cont(a)) a--; return a; };
            const sceneEnd = (i) => { let b = i; while (b < n && cont(b + 1)) b++; return b; };
            const toggle = (i) => {
                if (keep.has(i)) for (let j = i; j <= sceneEnd(i); j++) keep.delete(j);
                else for (let j = sceneStart(i); j <= i; j++) keep.add(j);
                how = "clips";
                draw();
            };
            const strip = h("div", { class: "br-pick" });
            for (const i of chain) {
                if (i > 1 && !cont(i)) strip.append(h("span", { class: "br-cut", title: _t("plan.new_scene_cut") }, "✂"));
                else if (i > 1) strip.append(h("span", { class: "br-link" }, "→"));
                const on = keep.has(i);
                strip.append(h("button", { class: `br-clip${on ? " on" : ""}`, "data-clip": i,
                    title: on ? _t("branch.clip_kept_title", { index: i }) : _t("branch.clip_free_title", { index: i }), onclick: () => toggle(i) },
                    thumb(sel.takes[i]), h("b", {}, String(i)), h("span", { class: "br-state" }, on ? "✓" : _t("branch.clip_free"))));
            }
            const kept = chain.filter((i) => keep.has(i)), free = chain.filter((i) => !keep.has(i) && i < Math.max(0, ...kept));
            const copyBox = h("div", { class: "br-sub" },
                choice("copy", _t("branch.without_clips"), _t("branch.without_clips_hint")),
                n
                    ? h("div", {}, choice("clips", _t("branch.with_clips"), _t("branch.with_clips_hint")),
                        h("div", { style: "margin-left:26px" }, strip,
                            h("div", { class: "tk-inline" },
                                h("button", { class: "small br-all", onclick: () => { keep = new Set(chain); how = "clips"; draw(); } }, _t("branch.keep_all")))))
                    : h("div", { class: "hint", style: "margin-left:26px" }, _t("branch.with_clips_needs_selection", { name: src.name || "?" })));
            const parts = [
                h("div", { class: "tk-inline" }, h("span", { class: "hint", style: "width:60px" }, _t("branch.name")), nameIn),
                ...(dup ? [copyBox] : [choice("empty", _t("branch.empty"), _t("branch.empty_hint")), choice("file", _t("branch.from_file"), _t("branch.from_file_hint"))]),
            ];
            if (how === "clips" && sel) {
                parts.push(h("div", { class: "hint br-summary", style: "margin-top:6px" }, kept.length
                    ? _t("branch.portions_summary", { kept: ranges(kept), n: kept.length }) : _t("branch.portions_none")));
                if (free.length) parts.push(h("div", { class: "hint br-free" }, _t("branch.portions_free", { free: ranges(free) })));
                if (kept.length) parts.push(h("div", { class: "hint" }, _t("branch.subjects_kept_by_clips")));
            }
            go.disabled = how === "clips" && (!sel || !kept.length);
            K().fill(body, parts);
        };
        const go = h("button", { class: "primary", onclick: async () => {
            const label = nameIn.value.trim();
            try {
                let res;
                if (how === "file") {
                    const [file] = await K().pickFiles(".json,application/json");
                    if (!file) return;
                    res = await K().api(`${K().base()}/branches?how=file&filename=${encodeURIComponent(file.name)}&name=${encodeURIComponent(label)}`,
                        { method: "POST", body: await file.arrayBuffer() });
                } else {
                    const payload = { how, name: label || null };
                    if (how === "copy" || how === "clips") payload.source = source;
                    if (how === "clips") {
                        const tw = S().twig.takes || {};
                        const kept = [...keep].sort((a, b) => a - b);
                        payload.leaf = tw[kept[kept.length - 1]];
                        payload.keep = kept;
                    }
                    res = await K().post(`${K().base()}/branches`, payload);
                }
                dlg.close();
                await K().saveIfDirty();
                K().applyProject(res.project);
                if (how === "empty" && !res.copied_from) await settings(res.branch.id, { first: true });
                if (tk()) tk().recompute();
                K().toast(_t("branch.created", { name: res.branch.name }));
            } catch (e) { alert(e.message); }
        } }, _t("branch.create"));
        draw();
        const title = dup ? _t("branch.duplicate_title", { name: (branches.find((b) => b.id === source) || {}).name || "?" }) : _t("branch.new_branch");
        const dlg = K().modal(title, h("div", {}, body, h("div", { class: "tk-inline", style: "justify-content:flex-end;margin-top:12px" }, go)));
    }

    // ------------------------------------------------------------------ « Réglages de la branche »
    async function settings(id, { first = false } = {}) {
        let data;
        try { data = await project(); } catch (e) { alert(e.message); return; }
        const state = (data.branch_states || {})[id] || { has_takes: false };
        const body = h("div", { class: "tk-refs br-settings" });
        let dlg = null;
        const draw = () => {
            const br = K().branchById(id);
            if (!br) return;
            const why = _t("branch.frozen_why", { name: br.name });
            const parts = [];
            if (first) parts.push(h("p", { class: "hint" }, _t("studio.choose_the_size_and_files_of")));
            if (state.has_takes) parts.push(h("p", { class: "hint" }, _t("branch.has_takes_banner")));
            // picture size (fixed by the takes) and reference size (a generation setting)
            const size = K().sizePicker(Number(br.width), Number(br.height), async (w, hh) => {
                try { await K().putBranch(id, { width: w, height: hh }); } catch (e) { alert(e.message); return false; }
                return true;
            });
            if (state.has_takes) size.querySelectorAll("input,select,button").forEach((el) => frozen(el, why));
            parts.push(h("h3", {}, _t("branch.picture")),
                h("div", { class: "tk-row" }, h("label", {}, _t("studio.picture_size")), h("div", { class: "br-size" }, size, state.has_takes ? lock(why) : null)),
                h("div", { class: "tk-row" }, h("label", {}, _t("studio.reference_size")), K().refSizePicker(br.ref_image_size || "max", async (value) => {
                    try { await K().putBranch(id, { ref_image_size: value }); } catch (e) { alert(e.message); return false; }
                    return true;
                })));
            // the segment of the project's video this branch uses: shown here, chosen in its master plan
            parts.push(h("h3", {}, _t("branch.video")), planSummary(id, state, why));
            parts.push(h("h3", {}, _t("branch.generation")), generationRows(id, br));
            parts.push(h("div", { class: "hint br-foot" }, _t("branch.other_values"), " ",
                h("button", { class: "small", onclick: () => { if (dlg) dlg.close(); create({ how: "copy", source: id, duplicate: true }); } }, _t("branch.duplicate"))));
            K().fill(body, parts);
        };
        draw();
        const br = K().branchById(id) || { name: id };
        return new Promise((resolve) => {
            dlg = K().modal(_t("branch.settings_of", { name: br.name }), body,
                { wide: true, onClose: () => { if (tk()) tk().render(); resolve(); } });
        });
    }

    function planSummary(id, state, why) {
        const box = h("div", { class: "br-plan" });
        K().api(`${K().base()}/plan?branch=${encodeURIComponent(id)}`).then((res) => {
            const p = res.plan || {};
            const sv = p.start_video || p.edit_video;
            const video = !sv ? _t("branch.no_video") : `${p.start_video ? _t("branch.start_video") : _t("branch.edited_video")} · ${Number(sv.start || 0).toFixed(1)}–${sv.end != null ? Number(sv.end).toFixed(1) : "…"} s`;
            const row = (label, value) => h("div", { class: "tk-row" }, h("label", {}, label), h("span", {}, value, state.has_takes ? lock(why) : null));
            const open = h("button", { class: "small", onclick: () => { document.querySelectorAll(".tk-modal").forEach((m) => m.remove()); K().openPlanScreen({ branch: id, leaf: null }); } },
                _t("branch.change_in_master_plan"));
            if (state.has_takes) frozen(open, why);
            K().fill(box, row(_t("branch.segment"), video), sv ? h("div", { class: "tk-row" }, h("label", {}), open) : null);
        }).catch((e) => K().fill(box, h("span", { class: "hint" }, e.message)));
        return box;
    }

    function generationRows(id, br) {
        const box = h("div", { class: "studio-upscale" });
        K().loraValues().then((values) => {
            const list = JSON.parse(JSON.stringify(br.loras || []));
            let timer = null;
            const save = () => { clearTimeout(timer); timer = setTimeout(() => K().putBranch(id, { loras: K().cleanList(list) }).catch((e) => K().toast(e.message)), 250); };
            const up = K().branchUpscale(br);
            const sum = up.enabled ? K().upscaleSummary(up, br) : null;
            K().fill(box, h("p", { class: "hint" }, _t("branch.generation_free"), " ", K().projectStackHint()),
                h("label", {}, _t("studio.extra_lora")), K().loraEditor(list, values, save),
                h("div", { class: "tk-inline", style: "margin-top:8px" }, h("span", {}, _t("studio.latent_upscale") + " : " + (!up.enabled ? _t("studio.upscale_off") : sum.error ? "⚠ " + sum.error : sum.text)),
                    h("button", { class: "small", onclick: () => K().openUpscale(id) }, _t("studio.modify"))));
        });
        return box;
    }

    // ------------------------------------------------------------------ the essence of the project (« Réglages du projet »)
    // mode, video (none, continue, edit), its file, the song, the context: the same for every branch, frozen by the
    // first take of the project
    function essenceBox() {
        const box = h("div", { class: "br-essence" });
        const draw = async () => {
            let data;
            try { data = await project(); } catch (e) { K().fill(box, h("p", { class: "hint" }, e.message)); return; }
            const ess = data.essence || {}, res = data.resources || S().resources || {};
            const music = ess.mode === "music_video";
            const locked = !!data.project_has_takes, why = _t("branch.project_frozen_why");
            const set = async (changes) => {
                try {
                    const pr = await K().put(`${K().base()}/essence`, changes);
                    S().resources = pr.resources || S().resources;
                    K().applyProject(pr);
                    if (document.body.classList.contains("planscreen") && S().editTarget) await K().openPlanScreen(S().editTarget);
                    if (tk()) tk().recompute();
                } catch (e) { alert(e.message); }
                draw();
            };
            const sel = (value, options, onchange) => {
                const el = h("select", { onchange: (e) => onchange(e.target.value) },
                    options.map(([v, label, dis]) => h("option", { value: v, selected: String(v) === String(value) || null, disabled: dis || null }, label)));
                return locked ? frozen(el, why) : el;
            };
            const importBtn = (folder, accept, key) => {
                const b = h("button", { onclick: async () => {
                    const [file] = await K().pickFiles(accept);
                    if (!file) return;
                    try { const [path] = await K().importFiles(folder, [file]); await set({ [key]: path }); } catch (e) { alert(e.message); }
                } }, _t("studio.import"));
                return locked ? frozen(b, why) : b;
            };
            const row = (label, ...kids) => h("div", { class: "tk-row" }, h("label", {}, label), h("div", { class: "tk-inline" }, ...kids, locked ? lock(why) : null));
            const ctxValues = music ? [5, 22, 39, 56, 73, 90] : H3.avContextValues();
            if (!ctxValues.includes(ess.context_frames)) ctxValues.push(ess.context_frames);
            K().fill(box,
                h("h3", {}, _t("branch.the_project")),
                h("p", { class: "hint" }, locked ? _t("branch.project_has_takes") : _t("branch.project_hint")),
                row(_t("plan.mode"), sel(ess.mode, [["music_video", _t("plan.music_video")], ["free", _t("plan.free_generated_sound")]], (v) => set({ mode: v }))),
                row(_t("branch.video"), sel(ess.video, [["none", _t("plan.video_none")], ["continue", _t("plan.video_continue")], ["edit", _t("plan.video_edit"), music]], (v) => set({ video: v }))),
                ess.video !== "none" ? row(_t("branch.video_file"),
                    sel(data.start_video_file || "", [["", _t("plan.start_video_choose")], ...(res.videos || []).map((v) => [v.path, v.name])], (v) => set({ video_file: v || null })),
                    importBtn("videos", K().ACCEPT.videos, "video_file")) : null,
                music ? row(_t("studio.song"),
                    sel(data.song || "", [["", _t("studio.none_3")], ...(res.songs || []).map((it) => [it.path, it.name])], (v) => set({ song: v })),
                    importBtn("songs", "audio/*", "song"),
                    data.song ? h("audio", { controls: true, src: K().fileUrl(data.song), style: "width:240px" }) : null) : null,
                row(_t("plan.context"), sel(ess.context_frames, ctxValues.map((v) => [v, _t("branch.frames", { n: v })]), (v) => set({ context_frames: Number(v) }))),
                h("p", { class: "hint" }, _t("branch.segment_in_branch")));
        };
        draw();
        return box;
    }

    window.H3Branch = { create, settings, essenceBox };
})();
