// ---------------------------------------------------------------------------------------------
// Encore - "Takes" tab: the takes of every clip, one band per branch, as a dependency graph.
// Encore's server holds the takes and drives ComfyUI: this tab only asks it (see useStudio).
// ---------------------------------------------------------------------------------------------
(() => {
    const COLW = 196, GAP = 70, CARD_H = 158, TOP = 54, LEFT = 16;
    const T = {
        takes: {}, fileSelection: {}, pick: {}, fingerprints: null, resolved: null, soundOnHover: false, loading: false,
        server: null, settings: null, jobs: [], previewInfo: {}, planFile: null, socketOpen: false, error: null,
        studio: null, seenDone: new Set(),          // studio: Encore's API, given by useStudio()
    };
    const ed = () => window.H3Editor;
    const plan = () => ed().state.plan;
    const $ = (id) => document.getElementById(id);
    function h(tag, attrs = {}, ...kids) {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v === undefined || v === null || v === false) continue;
            if (k === "class") node.className = v;
            else if (k === "style") node.style.cssText = v;
            else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
            else node.setAttribute(k, v === true ? "" : v);
        }
        for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid instanceof Node ? kid : String(kid));
        return node;
    }
    const toast = (t) => ed().toast(t);
    function when(seconds) {
        if (!seconds) return "";
        const d = new Date(seconds * 1000), p = (n) => String(n).padStart(2, "0");
        return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }
    const rescan = () => serverScan();


    async function recompute() {
        T.fingerprints = null;
        T.resolved = null;
        if (plan() && H3.framesLegal(plan())) {
            T.fingerprints = await H3.takeFingerprints(plan());
            T.resolved = resolveWith(T.pick);
        }
        renderTakes();
    }

    // Encore's rules (nothing deleted: takes are "invalid", see plan_core.js)
    function resolveWith(pick) {
        const resolve = (sel, branch) => H3.studioResolveTakes(plan(), T.takes, { ...sel, branch: branch || null }, T.fingerprints, T.studio.current());
        const res = resolve(pick, T.pickBranch);
        if (!res.branch || !isFolded(res.branch)) return res;
        // a folded branch never holds the selection: it goes to an unfolded branch, chosen like the resolver
        // does (the branch of the latest valid take of clip 1, else the first branch having takes)
        const open = new Set(branchesList().filter((b) => !isFolded(b.id)).map((b) => b.id));
        const clip1 = [...(T.takes[1] || [])].sort((a, b) => (a.saved_at || 0) - (b.saved_at || 0))
            .filter((r) => open.has(branchOfRecord(r)) && res[1]?.takes?.[r.id]?.[0] !== "invalid");
        let target = clip1.length ? branchOfRecord(clip1[clip1.length - 1]) : null;
        if (!target) target = [...open].sort().find((b) => Object.values(T.takes || {}).flat().some((r) => branchOfRecord(r) === b)) || null;
        if (!target) return res;      // no unfolded branch has takes yet: nothing to move to
        T.pickBranch = target;
        T.pick = {};
        if (T.fileSelection) setTimeout(studioSaveSelection, 0);   // once T.resolved holds the new result
        return resolve({}, target);
    }
    const unusable = (state) => state === "stale" || state === "invalid";
    function chosenMap() {
        const out = {};
        if (!T.resolved) return out;
        for (const [i, v] of Object.entries(T.resolved)) if (v.chosen) out[+i] = v.chosen;
        return out;
    }

    // ------------------------------------------------------------------ choosing
    function recordOf(index, id) { return (T.takes[index] || []).find((r) => r.id === id); }
    function recordAny(id) { for (const list of Object.values(T.takes)) for (const r of list) if (r.id === id) return r; return null; }
    const hasPreview = (id) => !!T.previewInfo[id];
    function choose(index, id, quiet) {
        const state = T.resolved?.[index]?.takes?.[id];
        if (!state) return;
        if (unusable(state[0])) { if (!quiet) toast(`${state[0] === "invalid" ? _t("takes.invalidated_take") : _t("takes.out_of_date_take")} : ${state[1]}`); return; }
        let pick = chosenMap();
        const b = branchOfRecord(recordOf(index, id));
        if (b !== T.resolved?.branch) pick = {};
        T.pickBranch = b;
        pick[index] = id;
        let i = index, record = recordOf(index, id);
        while (i > 1 && plan().clips[i - 1].continue && record && record.parent) {
            pick[i - 1] = record.parent;
            record = recordOf(i - 1, record.parent);
            i--;
        }
        T.pick = pick;
        T.resolved = resolveWith(T.pick);
        studioSaveSelection();
        renderTakes();
    }


    // ------------------------------------------------------------------ video helpers
    async function previewUrl(id) {
        const p = T.previewInfo[id];
        return p ? T.server.viewUrl(`${p.subfolder}/${p.filename}`, p.type || "output") + `&v=${Math.round((recordAny(id)?.saved_at || 0) * 1000)}` : null;
    }
    // thumbnails survive a redraw of the tab (choosing a take, switching branch…): the same <video>
    // element is moved into the new card instead of loading the file again (no flicker)
    function thumbVideo(key, make) {
        if (!T.thumbs) T.thumbs = new Map();
        let v = T.thumbs.get(key);
        if (!v) { v = make(); T.thumbs.set(key, v); }
        return v;
    }
    async function attachThumb(video, id) {
        const url = await previewUrl(id);
        if (!url) return;
        video.src = url;
        video.addEventListener("loadeddata", () => { if (video.paused) video.currentTime = Math.min(0.5, (video.duration || 1) / 3); }, { once: true });
    }
    function modelsText(m, record) {
        const loras = (m.loras || []).map((l) => `${l.name.replace(/\.safetensors$/, "")} (${l.strength})`).join(", ") || _t("takes.none");
        return _t("takes.lora_steps", { width: record.width, height: record.height, v2: m.unet_name || "?", loras, v4: m.sampler_name || "?", v5: m.scheduler || "?", v6: m.steps ?? "?" });
    }
    function openViewer(index, id) {
        const clip = plan().clips[index - 1];
        const record = recordOf(index, id) || {};
        const state = T.resolved?.[index]?.takes?.[id] || ["?", ""];
        const video = h("video", { controls: true, autoplay: true, style: "width:100%;max-height:62vh;background:#000;border-radius:6px" });
        previewUrl(id).then((url) => { if (url) video.src = url; });
        const labels = { ok: _t("takes.usable"), other: _t("takes.built_on_another_take_of_the"), stale: _t("takes.out_of_date"), invalid: _t("takes.invalidated") };
        const close = () => { video.pause(); overlay.remove(); document.removeEventListener("keydown", onKey); };
        const onKey = (e) => { if (e.key === "Escape") close(); };
        const overlay = h("div", { class: "tk-modal", onclick: (e) => { if (e.target === overlay) close(); } },
            h("div", { class: "tk-box" },
                h("div", { class: "tk-box-head" },
                    h("b", {}, _t("takes.clip", { index, name: clip.name })),
                    h("span", { class: "hint" }, _t("takes.take_seed", { id, seed: record.seed, v2: when(record.saved_at), v3: labels[state[0]] || state[0], v4: state[1] ? " — " + state[1] : "" })),
                    h("span", { style: "flex:1" }),
                    h("button", { class: "primary", disabled: unusable(state[0]) || T.resolved?.[index]?.chosen === id,
                        onclick: () => { choose(index, id); close(); } }, _t("takes.choose_this_take")),
                    h("button", { onclick: close }, _t("takes.close"))),
                record.studio && record.studio.models ? h("div", { class: "hint tk-models" }, modelsText(record.studio.models, record)) : null,
                hasPreview(id) ? video : h("div", { class: "empty" }, _t("takes.no_preview_for_this_take"))));
        document.body.append(overlay);
        document.addEventListener("keydown", onKey);
    }

    // ------------------------------------------------------------------ takes and settings from Encore




    function loadSettings() { T.settings = T.studio.settings(); T.settingsProject = plan().project; }

    async function serverScan() {
        T.loading = true;
        T.error = null;
        renderTakes();
        try {
            if (!T.settings || T.settingsProject !== plan().project) loadSettings();
            const listing = await T.server.takes(T.planFile);
            try { T.exports = (await T.studio.exports()).exports || []; } catch (_) { T.exports = T.exports || []; }
            const takes = {}, previews = {}, selection = {};
            for (const clip of listing.clips) {
                takes[clip.index] = clip.takes.map((t) => ({ ...(t.record || {}), id: t.id }));
                for (const t of clip.takes) if (t.preview) previews[t.id] = t.preview;
                if (clip.selected) selection[clip.index] = clip.selected;
            }
            const firstLoad = T.takesProject !== plan().project;
            T.takes = takes;
            T.previewInfo = previews;
            T.fileSelection = selection;
            if (firstLoad) { T.pick = { ...selection }; T.pickBranch = listing.selection_branch || null; T.takesProject = plan().project; }
            // takes produced by finished jobs: drop their ghost and choose them (the newest take is chosen, like in the plugin)
            const fresh = [];
            for (const job of T.jobs) {
                if (job.kind !== "clip" || job.status !== "done") continue;
                const take = (takes[job.clip] || []).find((r) => r.id.endsWith("_" + job.token));
                if (take) { job.realized = take.id; fresh.push(job); }
            }
            T.jobs = T.jobs.filter((j) => !j.realized);
            T.loading = false;
            await recompute();
            for (const job of fresh) choose(job.clip, job.realized, true);
        } catch (e) {
            T.loading = false;
            T.error = e.message;
            renderTakes();
        }
    }

    // --------------------------------------------------------------- generation
    function tokenOf(id) { return String(id).split("_").pop(); }
    function jobsOf(clip) { return T.jobs.filter((j) => j.kind === "clip" && j.clip === clip); }

    async function generate(clipIndex, { parentToken = null, random = false, seed: forcedSeed = null, branch = null, upscale = null, loras = null, upscaleSettings = null } = {}) {
        try {
            const clip = plan().clips[clipIndex - 1];
            await T.studio.savePlan();
            const job = await T.studio.generate(clipIndex, clip.continue ? parentToken : null, random, forcedSeed, branch, upscale, loras, upscaleSettings);
            if (!T.jobs.some((j) => j.id === job.id)) T.jobs.push(job);
            studioPollSoon(300);
            renderTakes();
        } catch (e) {
            alert(_t("takes.cannot_start_the_generation", { v0: e.message }));
        }
    }


    async function assemble(leafClip, leafId) {
        try {
            await T.studio.savePlan();
            const job = await T.studio.assemble(leafClip, leafId);
            if (!T.jobs.some((j) => j.id === job.id)) T.jobs.push(job);
            studioPollSoon(300);
            renderTakes();
        } catch (e) {
            alert(_t("takes.cannot_start_the_assembly", { v0: e.message }));
        }
    }

    async function stopAll() {
        const mine = T.jobs.filter((j) => j.status === "queued" || j.status === "running");
        if (!mine.length) return;
        if (!await H3Dialog.confirm(_t("takes.stop_the_running_generation_and_remove", { v0: mine.length - 1 > 0 ? mine.length - 1 + _t("takes.waiting_job_s") : _t("takes.the_waiting_jobs") }))) return;
        try { applyStudioJobs(await T.studio.cancel(mine.map((j) => j.id))); } catch (e) { alert(e.message); }
        renderTakes();
    }

    // --------------------------------------------------------------- progress
    function updateGhost(job) {
        const node = document.querySelector(`[data-job="${job.id}"]`);
        if (!node && job.kind === "assemble") {   // side pane folded: only the label of the top bar changes
            const a = document.getElementById("tkAssembleState");
            if (a) a.textContent = ghostLabel(job);
            return;
        }
        if (!node) { renderTakes(); return; }
        if (job.preview) {             // live preview sent by ComfyUI during sampling
            const el = node.querySelector(".tk-live");
            if (!el || el.dataset.kind !== liveKind(job)) { renderTakes(); return; }
            refreshLive(el, job);
        }
        if (T.live && T.live.job.id === job.id) {
            const el = T.live.box.querySelector(".tk-live");
            if (job.preview && (!el || el.dataset.kind !== liveKind(job))) el ? el.replaceWith(liveElement(job, true)) : T.live.box.append(liveElement(job, true));
            else if (el) refreshLive(el, job);
            T.live.label.textContent = ` ${ghostLabel(job)}`;
        }
        const bar = node.querySelector(".tk-progress i");
        const label = node.querySelector(".tk-ghost-label");
        if (bar && job.progress) bar.style.width = `${Math.round(100 * job.progress.value / Math.max(1, job.progress.max))}%`;
        if (label) label.textContent = ghostLabel(job);
        if (job.kind === "assemble") { const a = document.getElementById("tkAssembleState"); if (a) a.textContent = ghostLabel(job); }
    }
    // live preview: a picture, or a short video (KJNodes, animated, maybe with sound)
    const liveKind = (job) => (String(job.previewMime || "").startsWith("video/") ? "video" : "img");
    function liveElement(job, big) {
        const kind = liveKind(job), src = T.studio.previewUrl(job.id, job.preview);
        const el = kind === "video"
            ? h("video", { class: "tk-live", src, autoplay: true, loop: true, muted: true, playsinline: true, controls: big || null })
            : h("img", { class: "tk-live", src });
        if (kind === "video") { el.muted = !big; el.play().catch(() => { el.muted = true; el.play().catch(() => {}); }); }
        el.dataset.kind = kind;
        el.dataset.seq = String(job.preview);
        if (big) el.style.cssText = "width:100%;max-height:62vh;background:#000;border-radius:6px;object-fit:contain";
        return el;
    }
    function refreshLive(el, job) {
        if (el.dataset.seq === String(job.preview)) return;
        el.dataset.seq = String(job.preview);
        el.src = T.studio.previewUrl(job.id, job.preview);
        if (el.tagName === "VIDEO") el.play().catch(() => {});
    }
    function openLive(job) {
        const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); T.live = null; };
        const onKey = (e) => { if (e.key === "Escape") close(); };
        const label = h("span", { class: "hint" }, ` ${ghostLabel(job)}`);
        const box = h("div", {}, liveElement(job, true));
        const overlay = h("div", { class: "tk-modal", onclick: (e) => { if (e.target === overlay) close(); } },
            h("div", { class: "tk-box" },
                h("div", { class: "tk-box-head" }, h("b", {}, _t("takes.clip_generating", { clip: job.clip })), label,
                    h("span", { style: "flex:1" }), h("button", { onclick: close }, _t("takes.close"))),
                box, h("div", { class: "hint", style: "margin-top:6px" }, _t("takes.preview_sent_by_comfyui_at_each"))));
        document.body.append(overlay);
        document.addEventListener("keydown", onKey);
        T.live = { job, box, label };
    }
    function duration(sec) {
        sec = Math.max(0, Math.round(sec));
        if (sec < 60) return `${sec} s`;
        const m = Math.floor(sec / 60), r = sec % 60;
        if (m < 60) return `${m} min${r ? " " + String(r).padStart(2, "0") : ""}`;
        return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
    }
    // length of a clip, from its number of frames (24 per second)
    function clipLength(frames) {
        if (!frames) return "";
        const sec = frames / 24;
        return sec < 60 ? `${sec.toFixed(1).replace(".", H3I18n.decimal())} s` : `${Math.floor(sec / 60)} min ${String(Math.round(sec % 60)).padStart(2, "0")}`;
    }
    function ghostLabel(job) {
        if (job.status === "queued" && job.suspended) return _t("takes.suspended_queue_manager");
        if (job.status === "queued" && !job.dispatched && T.queuePaused) return _t("takes.queue_paused");
        if (job.status === "queued" && job.comfy_ahead) return _t("takes.waits_behind_comfy", { n: job.comfy_ahead });
        if (job.status === "queued" && job.start_in != null && job.at_least) return _t("takes.waiting") + _t("takes.start_at_least", { v0: duration(job.start_in) });
        if (job.status === "queued") return _t("takes.waiting") + (job.start_in == null ? "" : job.start_in < 5 ? _t("takes.starting_soon") : _t("takes.start_2", { v0: duration(job.start_in) }));
        if (job.status === "error") return "✖ " + (job.error || _t("takes.error"));
        if (job.status === "done") return _t("takes.finished");
        const p = job.progress ? ` ${job.progress.value}/${job.progress.max}` : "";
        return `▶ ${job.step || _t("takes.preparing")}${p}` + (job.eta != null ? _t("takes.left", { time: duration(job.eta) }) : "");
    }


    // --------------------------------------------------------------- plan of a clip, plan a take was made with
    const SECTION_NAMES = () => H3.SECTIONS.map((s) => s.replace(/:$/, ""));
    function promptParts(prompt) {
        const parts = H3.parseSections(prompt || "");
        return parts ? SECTION_NAMES().map((name, k) => [name, parts[k]]) : [[null, String(prompt || "")]];
    }
    // word diff (longest common subsequence on words and spaces): [[op, text]] with op "=", "-" or "+"
    function wordDiff(a, b) {
        const x = String(a || "").split(/(\s+)/).filter((w) => w !== ""), y = String(b || "").split(/(\s+)/).filter((w) => w !== "");
        if (x.length * y.length > 4e6) return [["-", a], ["+", b]];
        const m = x.length, n = y.length;
        const L = Array.from({ length: m + 1 }, () => new Uint32Array(n + 1));
        for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
        const out = [];
        const push = (op, t) => { if (out.length && out[out.length - 1][0] === op) out[out.length - 1][1] += t; else out.push([op, t]); };
        let i = 0, j = 0;
        while (i < m && j < n) {
            if (x[i] === y[j]) { push("=", x[i]); i++; j++; }
            else if (L[i + 1][j] >= L[i][j + 1]) push("-", x[i++]);
            else push("+", y[j++]);
        }
        while (i < m) push("-", x[i++]);
        while (j < n) push("+", y[j++]);
        return out;
    }
    function diffNode(ops) {
        return h("div", { class: "tk-plan-text" }, ops.map(([op, t]) => op === "=" ? t
            : h(op === "-" ? "del" : "ins", { class: op === "-" ? "tk-diff-del" : "tk-diff-ins" }, t)));
    }
    function framesText(frames) { return frames ? `${frames} ${_t("takes.plan_frames")} (${clipLength(frames)})` : "—"; }
    function continueText(entry, index) {
        return index === 1 ? _t("takes.plan_first_clip") : entry && entry.continue ? _t("takes.plan_continues", { clip: index - 1 }) : _t("takes.plan_new_scene");
    }
    function linesText(entry, free) {
        if (!entry) return "";
        if (free) return (entry.dialogue || []).map((d) => `${d.speaker || "?"}${d.language ? ` [${d.language}]` : ""} : ${d.text || ""}`).join("\n");
        return entry.lyrics || "";
    }
    function refThumb(url, name) {
        return url ? zoomable(h("img", { class: "tk-plan-ref", src: url }), name) : h("div", { class: "tk-plan-ref empty" }, _t("takes.no_picture"));
    }
    function planRow(label, ...value) { return h("div", { class: "tk-plan-row" }, h("label", {}, label), h("div", {}, ...value)); }
    function sectionBlocks(prompt) {
        return promptParts(prompt).map(([name, text]) => h("div", { class: "tk-plan-sec" },
            name ? h("div", { class: "tk-plan-sec-name" }, name + ":") : null, h("div", { class: "tk-plan-text" }, text || "—")));
    }
    // everything a generation used (a take, a generation in the queue) or would use now (a « generate » box): the
    // « Generation » block of the plan windows
    function generationBlock(gen, { seed, size, title }) {
        if (!gen) return null;
        const m = gen.models || {};
        const fmt = (list) => (list && list.length ? T.studio.fmtLoras(list) : _t("takes.none"));
        const up = gen.upscale;
        return h("div", { class: "tk-plan-gen" },
            h("div", { class: "tk-plan-sec-name" }, title),
            seed !== undefined ? planRow(_t("takes.gen_seed"), seed ?? _t("takes.gen_seed_random")) : null,
            size && size[0] ? planRow(_t("takes.gen_size"), `${size[0]} × ${size[1]}` + (gen.ref_image_size ? ` · ${_t("takes.gen_ref_size")} ${gen.ref_image_size}` : "")) : null,
            planRow(_t("takes.gen_model"), `${m.unet_name || "—"}${m.weight_dtype ? ` (${m.weight_dtype})` : ""}`),
            planRow(_t("takes.gen_text_encoder"), m.clip_name || "—"),
            planRow(_t("takes.gen_vae"), `${m.video_vae || "—"} · ${m.audio_vae || "—"}`),
            planRow(_t("takes.gen_sampling"), `${m.sampler_name || "—"} / ${m.scheduler || "—"} · ${m.steps ?? "—"} ${_t("takes.gen_steps")} · SigmaShift ${m.shift_video ?? "—"} / ${m.shift_audio ?? "—"}`
                + (m.attention ? ` · ${m.attention}` : "")),
            planRow(_t("takes.gen_project_lora"), fmt(m.loras)),
            planRow(_t("takes.gen_extra_lora"), fmt(gen.extra_loras)),
            planRow(_t("takes.gen_upscale"), up ? up.summary + (up.source ? ` (${_t("takes.upscale_from_" + up.source)})` : "") : _t("takes.no")),
            gen.song ? planRow(_t("takes.gen_song"), String(gen.song).split("/").pop()) : null);
    }
    // read-only: the clip as it is in the plan now (from the header of its column)
    function openClipPlan(index, branchId) {
        const p = plan();
        const clip = (p.clips || [])[index - 1];
        if (!clip) return;
        const free = H3.mode(p) === "free";
        const row = (H3.framesLegal(p) ? H3.timeline(p) : [])[index - 1] || {};
        const br = branchesList().find((b) => b.id === (branchId || T.resolved?.branch || defBranch())) || null;
        const refs = (clip.refs || []).map((name, k) => h("div", { class: "tk-plan-refcell" },
            br ? refThumb(((br.refs || {})[name] || {}).image ? T.studio.viewUrl(br.refs[name].image) : null, name) : null,
            h("div", {}, h("b", {}, name), h("span", { class: "hint" }, ` <Picture ${k + 1}>`)),
            h("div", { class: "hint" }, (p.refs || {})[name] || "")));
        const lines = linesText(clip, free);
        const body = h("div", { class: "tk-plan" },
            planRow(_t("takes.plan_name"), h("b", {}, `${index}. ${clip.name || ""}`)),
            planRow(_t("takes.plan_length"), framesText(clip.frames)),
            planRow(_t("takes.plan_link"), continueText(clip, index)),
            row.end ? planRow(_t("takes.plan_in_video"), `${clipLength(index > 1 ? row.visible : 0) || "0"} → ${clipLength(row.end)}`) : null,
            planRow(_t("takes.plan_refs"), refs.length ? h("div", { class: "tk-plan-refs" }, refs) : "—"),
            br ? h("div", { class: "hint", style: "margin:-4px 0 6px 130px" }, _t("takes.plan_refs_of_branch", { name: br.name })) : null,
            planRow(free ? _t("takes.plan_lines") : _t("takes.plan_lyrics"), h("div", { class: "tk-plan-text" }, lines || "—")),
            h("div", { class: "tk-plan-prompt" }, sectionBlocks(clip.prompt)),
            br ? generationBlock(T.studio.generationNow(br.id, index), { size: T.studio.generationNow(br.id, index).size,
                title: _t("takes.gen_now_in_branch", { name: br.name }) }) : null);
        modal(_t("takes.plan_of_clip", { index, name: clip.name || "" }), body).overlay.classList.add("tk-plan-modal");
    }
    // read-only: the plan a take was made with, and what changed since
    // a generation still queued or running: the plan it was launched with, compared with the plan now
    async function openJobPlan(job) {
        let info;
        try { info = await T.studio.jobPlan(job.id); } catch (e) { alert(e.message); return; }
        showPlanWindow(job.clip, info, _t("takes.plan_of_job", { index: job.clip }), `${_t("takes.plan_seed")} ${info.seed ?? "—"} · ${info.size[0]} × ${info.size[1]}`);
    }
    async function openTakePlan(index, record) {
        let info;
        try { info = await T.studio.takePlan(index, record.id); } catch (e) { alert(e.message); return; }
        showPlanWindow(index, info, _t("takes.plan_of_take", { index, id: record.id }),
            `${record.id} · ${_t("takes.plan_seed")} ${info.seed ?? "—"} · ${when(info.saved_at)} · ${info.size[0]} × ${info.size[1]}`);
    }
    function showPlanWindow(index, info, title, head) {
        const p = plan();
        const free = H3.mode(p) === "free";
        const then = info.snapshot, now = info.current;
        const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
        const cmpRow = (label, a, b, fmt = (v) => v ?? "—") => {
            const diff = then && !same(a, b);
            return h("div", { class: `tk-plan-row${diff ? " changed" : ""}` }, h("label", {}, label),
                h("div", {}, then ? fmt(a) : "—", diff ? h("div", { class: "tk-plan-now" }, _t("takes.plan_now"), fmt(b)) : null));
        };
        const source = !then ? _t("takes.plan_source_unknown")
            : info.source === "record" ? _t("takes.plan_source_record")
            : info.source === "current" ? _t("takes.plan_source_current")
            : info.source === "previous" ? _t("takes.plan_source_previous")
            : info.source === "job" ? _t("takes.plan_source_job")
            : info.source.startsWith("checkpoint:") ? _t("takes.plan_source_checkpoint", { name: info.source.slice(11) })
            : _t("takes.plan_source_export", { name: info.source.slice(7) });
        const fullSame = then && now && same(then.prompt, now.prompt) && same(then.frames, now.frames) && same(!!then.continue, !!now.continue)
            && same(then.refs || [], now.refs || []) && same(linesText(then, free), linesText(now, free));
        // references: the files the take was made with, against those of its branch now
        const refCells = Object.entries(info.refs || {}).filter(([name]) => (then ? then.refs || [] : []).includes(name) || (now && (now.refs || []).includes(name)))
            .map(([name, kinds]) => {
                const img = kinds.image || {}, a = img.then, b = img.now;
                const moved = a && b ? a.file !== b.file : !!a !== !!b;
                const edited = a && !a.same;
                const state = moved ? _t("takes.plan_ref_other_file") : edited ? _t("takes.plan_ref_file_changed") : "";
                const voice = free && kinds.voice && (kinds.voice.then || kinds.voice.now) ? h("div", { class: "hint" }, "🎙 "
                    + ((kinds.voice.then || {}).file || "—") + ((kinds.voice.then || {}).file !== (kinds.voice.now || {}).file ? " → " + ((kinds.voice.now || {}).file || "—") : "")) : null;
                return h("div", { class: `tk-plan-refcell${state ? " changed" : ""}` },
                    h("div", { class: "tk-plan-refpair" },
                        refThumb(a && a.exists && a.same ? T.studio.viewUrl(a.file) : null, `${name} (${_t("takes.plan_then")})`),
                        state ? h("span", { class: "tk-plan-arrow" }, "→") : null,
                        state ? refThumb(b && b.exists ? T.studio.viewUrl(b.file) : null, `${name} (${_t("takes.plan_now_short")})`) : null),
                    h("div", {}, h("b", {}, name)), a ? h("div", { class: "hint" }, a.file.split("/").pop()) : null,
                    state ? h("div", { class: "tk-plan-warn" }, state) : null, voice);
            });
        const prompt = !then ? sectionBlocks(now && now.prompt)
            : (() => {
                const A = promptParts(then.prompt), B = promptParts(now ? now.prompt : "");
                if (A.length !== B.length || A.some(([n], k) => n !== B[k][0])) return [diffNode(wordDiff(then.prompt, now ? now.prompt : ""))];
                return A.map(([name, text], k) => {
                    const diff = text !== B[k][1];
                    return h("div", { class: `tk-plan-sec${diff ? " changed" : ""}` },
                        name ? h("div", { class: "tk-plan-sec-name" }, name + ":" + (diff ? " " + _t("takes.plan_modified") : "")) : null,
                        diff ? diffNode(wordDiff(text, B[k][1])) : h("div", { class: "tk-plan-text" }, text || "—"));
                });
            })();
        const shift = !free && info.raw_start != null && info.now_raw_start != null && info.raw_start !== info.now_raw_start;
        const body = h("div", { class: "tk-plan" },
            h("div", { class: "hint", style: "margin-bottom:8px" }, head),
            h("div", { class: `tk-plan-banner${then && !fullSame ? " changed" : ""}` }, source,
                then ? " " + (fullSame ? _t("takes.plan_identical") : _t("takes.plan_differs")) : ""),
            cmpRow(_t("takes.plan_name"), then && then.name, now && now.name),
            cmpRow(_t("takes.plan_length"), then && then.frames, now && now.frames, framesText),
            cmpRow(_t("takes.plan_link"), then && !!then.continue, now && !!now.continue, (v) => continueText({ continue: v }, index)),
            shift ? h("div", { class: "tk-plan-row changed" }, h("label", {}, _t("takes.plan_song_window")),
                h("div", {}, _t("takes.plan_song_shift", { then: clipLength(info.raw_start) || "0", now: clipLength(info.now_raw_start) || "0" }))) : null,
            cmpRow(_t("takes.plan_refs"), then && (then.refs || []), now && (now.refs || []), (v) => (v || []).join(", ") || "—"),
            refCells.length ? h("div", { class: "tk-plan-refs", style: "margin:0 0 8px 130px" }, refCells) : null,
            cmpRow(free ? _t("takes.plan_lines") : _t("takes.plan_lyrics"), linesText(then, free), linesText(now, free), (v) => h("div", { class: "tk-plan-text" }, v || "—")),
            h("div", { class: "tk-plan-prompt" }, prompt),
            info.generation ? generationBlock({ ...info.generation, upscale: info.upscale }, { seed: info.seed, size: info.size, title: _t("takes.gen_used") }) : null,
            then && !fullSame ? h("div", { class: "hint", style: "margin-top:6px" }, h("del", { class: "tk-diff-del" }, _t("takes.plan_legend_then")), " ",
                h("ins", { class: "tk-diff-ins" }, _t("takes.plan_legend_now"))) : null);
        modal(title, body).overlay.classList.add("tk-plan-modal");
    }
    // ≡: on a take (the plan it was made with), on a queued or running generation (the plan it was launched with),
    // on a « generate » box or a column header (the plan of the clip now, read only)
    function planButton(index, record, { job = null, branch = null } = {}) {
        const open = () => (record ? openTakePlan(index, record) : job ? openJobPlan(job) : openClipPlan(index, branch));
        return h("button", { class: record || job || branch ? "small tk-plan-btn" : "small tk-clipplan",
            title: record ? _t("takes.plan_of_take_title") : job ? _t("takes.plan_of_job_title") : _t("takes.plan_of_clip_title"),
            onclick: (e) => { e.stopPropagation(); open(); }, ondblclick: (e) => e.stopPropagation() }, "≡");
    }

    // --------------------------------------------------------------- settings and references dialogs
    function modal(title, body, onClose) {
        const close = () => { overlay.remove(); onClose && onClose(); };
        const overlay = h("div", { class: "tk-modal", onclick: (e) => { if (e.target === overlay) close(); } },
            h("div", { class: "tk-box tk-form" }, h("div", { class: "tk-box-head" }, h("b", {}, title), h("span", { style: "flex:1" }), h("button", { onclick: close }, _t("takes.close"))), body));
        document.body.append(overlay);
        return { overlay, close };
    }






    // ------------------------------------------------------------------ rendering
    function renderTakes() {
        hideZoom();
        const box = $("takesView");
        if (!box || box.hidden) return;
        box.innerHTML = "";
        const p = plan();
        keepOneUnfolded();
        // a resolution computed for another plan (another number of clips) is useless
        if (T.resolved && !p.clips.every((_c, k) => T.resolved[k + 1])) T.resolved = null;
        const nTakes = Object.values(T.takes).reduce((a, l) => a + l.length, 0);
        const active = T.jobs.filter((j) => j.status === "queued" || j.status === "running");
        const bar = h("div", { class: "tk-bar" },
            h("button", { onclick: rescan }, _t("takes.refresh")),
            h("label", { class: "tk-check" }, h("input", { type: "checkbox", checked: T.soundOnHover || null, onchange: (e) => { T.soundOnHover = e.target.checked; } }), _t("takes.sound_on_hover")),
            h("span", { class: "tk-status" }, statusText(nTakes)),
            h("span", { style: "flex:1" }),
            active.length ? h("span", { class: "tk-queue" }, [
                active.some((j) => j.status === "running") ? _t("takes.1_running") : null,
                active.some((j) => j.status === "queued") ? _t("takes.waiting_2", { length: active.filter((j) => j.status === "queued").length }) : null,
            ].filter(Boolean).join(" · ")) : null,
            // one « ▶ assembler » button per leaf of the tree, on its card
            h("button", { class: "danger", onclick: stopAll, disabled: !active.length }, _t("takes.stop")));
        box.append(bar);
        if (T.error) { box.append(h("div", { class: "empty" }, h("p", {}, _t("takes.error_2", { error: T.error })), h("button", { onclick: rescan }, _t("takes.try_again")))); return; }
        if (T.loading && !T.resolved) { box.append(h("div", { class: "empty" }, _t("takes.reading_the_takes"))); return; }
        if (!T.resolved) { box.append(h("div", { class: "empty" }, _t("takes.the_plan_has_an_invalid_clip"))); return; }
        box.append(h("div", { class: "tk-legend" },
            h("span", {}, h("i", { class: "lg chosen" }), _t("takes.chosen_take")),
            h("span", {}, h("i", { class: "lg" }), _t("takes.usable")),
            h("span", {}, h("i", { class: "lg other" }), _t("takes.built_on_another_take_of_the")),
            h("span", {}, h("i", { class: "lg invalid" }), _t("takes.invalidated_redo")),
            h("span", {}, _t("takes.click_choose_used_to_assemble_before") + _t("takes.hover_play_double_click_larger_preview") + _t("takes.new_take_of_the_clip_box"))));

        if (!branchesList().length) {
            box.append(h("div", { class: "tk-area" }, h("div", { class: "empty", style: "flex:1" },
                h("button", { class: "primary tk-newbranch-big", onclick: newBranch }, _t("takes.new_branch")),
                h("p", { class: "hint" }, _t("takes.a_branch_starts_at_clip_1"))),
                videoPane(p)));
            return;
        }
        box.append(viewBar());
        const graph = buildBands(p);
        const viewport = h("div", { class: "tk-viewport" });
        const canvas = h("div", { class: "tk-canvas", style: `width:${graph.width}px;height:${graph.height}px` });
        const svgNS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(svgNS, "svg");
        svg.setAttribute("width", graph.width);
        svg.setAttribute("height", graph.height);
        svg.classList.add("tk-svg");
        canvas.append(svg);
        const n = p.clips.length;
        // frozen panes. The clip names live in their own layer, kept on top by the browser itself (position: sticky):
        // vertical scrolling is done by the browser, a script would follow it one frame late. The branch column moves
        // with the horizontal scroll, which only the Studio's own code does (drag, minimap): stickPanes follows it at once.
        const leftW = LEFT + HEADW + 10;
        const top = h("div", { class: "tk-topcanvas", style: `width:${graph.width}px;height:${TOP - 6}px` });
        canvas.append(h("div", { class: "tk-pane-left tk-stick-x", style: `width:${leftW}px;height:${graph.height}px` }));
        top.append(h("div", { class: "tk-pane-top", style: `width:${graph.width}px;height:${TOP - 6}px` }));
        for (const band of graph.bands) {
            canvas.append(h("div", { class: `tk-band${band.folded ? " folded" : ""}`, style: `top:${band.y - (band.folded ? 2 : 8)}px;height:${band.h + (band.folded ? 4 : 16)}px;width:${graph.width - 8}px;border-left-color:${band.branch.color}` }));
            canvas.append(bandHeader(band, p));
        }
        canvas.append(h("button", { class: "tk-newbranch tk-stick-x", style: `left:${LEFT}px;top:${graph.newBranchY}px;width:${HEADW}px`, onclick: newBranch }, _t("takes.new_branch")));
        for (let index = 1; index <= n; index++) {
            const clip = p.clips[index - 1];
            const res = T.resolved[index];
            const count = (T.takes[index] || []).length;
            top.append(h("div", { class: "tk-col-head", style: `left:${colX(index)}px;width:${COLW}px` },
                h("div", { class: "tk-col-name" }, planButton(index), h("b", {}, `${index} `), (clip.continue ? "↪ " : "") + (clip.name || "")),
                h("div", { class: "hint" }, _t("takes.take_s", { count }) + (res.chosen ? "" : _t("takes.none_usable"))),
                clipDefaultsButton(index)));
            if (index > 1 && !clip.continue) {
                canvas.append(h("div", { class: "tk-cut", style: `left:${colX(index) - gapX() / 2}px;height:${graph.height - 10}px` }));
                top.append(h("span", { class: "tk-cut-mark", style: `left:${colX(index) - gapX() / 2 - 7}px` }, "✂"));
            }
        }
        for (const node of graph.nodes) canvas.append(node.kind === "take" ? takeCard(node, p) : node.kind === "export" ? exportCard(node) : ghostCard(node, p));
        for (const slot of graph.slots || []) canvas.append(slotCard(slot));

        if (T.server) for (const ph of graph.placeholders) canvas.append(placeholderCard(ph, p));
        for (const e of graph.edges) {
            const a = graph.byKey[e.from], b = graph.byKey[e.to];
            if (!a || !b) continue;
            const x1 = a.x + COLW, y1 = a.y + CARD_H / 2, x2 = b.x, y2 = b.y + CARD_H / 2, mid = (x2 - x1) / 2;
            const path = document.createElementNS(svgNS, "path");
            path.setAttribute("d", `M${x1},${y1} C${x1 + mid},${y1} ${x2 - mid},${y2} ${x2},${y2}`);
            path.setAttribute("class", `tk-link ${e.cls}`);
            svg.append(path);
        }
        top.append(h("div", { class: "tk-pane-corner tk-stick-x", style: `width:${leftW}px;height:${TOP - 6}px` }));
        viewport.append(h("div", { class: "tk-toplayer" }, top), h("div", { class: "tk-sizer" }, canvas));
        T.graphSize = [graph.width, graph.height];
        T.graph = graph;
        const wrap = h("div", { class: "tk-vpwrap" }, viewport, minimap());
        const area = h("div", { class: "tk-area" }, h("div", { class: "tk-graphcol" }, wrap), videoPane(p));
        box.append(area);
        bindViewport(viewport);
        applyView(canvas);
        drawMinimap();
        stopStrayThumbs();
        equalFoldedWidths(canvas);
    }
    // folded branch headers all take the width of the widest one (▶▶ lined up on the right)
    function equalFoldedWidths(canvas) {
        const heads = [...canvas.querySelectorAll(".tk-band-head.folded")];
        if (heads.length < 2) return;
        for (const el of heads) el.style.width = "";
        const w = Math.max(...heads.map((el) => el.offsetWidth));
        for (const el of heads) el.style.width = `${w}px`;
    }
    // thumbnails keep their <video> from one drawing to the next (no flicker): one that was playing under the mouse
    // when its old card was removed never got its "mouse left": stop every one that is not under the mouse now
    function stopStrayThumbs() {
        for (const v of (T.thumbs ? T.thumbs.values() : [])) {
            if (v.paused || v.classList.contains("tk-live")) continue;
            const card = v.closest(".tk-card, .tk-pane-item, .tk-ex");
            if (card && card.matches(":hover")) continue;
            v.pause();
            v.currentTime = Math.min(0.5, (v.duration || 1) / 3);
        }
    }

    // ---------------------------------------------------------------- layout: columns or tree
    const gapX = () => (T.viewMode === "tree" ? 130 : GAP);
    const gapY = () => (T.viewMode === "tree" ? 34 : 12);
    const HEADW = 200;
    const colX = (i) => LEFT + HEADW + 30 + (i - 1) * (COLW + gapX());

    // ---------------------------------------------------------------- branches (Encore)
    const branchesList = () => T.studio.branches();
    const defBranch = () => (branchesList()[0] || {}).id || null;
    const branchOfRecord = (r) => (r ? H3.takeBranch(r, defBranch()) : null);
    const branchColor = (id) => (branchesList().find((b) => b.id === id) || {}).color || "#888";
    function bandPreferred(branch, k) {
        // the take of clip k a new step of this branch starts from: the selected one, or its most recent valid take
        if (k < 1 || !T.resolved || !T.resolved[k]) return null;
        if (T.resolved.branch === branch && T.resolved[k].chosen) return T.resolved[k].chosen;
        const list = (T.takes[k] || []).filter((r) => branchOfRecord(r) === branch && (T.resolved[k].takes[r.id] || ["invalid"])[0] !== "invalid")
            .sort((a, b) => (a.saved_at || 0) - (b.saved_at || 0));
        return list.length ? list[list.length - 1].id : null;
    }
    async function newBranch() {
        try {
            const res = await T.studio.createBranch();
            if (!res.copied_from) await T.studio.openBranch(res.branch.id, { first: true });
            recompute();
        } catch (e) { alert(e.message); }
    }
    // hovering a small picture shows it large in a bubble above the page (same size whatever the zoom)
    let zoomBubble = null;
    function hideZoom() { if (zoomBubble) { zoomBubble.remove(); zoomBubble = null; } }
    function zoomable(img, label) {
        img.addEventListener("mouseenter", () => {
            if (T.dragged || document.querySelector(".tk-viewport.dragging")) return;
            hideZoom();
            const big = h("img", { src: img.currentSrc || img.src });
            zoomBubble = h("div", { class: "tk-zoom" }, big, label ? h("div", { class: "tk-zoom-label" }, label) : null);
            zoomBubble.__img = img;
            document.body.append(zoomBubble);
            const place = () => {
                if (!zoomBubble) return;
                const r = img.getBoundingClientRect(), b = zoomBubble.getBoundingClientRect();
                let x = r.right + 10;
                if (x + b.width > window.innerWidth - 8) x = r.left - 10 - b.width;
                const y = Math.max(8, Math.min(window.innerHeight - b.height - 8, r.top + r.height / 2 - b.height / 2));
                Object.assign(zoomBubble.style, { left: `${Math.max(8, x)}px`, top: `${y}px`, visibility: "visible" });
            };
            if (big.complete) place(); else big.addEventListener("load", place, { once: true });
            requestAnimationFrame(place);
        });
        img.addEventListener("mouseleave", hideZoom);
        // the picture can vanish under the mouse (redraw, dialog closed): the bubble goes with it
        if (!window.__h3ZoomWatch) {
            window.__h3ZoomWatch = true;
            document.addEventListener("mousemove", () => { if (zoomBubble && !(zoomBubble.__img && zoomBubble.__img.isConnected && zoomBubble.__img.matches(":hover"))) hideZoom(); });
        }
        img.addEventListener("mousedown", hideZoom);
        return img;
    }
    // folding a branch: remembered per project in this browser
    const FOLD_H = 34;
    function foldKey() { return "encore.folded." + (plan().project || ""); }
    function foldedSet() {
        if (!T.folded || T.folded.key !== foldKey()) {
            let ids = [];
            try { ids = JSON.parse(localStorage.getItem(foldKey()) || "[]"); } catch (_) { /* ignore */ }
            T.folded = { key: foldKey(), ids: new Set(Array.isArray(ids) ? ids : []) };
        }
        return T.folded.ids;
    }
    function isFolded(id) { return foldedSet().has(id); }
    const unfoldedCount = () => branchesList().filter((b) => !isFolded(b.id)).length;
    function setFolded(id, on) {
        const set = foldedSet();
        if (on && unfoldedCount() <= 1) return;     // at least one branch stays unfolded
        if (on) set.add(id); else set.delete(id);
        try { localStorage.setItem(foldKey(), JSON.stringify([...set])); } catch (_) { /* ignore */ }
        if (on && T.resolved?.branch === id && T.fingerprints) { T.resolved = resolveWith(T.pick); studioSaveSelection(); }
        renderTakes();
    }
    // folds remembered from an earlier visit may cover every branch (branches deleted since): unfold one
    function keepOneUnfolded() {
        const list = branchesList();
        if (!list.length || list.some((b) => !isFolded(b.id))) return;
        const keep = list.find((b) => b.id === T.pickBranch) || list[0];
        foldedSet().delete(keep.id);
        try { localStorage.setItem(foldKey(), JSON.stringify([...foldedSet()])); } catch (_) { /* ignore */ }
    }
    function foldToggle(br, folded) {
        const last = !folded && unfoldedCount() <= 1;
        return h("button", { class: "tk-fold", disabled: last || null,
            title: last ? _t("takes.cannot_fold_last_branch") : folded ? _t("takes.unfold_branch") : _t("takes.fold_branch"),
            onclick: (e) => { e.stopPropagation(); setFolded(br.id, !folded); } }, folded ? "▸" : "▾");
    }
    function bandHeader(band, p) {
        const br = band.branch;
        if (band.folded) {
            const active = T.resolved?.branch === br.id;
            return h("div", { class: `tk-band-head folded tk-stick-x${active ? " active" : ""}`, style: `left:${LEFT}px;top:${band.y}px;height:${FOLD_H}px;border-color:${br.color}`,
                ondblclick: () => setFolded(br.id, false) },
                foldToggle(br, true), h("i", { class: "tk-fold-dot", style: `background:${br.color}` }),
                h("b", {}, br.name),
                h("span", { class: "hint" }, _t("takes.take_s", { count: band.count }) + (band.running ? " · " + _t("takes.folded_running", { count: band.running }) : "")),
                fillButton(br));
        }
        const free = H3.mode(p) === "free";
        const refs = Object.entries(br.refs || {});
        const thumbs = refs.filter(([, r]) => r && r.image).map(([name, r]) => zoomable(h("img", { class: "tk-band-ref", src: T.studio.viewUrl(r.image) }), name));
        const voices = free ? refs.filter(([, r]) => r && r.voice).map(([name]) => name) : [];
        const missing = Object.keys(p.refs || {}).filter((name) => !(br.refs || {})[name] || (!br.refs[name].image && !br.refs[name].voice));
        const active = T.resolved?.branch === br.id;
        return h("div", { class: `tk-band-head tk-stick-x${active ? " active" : ""}`, style: `left:${LEFT}px;top:${band.y}px;width:${HEADW}px;min-height:${Math.min(band.h, CARD_H)}px;border-color:${br.color}` },
            h("div", { class: "tk-band-title" }, foldToggle(br, false), h("i", { style: `background:${br.color}` }),
                h("b", { title: _t("takes.double_click_rename"), ondblclick: () => T.studio.renameBranch(br.id) }, br.name),
                active ? h("span", { class: "hint" }, _t("takes.selection")) : null),
            h("div", { class: "tk-band-refs" }, thumbs.length ? thumbs : h("span", { class: "hint" }, _t("takes.no_picture"))),
            h("div", { class: "hint" }, _t("takes.mp_ref", { width: br.width, height: br.height, v2: ((br.width * br.height) / (1024 * 1024)).toFixed(2).replace(/0$/, "").replace(".", H3I18n.decimal()), v3: br.ref_image_size || "max" })),
            voices.length ? h("div", { class: "hint" }, _t("takes.voice_2") + voices.join(", ")) : null,
            !free ? h("div", { class: "hint" }, "♪ " + (br.song ? br.song.split("/").pop() : _t("takes.no_song"))) : null,
            missing.length ? h("div", { class: "tk-band-warn" }, _t("takes.to_choose") + missing.join(", ")) : null,
            h("div", { class: "tk-inline", style: "margin-top:6px" },
                h("button", { class: "small", onclick: () => T.studio.openBranch(br.id) }, _t("takes.references_2")),
                h("button", { class: `small ${br.upscale && br.upscale.enabled ? "tk-up-on" : ""}`, title: _t("takes.latent_upscale_first_pass_at_a"),
                    onclick: () => T.studio.openUpscale(br.id) }, br.upscale && br.upscale.enabled ? "⇧ upscale…" : "upscale…"),
                h("button", { class: `small ${(br.loras || []).length ? "tk-lora-on" : ""}`,
                    title: (br.loras || []).length ? _t("takes.lora_added_to_the_takes_of") + T.studio.fmtLoras(br.loras) : _t("takes.lora_added_to_the_takes_of_2"),
                    onclick: () => T.studio.openBranchLoras(br.id) }, (br.loras || []).length ? _t("takes.lora_3", { length: br.loras.length }) : _t("takes.lora_2")),
                h("button", { class: "small", onclick: () => T.studio.renameBranch(br.id) }, _t("takes.rename")),
                fillButton(br),
                h("button", { class: "small danger", title: _t("takes.delete_the_branch_what_is_in"),
                    disabled: T.jobs.some((j) => (j.status === "queued" || j.status === "running") && (j.branch || defBranch()) === br.id) || null,
                    onclick: () => T.studio.deleteBranch(br.id) }, _t("takes.delete"))));
    }
    // ▶▶ : fills every hole of the branch (what is missing, invalid, or built on a clip that is redone), in plan order.
    // Its label comes from a dry run on the server, asked again when takes, jobs or the selection change.
    function fillKey() {
        const all = Object.values(T.takes || {}).flat();
        return JSON.stringify([all.length, Math.max(0, ...all.map((r) => r.saved_at || 0)), T.jobs.filter((j) => j.status === "queued" || j.status === "running").map((j) => j.id),
            T.pick, T.pickBranch, T.studio.planStamp ? T.studio.planStamp() : null]);
    }
    function fillInfo(brId) {
        T.fill = T.fill || {};
        const key = fillKey(), cur = T.fill[brId];
        if (!cur || cur.key !== key) {
            if (!cur || !cur.loading || cur.key !== key) {
                T.fill[brId] = { key, loading: true, data: cur && cur.data, error: cur && cur.error, busy: cur && cur.busy };
                T.studio.fillBranch(brId, true).then((data) => { T.fill[brId] = { key, data }; recompute(); })
                    .catch((e) => { T.fill[brId] = { key, error: e.message, busy: e.code === "busy" }; recompute(); });
            }
        }
        return T.fill[brId];
    }
    function clipRange(items) {
        const list = items.map((i) => i.clip);
        if (!list.length) return "";
        const runs = [];
        for (const c of list) { const last = runs[runs.length - 1]; if (last && c === last[1] + 1) last[1] = c; else runs.push([c, c]); }
        return runs.map(([a, b]) => (a === b ? `${a}` : _t("takes.to", { a, b }))).join(", ");
    }
    function fillButton(br) {
        const info = fillInfo(br.id);
        const data = info.data;
        const n = (plan().clips || []).length;
        // a fixed label (the header has a fixed width): what it will do is in the tooltip
        let title = _t("takes.generates_every_clip_missing_in_this"), disabled = true;
        if (info.error) { title = (info.busy ? _t("takes.generating_2") : _t("takes.fill_unavailable")) + "\n" + info.error; }
        else if (data) {
            const count = data.items.length;
            disabled = !count;
            const what = !count ? _t("takes.branch_complete") : count === n && !Object.values(T.takes || {}).flat().some((r) => branchOfRecord(r) === br.id)
                ? _t("takes.generate_all") : _t("takes.generate_2", { v0: count === 1 ? _t("takes.the_clip") : _t("takes.the_clips"), v1: clipRange(data.items) });
            title = what + "\n" + (!count ? _t("takes.each_clip_has_a_usable_take") : _t("takes.clip_s_to_generate_in_order", { count }));
        }
        return h("button", { class: "small tk-fill", disabled: disabled || null, title, onclick: () => confirmFill(br) }, _t("takes.fill_label"));
    }
    async function confirmFill(br) {
        let data;
        try { await T.studio.savePlan(); data = await T.studio.fillBranch(br.id, true); } catch (e) { alert(e.message); return; }
        if (!data.items.length) { alert(_t("takes.nothing_to_generate_each_clip_has")); return; }
        const fmt = (s) => (s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)} h ${String(Math.round(s % 3600 / 60)).padStart(2, "0")}`);
        const lines = data.items.map((it) => `• clip ${it.clip} ${it.name} — ${it.reason}${it.after ? _t("takes.following_take", { v0: tokenOf(it.after) }) : it.new_scene && it.clip > 1 ? _t("takes.new_scene") : ""}`);
        const head = _t("takes.branch_clip_s_to_generate_in", { name: br.name, length: data.items.length })
            + (data.from_selection ? _t("takes.starting_point_the_selection_of_this") : _t("takes.starting_point_the_latest_usable_takes"))
            + (data.eta ? _t("takes.estimated_time_from_previous_generations", { v0: fmt(data.eta) }) : "");
        const answer = await H3Dialog.confirm(`${head}\n\n${lines.join("\n")}`,
            { ok: _t("takes.start"), danger: false, check: { label: _t("takes.assemble_the_branch_at_the_end") + (plan().clips || []).length + ")", checked: true } });
        if (!answer) return;
        try {
            const res = await T.studio.fillBranch(br.id, false, answer.checked);
            toast(_t("takes.generation_s_added_to_the_queue", { length: (res.launched || []).length }) + (res.assembly ? _t("takes.then_assembly") : ""));
            studioPollSoon(300);
        } catch (e) { alert(e.message); }
    }
    // column header: the clip's own LoRA and upscale (all branches)
    function clipDefaultsButton(index) {
        const cd = T.studio.clipDefault(index);
        const parts = [];
        if (cd.loras.length) parts.push(cd.loras.length > 1 ? _t("takes.l", { length: cd.loras.length }) : "L");
        if (cd.no_branch_loras) parts.push(_t("takes.no_branch_l"));
        const title = _t("takes.lora_of_this_clip")
            + (cd.loras.length ? _t("takes.clip_lora") + T.studio.fmtLoras(cd.loras) : "")
            + (cd.no_branch_loras ? _t("takes.without_the_branch_lora") : "");
        return h("button", { class: `small tk-clipdef ${parts.length ? "set" : ""}`, title, onclick: (e) => { e.stopPropagation(); T.studio.openClipDefaults(index); } },
            parts.length ? parts.join(" · ") : "⚙");
    }
    function buildBands(p) {
        const n = p.clips.length, def = defBranch();
        const nodes = [], edges = [], placeholders = [], bands = [], byKey = {}, slots = [];
        const VG = gapY(), BAND_GAP = 44;
        let y = TOP;
        for (const br of branchesList()) {
            if (isFolded(br.id)) {        // folded: a thin band, nothing of its tree is drawn
                const count = Object.values(T.takes || {}).flat().filter((r) => branchOfRecord(r) === br.id).length;
                const running = T.jobs.filter((j) => j.kind !== "assemble" && ["queued", "running"].includes(j.status) && (j.branch || def) === br.id).length;
                bands.push({ branch: br, y, h: FOLD_H, folded: true, count, running });
                y += FOLD_H + BAND_GAP;
                continue;
            }
            const items = [], keyOfToken = {};
            for (let index = 1; index <= n; index++) {
                const list = (T.takes[index] || []).filter((r) => branchOfRecord(r) === br.id).sort((a, b) => (a.saved_at || 0) - (b.saved_at || 0));
                for (const record of list) {
                    const key = "t:" + record.id;
                    items.push({ key, kind: "take", index, record, order: record.saved_at || 0 });
                    keyOfToken[`${index}:${tokenOf(record.id)}`] = key;
                }
                for (const job of jobsOf(index).filter((j) => (j.branch || def) === br.id)) {
                    const key = "g:" + job.id;
                    items.push({ key, kind: "ghost", index, job, order: Infinity });
                    keyOfToken[`${index}:${job.token}`] = key;
                }
            }
            for (const it of items) {
                const clip = p.clips[it.index - 1];
                it.parent = null;
                if (it.index === 1) continue;
                if (clip.continue) {
                    const token = it.kind === "take" ? (it.record.parent ? tokenOf(it.record.parent) : null) : it.job.parentToken;
                    const key = token ? keyOfToken[`${it.index - 1}:${token}`] : null;
                    if (key) { it.parent = key; edges.push({ from: key, to: it.key, cls: linkClass(it, key) }); }
                } else if (T.viewMode === "tree") {
                    const pref = bandPreferred(br.id, it.index - 1);
                    if (pref && keyOfToken[`${it.index - 1}:${tokenOf(pref)}`]) { it.parent = "t:" + pref; edges.push({ from: it.parent, to: it.key, cls: "cut" }); }
                }
            }
            const local = {};
            for (const it of items) local[it.key] = it;
            for (const it of items) if (it.parent && !local[it.parent]) it.parent = null;
            // an empty box to the right of each end of the branch: the next clip, to generate after this take
            const hasChild = new Set(items.filter((it) => it.parent).map((it) => it.parent));
            for (const it of [...items]) {
                if (it.index >= n || !p.clips[it.index].continue || hasChild.has(it.key)) continue;
                if (it.kind === "take") {
                    const st = T.resolved?.[it.index]?.takes?.[it.record.id];
                    if (st && st[0] === "invalid") continue;
                } else if (["error", "cancelled", "done"].includes(it.job.status)) continue;
                const slot = { key: "s:" + it.key, kind: "slot", index: it.index + 1, parent: it.key, order: Infinity, branch: br.id,
                    token: it.kind === "take" ? tokenOf(it.record.id) : it.job.token, after: it };
                items.push(slot);
                local[slot.key] = slot;
                edges.push({ from: it.key, to: slot.key, cls: "slot" });
            }
            const children = {};
            for (const it of items) if (it.parent) (children[it.parent] = children[it.parent] || []).push(it);
            for (const list of Object.values(children)) list.sort((a, b) => a.order - b.order);
            const colBottom = {};
            if (T.viewMode === "tree") {
                const span = {};
                const sizeOf = (it) => {
                    const kids = children[it.key] || [];
                    const total = kids.reduce((acc, k) => acc + sizeOf(k), 0) + VG * Math.max(0, kids.length - 1);
                    return (span[it.key] = Math.max(CARD_H, total));
                };
                const place = (it, top) => {
                    const kids = children[it.key] || [];
                    if (!kids.length) it.y = top + (span[it.key] - CARD_H) / 2;
                    else {
                        let yy = top + (span[it.key] - (kids.reduce((a, k) => a + span[k.key], 0) + VG * (kids.length - 1))) / 2;
                        for (const k of kids) { place(k, yy); yy += span[k.key] + VG; }
                        it.y = (kids[0].y + kids[kids.length - 1].y) / 2;
                    }
                    it.x = colX(it.index);
                };
                const subtree = (it, out = []) => { out.push(it); for (const k of children[it.key] || []) subtree(k, out); return out; };
                const roots = items.filter((it) => !it.parent).sort((a, b) => a.index - b.index || a.order - b.order);
                for (const root of roots) {
                    sizeOf(root);
                    const members = subtree(root);
                    let top = y;
                    for (const c of new Set(members.map((m) => m.index))) if (colBottom[c] !== undefined) top = Math.max(top, colBottom[c] + VG * 2);
                    place(root, top);
                    for (const m of members) colBottom[m.index] = Math.max(colBottom[m.index] ?? -Infinity, m.y + CARD_H);
                }
            } else {
                const rows = {};
                for (const it of items) {
                    rows[it.index] = rows[it.index] || 0;
                    it.x = colX(it.index);
                    it.y = y + rows[it.index]++ * (CARD_H + VG);
                    colBottom[it.index] = it.y + CARD_H;
                }
            }
            // "générer": clip 1 and the first clip of each scene, when the branch has none yet
            for (let index = 1; index <= n; index++) {
                const clip = p.clips[index - 1];
                if (index > 1 && clip.continue) continue;
                if (items.some((it) => it.index === index)) continue;
                const yy = colBottom[index] !== undefined ? colBottom[index] + VG : y;
                placeholders.push({ index, branch: br.id, x: colX(index), y: yy });
                colBottom[index] = yy + CARD_H;
            }
            const bottom = Math.max(y + CARD_H + 40, ...Object.values(colBottom));
            bands.push({ branch: br, y, h: bottom - y });
            for (const it of items) { if (it.kind === "slot") slots.push(it); else nodes.push(it); byKey[it.key] = it; }
            y = bottom + BAND_GAP;
        }
        const width = colX(n) + COLW + LEFT;   // assembled videos are in the side pane
        return { nodes, edges, byKey, placeholders, bands, slots, newBranchY: y - BAND_GAP / 2, width, height: y + 40 };
    }


    function linkClass(child, parentKey) {
        if (child.kind === "ghost") return "ghost";
        const parentTake = parentKey.startsWith("t:") ? parentKey.slice(2) : null;
        const res = T.resolved;
        const cState = res[child.index]?.takes?.[child.record.id]?.[0];
        const pState = parentTake ? res[child.index - 1]?.takes?.[parentTake]?.[0] : null;
        const both = parentTake && res[child.index - 1]?.chosen === parentTake && res[child.index]?.chosen === child.record.id;
        return both ? "on" : unusable(cState) || unusable(pState) ? "stale" : cState === "other" ? "off" : "";
    }

    function takeCard(node, p) {
        const record = node.record, index = node.index;
        const clip = p.clips[index - 1];
        const res = T.resolved[index];
        const [state, why] = res.takes[record.id] || ["invalid", "?"];
        const chosen = res.chosen === record.id;
        const video = thumbVideo("t:" + record.id, () => {
            const v = h("video", { muted: true, loop: true, playsinline: true, preload: "auto" });
            v.muted = true;
            return v;
        });
        if (!video.dataset.loading && hasPreview(record.id)) { video.dataset.loading = "1"; attachThumb(video, record.id); }
        const branch = branchOfRecord(record);
        const actions = state === "invalid" ? regenerateButton(index, clip, record)
            : !unusable(state) ? h("div", { class: "tk-actions" },
            index === 1 ? null : splitButton("↻", _t("takes.new_take_of_this_clip_random") + (clip.continue ? _t("takes.from_the_same_take_of_the") : ""),
                index, { parentToken: clip.continue ? (record.parent ? tokenOf(record.parent) : null) : null, random: true }, branch, _t("takes.new_take_of_clip", { index }), "tk-retake", sameAs(record).loras ? sameAs(record) : null)) : null;
        return h("div", {
            class: `tk-card ${chosen ? "chosen" : state}`, "data-take": record.id,
            style: `left:${node.x}px;top:${node.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: _t("takes.seed", { id: record.id, seed: record.seed, v2: when(record.saved_at), v3: why ? "\n" + why : "" }),
            onclick: () => {
                if (T.dragged) return;
                clearTimeout(T.clickTimer);
                T.clickTimer = setTimeout(() => choose(index, record.id), 230);
            },
            ondblclick: (e) => { e.preventDefault(); clearTimeout(T.clickTimer); openViewer(index, record.id); },
            onmouseenter: () => { if (!video.src) return; video.muted = !T.soundOnHover; video.currentTime = 0; video.play().catch(() => { video.muted = true; video.play().catch(() => {}); }); },
            onmouseleave: () => { video.pause(); video.currentTime = Math.min(0.5, (video.duration || 1) / 3); },
        },
            branch ? h("i", { class: "tk-branch-mark", style: `background:${branchColor(branch)}` }) : null,
            record.studio ? badges(record.studio.upscale, record.studio.upscale ? _t("takes.latent_upscale_summary", { summary: record.studio.upscale.summary }) : "", record.studio.extra_loras) : null,
            h("div", { class: "tk-thumb" }, hasPreview(record.id) ? video : h("span", { class: "hint" }, _t("takes.no_preview")),
                h("span", { class: "tk-dur", title: _t("takes.clip_length") }, clipLength(record.frames || clip.frames)),
                // invalidated: « refaire » is at the top right, the assembly goes at the bottom left of the picture
                state === "invalid" ? leafButton(index, record, branch, true) : null),
            h("div", { class: "tk-meta" }, h("span", { class: "tk-seedbox" }, chosen ? "✓ " : "", seedField(record, (seed) => {
                if (state === "invalid") { const parent = regenerateParent(index, clip, branch); if (!parent.ok) { alert(_t("takes.regenerate_clip_first_2", { v0: index - 1 })); return; } generate(index, { parentToken: parent.token, seed, branch }); }
                else generate(index, { parentToken: clip.continue ? (record.parent ? tokenOf(record.parent) : null) : null, seed, branch });
            })), h("span", { class: "hint" }, when(record.saved_at))),
            unusable(state) ? h("div", { class: "tk-why" }, why) : null,
            actions,
            planButton(index, record),
            state !== "invalid" ? leafButton(index, record, branch, false) : null);
    }

    // what assembling this leaf would take: clips 1 to index along its chain (earlier scenes: the current selection)
    function leafChain(index, record, branch) {
        const p = plan();
        const chain = {};
        let i = index, rec = record;
        while (rec) {
            chain[i] = rec.id;
            if (!(p.clips[i - 1] && p.clips[i - 1].continue) || i === 1) break;
            const parent = rec.parent;
            i -= 1;
            rec = (T.takes[i] || []).find((r) => r.id === parent) || null;
            if (!rec) return { ok: false, why: _t("takes.the_take_of_clip_it_continues", { i }) };
        }
        const sel = { branch };
        if (T.pickBranch == null || T.pickBranch === branch) Object.assign(sel, T.pick || {});
        Object.assign(sel, chain);
        const res = H3.studioResolveTakes(p, T.takes, sel, T.fingerprints, T.studio.current());
        for (let k = 1; k <= index; k++) {
            const pick = res[k] && res[k].chosen;
            if (!pick || (chain[k] && pick !== chain[k])) return { ok: false, why: _t("takes.clip_has_no_usable_take_in", { k }) };
        }
        return { ok: true };
    }
    // on every take, shown when the mouse is over the card: assembles clips 1 to this one along its chain
    // on an invalidated take (or a chain with one): an assembly of what was really made, after a confirmation
    function leafButton(index, record, branch, invalid) {
        if (!T.fingerprints) return null;
        const btn = h("button", { class: `small tk-asm-btn${invalid ? " invalid" : ""}`,
            onmouseenter: () => {                // checked when needed (a whole resolution per take would be slow)
                const c = invalid ? { ok: false } : leafChain(index, record, branch);
                btn.classList.toggle("invalid", !c.ok);
                btn.title = c.ok ? _t("takes.assemble_clips_1_to_along_this", { index })
                    : (c.why ? _t("takes.cannot_assemble", { why: c.why }) + "\n" : "") + _t("takes.assemble_invalid_title", { index });
            },
            onclick: (e) => {
                e.stopPropagation();
                const c = invalid ? { ok: false } : leafChain(index, record, branch);
                if (c.ok) assemble(index, record.id); else assembleInvalid(index, record.id);
            } }, (invalid ? "⚠ " : "") + _t("takes.assemble_1", { index }));
        return btn;
    }
    async function assembleInvalid(index, takeId) {
        let check;
        try { await T.studio.savePlan(); check = await T.studio.assembleCheck(index, takeId); }
        catch (e) { alert(_t("takes.cannot_start_the_assembly", { v0: e.message })); return; }
        if (check.error) { alert(_t("takes.cannot_start_the_assembly", { v0: check.error })); return; }
        const lines = (check.invalid || []).map((i) => _t("takes.assemble_invalid_line", { clip: i.clip, take: i.take, reason: i.reason || "?" }));
        const warn = (check.warnings || []).map((w) => "⚠ " + w);
        const text = [_t("takes.assemble_invalid_head", { index }), "",
            lines.length ? _t("takes.assemble_invalid_list") : _t("takes.assemble_invalid_none"), ...lines,
            ...(warn.length ? ["", ...warn] : []), "", _t("takes.assemble_invalid_note")].join("\n");
        if (!await H3Dialog.confirm(text, { ok: _t("takes.assemble_invalid_ok"), danger: lines.length > 0 })) return;
        try {
            const job = await T.studio.assemble(index, takeId, true);
            if (!T.jobs.some((j) => j.id === job.id)) T.jobs.push(job);
            studioPollSoon(300);
            renderTakes();
        } catch (e) { alert(_t("takes.cannot_start_the_assembly", { v0: e.message })); }
    }

    // seed of a take: selectable and copyable; a new value + Enter (or ↵) makes a new take with that seed
    const MAX_SEED = 2 ** 48;
    function parseSeed(text) {
        const t = String(text).trim();
        if (!/^\d+$/.test(t)) return null;
        const v = Number(t);
        return Number.isSafeInteger(v) && v <= MAX_SEED ? v : null;
    }
    function seedField(record, launch) {
        const original = record ? String(record.seed ?? "") : "";
        const input = h("input", { class: "tk-seed", value: original, placeholder: _t("takes.seed_auto"), spellcheck: "false",
            title: record ? _t("takes.seed_of_this_take_selectable_another") : _t("takes.optional_seed_empty_the_plan_s") });
        const go = h("button", { class: "small tk-seed-go", title: _t("takes.generate_a_new_take_with_this"), hidden: true }, "↵");
        const stop = (e) => e.stopPropagation();
        for (const ev of ["click", "dblclick", "mousedown"]) { input.addEventListener(ev, stop); go.addEventListener(ev, stop); }
        const sync = () => { go.hidden = !record || input.value.trim() === original; };
        const submit = () => {
            const v = parseSeed(input.value);
            if (v === null) { alert(_t("takes.invalid_seed_an_integer_from_0", { MAX_SEED })); return; }
            if (record && String(v) === original) return;
            launch(v);
            if (record) { input.value = original; sync(); }
        };
        input.addEventListener("input", sync);
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } if (e.key === "Escape") { input.value = original; sync(); input.blur(); } });
        go.addEventListener("click", submit);
        const box = h("span", { class: "tk-seedwrap" }, input, go);
        box.seedValue = () => (input.value.trim() === "" ? null : parseSeed(input.value));
        return box;
    }

    // "régénérer": a new take of this clip only, with the seed of the invalidated one
    function regenerateParent(index, clip, branch) {
        if (!clip.continue || index === 1) return { ok: true, token: null };
        const chosen = bandPreferred(branch, index - 1);
        if (chosen) return { ok: true, token: tokenOf(chosen) };
        const waiting = jobsOf(index - 1).filter((j) => (j.status === "queued" || j.status === "running") && (j.branch || defBranch()) === branch);
        if (waiting.length) return { ok: true, token: waiting[waiting.length - 1].token };
        return { ok: false };
    }
    // a launch button with its ▾: click = branch + clip settings; ▾ = the "prise réglée" dialog (LoRA, upscale, seed)
    function tuned(index, opts, branch, title, preset) {
        T.studio.takeDialog({ clip: index, branch: branch || defBranch(), title, preset }).then((res) => {
            if (!res) return;
            generate(index, { ...opts, branch, loras: res.loras, upscale: res.upscale, upscaleSettings: res.upscale_settings, seed: res.seed ?? opts.seed ?? null, random: res.seed == null ? !!opts.random : false });
        });
    }
    function effTitle(index, branch) {
        return "\n" + T.studio.effectiveTake(branch || defBranch(), index).text + _t("takes.tune_this_take_differently");
    }
    // preset: {loras, upscale} of the take the button belongs to (the ▾ dialog opens with them)
    function splitButton(label, title, index, opts, branch, dialogTitle, cls = "", preset = null) {
        const go = (e) => { e.stopPropagation(); generate(index, { ...opts, branch }); };
        return h("span", { class: "tk-split" },
            h("button", { class: `small ${cls}`, title: title + effTitle(index, branch), onclick: go }, label),
            h("button", { class: "small tk-split-arrow", title: _t("takes.tuned_take_lora_upscale_seed"), onclick: (e) => { e.stopPropagation(); tuned(index, opts, branch, dialogTitle, preset); } }, "▾"));
    }
    function badges(upscale, upTitle, loras) {
        if (!upscale && !(loras && loras.length)) return null;
        return h("span", { class: "tk-badges" },
            upscale ? h("span", { class: "tk-up-badge", title: upTitle }, "⇧") : null,
            loras && loras.length ? h("span", { class: "tk-lora-badge", title: _t("takes.extra_lora") + T.studio.fmtLoras(loras) }, loras.length > 1 ? _t("takes.l", { length: loras.length }) : "L") : null);
    }
    // a take made with v0.16 or later knows its own LoRA and upscale: « ⟲ redo » does the same again (and since 0.27,
    // the upscale settings it had for itself only)
    function sameAs(record) {
        const st = record && record.studio;
        if (!st || !("extra_loras" in st)) return {};
        const own = st.upscale && st.upscale.source === "take" ? st.upscale.settings : null;
        return { loras: st.extra_loras || [], upscale: st.upscale ? "on" : "off", ...(own ? { upscaleSettings: own, upscale_settings: own } : {}) };
    }
    // the next clip after a take (or a take still waiting): a click generates it, ▾ sets its LoRA / upscale / seed
    function slotCard(slot) {
        const index = slot.index;
        const opts = { parentToken: slot.token };
        const launch = () => { if (!T.dragged) generate(index, { ...opts, branch: slot.branch }); };
        return h("div", { class: "tk-card tk-placeholder tk-slot", style: `left:${slot.x}px;top:${slot.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: _t("takes.generate_clip_following_this_take", { index }) + effTitle(index, slot.branch), onclick: launch },
            h("div", { class: "tk-plus" }, "+"), h("div", { class: "hint" }, _t("takes.clip_following", { index })),
            h("button", { class: "small tk-split-arrow tk-ph-arrow", title: _t("takes.tuned_take_lora_upscale_seed"),
                onclick: (e) => { e.stopPropagation(); tuned(index, opts, slot.branch, _t("takes.clip_following_this_take", { index })); } }, _t("takes.tuned")),
            planButton(index, null, { branch: slot.branch }));
    }
    function regenerateButton(index, clip, record) {
        const branch = branchOfRecord(record);
        const parent = regenerateParent(index, clip, branch);
        return h("div", { class: "tk-actions show" },
            h("button", { class: "small warn", disabled: !parent.ok || null,
                title: parent.ok ? _t("takes.new_take_of_clip_with_the", { index, v1: clip.continue && index > 1 ? _t("takes.following_the_chosen_take_of_clip", { v0: index - 1 }) : "" })
                    : _t("takes.regenerate_clip_first", { v0: index - 1 }),
                onclick: (e) => { e.stopPropagation(); generate(index, { parentToken: parent.token, seed: record.seed, branch, ...sameAs(record) }); } },
                parent.ok ? _t("takes.redo") : _t("takes.clip_first", { n: index - 1 })));
    }

    function ghostCard(node, p) {
        const job = node.job, index = node.index;
        const pct = job.progress ? Math.round(100 * job.progress.value / Math.max(1, job.progress.max)) : 0;
        const live = job.status === "queued" || job.status === "running";
        return h("div", { class: `tk-card tk-ghost ${job.status}`, "data-job": job.id, style: `left:${node.x}px;top:${node.y}px;width:${COLW}px;height:${CARD_H}px`, title: job.error || (job.preview ? _t("takes.double_click_larger_preview") : ""),
            ondblclick: (e) => { e.preventDefault(); if (job.preview) openLive(job); },
            onmouseenter: (e) => { const v = e.currentTarget.querySelector("video.tk-live"); if (v && T.soundOnHover) v.muted = false; },
            onmouseleave: (e) => { const v = e.currentTarget.querySelector("video.tk-live"); if (v) v.muted = true; } },
            h("div", { class: "tk-thumb" }, job.preview && live
                ? liveElement(job)
                : h("span", { class: "tk-ghost-icon" }, job.status === "queued" ? "⏳" : job.status === "error" ? "✖" : job.status === "done" ? "✓" : "▶")),
            h("div", { class: "tk-ghost-label" }, ghostLabel(job)),
            job.status === "running" ? h("div", { class: "tk-progress" }, h("i", { style: `width:${pct}%` })) : null,
            h("div", { class: "tk-actions show" },
                live ? h("button", { class: "small danger", title: _t("takes.cancel_this_generation"), onclick: (e) => { e.stopPropagation(); cancelJob(job); } }, _t("takes.cancel")) : null,
                job.status === "error" ? h("button", { class: "small", onclick: () => { T.jobs = T.jobs.filter((j) => j !== job); T.studio.removeJob(job.id).catch(() => {}); renderTakes(); } }, _t("takes.remove")) : null,
                null),
            job.branch ? h("i", { class: "tk-branch-mark", style: `background:${branchColor(job.branch)}` }) : null,
            job.kind !== "assemble" ? badges(job.upscale, _t("takes.with_latent_upscale"), job.loras) : null,
            job.kind === "clip" && live ? planButton(job.clip, null, { job }) : null,
            live && job.kind === "clip" ? h("button", { class: "small tk-asm-btn",
                title: _t("takes.plan_the_assembly_of_clips_1", { index }),
                onclick: async (e) => {
                    e.stopPropagation();
                    try {
                        await T.studio.savePlan();
                        const made = await T.studio.assembleAfter(job.id);
                        if (!T.jobs.some((j) => j.id === made.id)) T.jobs.push(made);
                        toast(_t("takes.assembly_of_clips_1_to_planned", { index }));
                        studioPollSoon(300);
                    } catch (err) { alert(err.message); }
                } }, _t("takes.assemble_1", { index })) : null);
    }

    // ---------------------------------------------------------------- assembled videos (Encore)
    const whenMs = (t) => new Date(t * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    function exportCard(node) {
        const ex = node.export;
        const video = h("video", { muted: true, loop: true, playsinline: true, preload: "metadata", src: T.studio.viewUrl(ex.file) });
        video.addEventListener("loadeddata", () => { if (video.paused) video.currentTime = Math.min(0.5, (video.duration || 1) / 3); }, { once: true });
        return h("div", { class: "tk-card tk-export", style: `left:${node.x}px;top:${node.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: _t("takes.mp4_clips_1_to_double_click", { name: ex.name, clips: ex.clips }),
            ondblclick: (e) => { e.preventDefault(); openExport(ex); },
            onmouseenter: () => { video.muted = !T.soundOnHover; video.currentTime = 0; video.play().catch(() => { video.muted = true; video.play().catch(() => {}); }); },
            onmouseleave: () => { video.pause(); video.currentTime = Math.min(0.5, (video.duration || 1) / 3); } },
            h("i", { class: "tk-branch-mark", style: `background:${branchColor(ex.branch || defBranch())}` }),
            h("div", { class: "tk-thumb" }, video),
            h("div", { class: "tk-meta" }, h("span", {}, _t("takes.video_clips_1", { clips: ex.clips })), h("span", { class: "hint" }, whenMs(ex.created))));
    }
    function openExport(ex) {
        const close = () => { video.pause(); overlay.remove(); document.removeEventListener("keydown", onKey); };
        const onKey = (e) => { if (e.key === "Escape") close(); };
        const video = h("video", { controls: true, autoplay: true, src: T.studio.viewUrl(ex.file), style: "width:100%;max-height:62vh;background:#000;border-radius:6px" });
        const overlay = h("div", { class: "tk-modal", onclick: (e) => { if (e.target === overlay) close(); } },
            h("div", { class: "tk-box" },
                h("div", { class: "tk-box-head" }, h("b", {}, `${ex.name}.mp4`),
                    h("span", { class: "hint" }, _t("takes.clips_1_to", { v0: ex.branch_name || "", clips: ex.clips, v2: ex.size ? ex.size.join(" × ") : "", v3: whenMs(ex.created) })),
                    h("span", { style: "flex:1" }),
                    ex.infos ? h("button", { title: _t("takes.how_the_video_was_made_clips"), onclick: () => window.open(T.studio.infosUrl(ex.infos), "_blank") }, "infos") : null,
                    ex.checkpoint ? h("button", { onclick: async () => { if (await T.studio.restoreCheckpoint(ex.checkpoint, _t("takes.the_state_of", { name: ex.name }))) close(); } }, _t("takes.restore_the_state_of_this_video")) : null,
                    h("button", { onclick: close }, _t("takes.close"))),
                video));
        document.body.append(overlay);
        document.addEventListener("keydown", onKey);
    }

    function placeholderCard(ph, p) {
        const index = ph.index;
        const seed = seedField(null, () => {});
        const launch = () => {
            const typed = seed.querySelector("input").value.trim();
            const v = typed === "" ? null : parseSeed(typed);
            if (typed !== "" && v === null) { alert(_t("takes.invalid_seed_an_integer_from_0", { MAX_SEED })); return; }
            generate(index, { branch: ph.branch, seed: v });
        };
        seed.querySelector("input").addEventListener("keydown", (e) => { if (e.key === "Enter") launch(); });
        return h("div", { class: "tk-card tk-placeholder", style: `left:${ph.x}px;top:${ph.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: (index === 1 ? _t("takes.generate_clip_1_of_this_branch") : _t("takes.generate_clip_new_scene_in_this", { index })) + effTitle(index, ph.branch),
            onclick: () => { if (!T.dragged) launch(); } },
            h("div", { class: "tk-plus" }, "+"), h("div", { class: "hint" }, _t("takes.generate")), h("div", { class: "tk-ph-seed" }, seed),
            h("button", { class: "small tk-split-arrow tk-ph-arrow", title: _t("takes.tuned_take_lora_upscale_seed"),
                onclick: (e) => { e.stopPropagation(); tuned(index, {}, ph.branch, _t("takes.clip_new_take", { index })); } }, _t("takes.tuned")),
            planButton(index, null, { branch: ph.branch }));
    }

    // ---------------------------------------------------------------- zoom and pan
    function loadViewPrefs() {
        try {
            const v = JSON.parse(localStorage.getItem("h3clipplan.view") || "{}");
            if (v.mode === "tree" || v.mode === "columns") T.viewMode = v.mode;
            T.mapCorner = ["tl", "tr", "bl", "br"].includes(v.mapCorner) ? v.mapCorner : "br";
            T.mapOpen = v.mapOpen !== false;
            T.paneOpen = v.paneOpen !== false;
        } catch (_) { /* storage unavailable */ }
        if (!T.viewMode) T.viewMode = "tree";
        if (!T.mapCorner) T.mapCorner = "br";
        if (T.mapOpen === undefined) T.mapOpen = true;
        if (T.paneOpen === undefined) T.paneOpen = true;
        if (!T.zoom) T.zoom = { z: 1, sx: 0, sy: 0 };
    }
    function saveViewPrefs() {
        try { localStorage.setItem("h3clipplan.view", JSON.stringify({ mode: T.viewMode, mapCorner: T.mapCorner, mapOpen: T.mapOpen, paneOpen: T.paneOpen })); } catch (_) { /* ignore */ }
    }
    function viewBar() {
        return h("div", { class: "tk-viewbar" },
            h("span", { class: "tabs" },
                h("button", { class: T.viewMode === "tree" ? "on" : "", onclick: () => { T.viewMode = "tree"; saveViewPrefs(); renderTakes(); } }, _t("takes.tree")),
                h("button", { class: T.viewMode === "columns" ? "on" : "", onclick: () => { T.viewMode = "columns"; saveViewPrefs(); renderTakes(); } }, _t("takes.columns"))),
            h("button", { class: "small", onclick: () => fitView() }, _t("takes.fit")),
            h("button", { class: "small", onclick: () => setZoom(1) }, "100 %"),
            h("span", { class: "hint", id: "tkZoomLabel" }, `${Math.round(T.zoom.z * 100)} %`),
            h("span", { class: "hint" }, _t("takes.wheel_up_down_shift_wheel_zoom")),
            h("span", { style: "flex:1" }));
    }
    // the viewport scrolls natively: vertical scrollbar only, horizontal by dragging (clamped by the browser)
    function viewParts() {
        const vp = document.querySelector("#takesView .tk-viewport");
        return vp ? { vp, sizer: vp.querySelector(".tk-sizer"), canvas: vp.querySelector(".tk-canvas") } : null;
    }
    function applyView(canvas, keep) {
        const parts = viewParts();
        if (!parts || !T.graphSize) return;
        const { vp, sizer } = parts;
        const c = canvas || parts.canvas;
        const z = T.zoom.z, [w, hh] = T.graphSize;
        c.style.transform = `scale(${z})`;
        const topLayer = parts.vp.querySelector(".tk-topcanvas");
        if (topLayer) topLayer.style.transform = `scale(${z})`;
        sizer.style.width = `${Math.ceil(w * z)}px`;
        sizer.style.height = `${Math.ceil(hh * z)}px`;
        if (keep !== false) { vp.scrollLeft = T.zoom.sx || 0; vp.scrollTop = T.zoom.sy || 0; }
        T.zoom.sx = vp.scrollLeft; T.zoom.sy = vp.scrollTop;
        stickPanes(c);
        placeMinimap();
        if (T.graph) drawMinimap();
        const label = document.getElementById("tkZoomLabel");
        if (label) label.textContent = `${Math.round(z * 100)} %`;
    }
    // keeps the frozen panes in view: they move by the scroll, in canvas units (the canvas is scaled by the zoom)
    function stickPanes(canvas) {
        const parts = viewParts();
        if (!parts) return;
        const { vp } = parts, c = canvas || parts.canvas, z = T.zoom.z || 1;
        if (!c) return;
        const x = vp.scrollLeft / z;
        for (const el of [...c.querySelectorAll(".tk-stick-x"), ...vp.querySelectorAll(".tk-topcanvas .tk-stick-x")]) el.style.transform = x ? `translateX(${x}px)` : "";
    }
    function setZoom(z) { T.zoom = { z, sx: 0, sy: 0 }; applyView(); }
    function fitView() {
        const parts = viewParts();
        if (!parts || !T.graphSize) return;
        setZoom(Math.max(0.25, Math.min(1, parts.vp.clientWidth / T.graphSize[0])));
    }
    function bindViewport(vp) {
        vp.addEventListener("scroll", () => { T.zoom.sx = vp.scrollLeft; T.zoom.sy = vp.scrollTop; stickPanes(); mapFrame(); });
        vp.addEventListener("wheel", (e) => {
            if (!e.shiftKey) return;              // the wheel scrolls up and down; Shift + wheel zooms
            e.preventDefault();
            const delta = e.deltaY || e.deltaX;   // some browsers turn Shift + wheel into a horizontal delta
            if (!delta) return;
            const rect = vp.getBoundingClientRect();
            const mx = e.clientX - rect.left, my = e.clientY - rect.top;
            const z = T.zoom.z;
            const z2 = Math.max(0.25, Math.min(2, z * (delta < 0 ? 1.12 : 1 / 1.12)));
            if (z2 === z) return;
            const cx = (vp.scrollLeft + mx) / z, cy = (vp.scrollTop + my) / z;
            T.zoom.z = z2;
            applyView(null, false);
            vp.scrollLeft = cx * z2 - mx;
            vp.scrollTop = cy * z2 - my;
            T.zoom.sx = vp.scrollLeft; T.zoom.sy = vp.scrollTop;
            mapFrame();
        }, { passive: false });
        // a drag must not end as a click (choose a take, generate, + prise…)
        vp.addEventListener("click", (e) => { if (T.dragged) { e.stopPropagation(); e.preventDefault(); } }, true);
        vp.addEventListener("mousedown", (e) => {
            if (e.button !== 0 || e.target.closest("input, textarea, select")) return;
            if (e.offsetX > vp.clientWidth && e.target === vp) return;   // vertical scrollbar
            e.preventDefault();   // no text or image selection while dragging
            const start = { x: e.clientX, sx: vp.scrollLeft };
            T.dragged = false;
            const move = (ev) => {
                const dx = ev.clientX - start.x;
                if (!T.dragged && Math.abs(dx) <= 4) return;
                if (!T.dragged) { T.dragged = true; vp.classList.add("dragging"); }
                vp.scrollLeft = start.sx - dx;   // horizontal only; the browser clamps at both ends
                stickPanes();
            };
            const up = () => {
                window.removeEventListener("mousemove", move);
                window.removeEventListener("mouseup", up);
                vp.classList.remove("dragging");
                setTimeout(() => { T.dragged = false; }, 0);
            };
            window.addEventListener("mousemove", move);
            window.addEventListener("mouseup", up);
        });
    }

    // ---------------------------------------------------------------- minimap (overview of the whole graph)
    const MAP_W = 260, MAP_H = 160;
    const CORNERS = { tl: _t("takes.top_left"), tr: _t("takes.top_right"), bl: _t("takes.bottom_left"), br: _t("takes.bottom_right") };
    function minimap() {
        if (!T.mapOpen) {
            return h("button", { class: `tk-map-icon c-${T.mapCorner}`, title: _t("takes.show_the_overview"), onclick: () => { T.mapOpen = true; saveViewPrefs(); renderTakes(); } }, "▦");
        }
        const cv = h("canvas", { class: "tk-map-canvas" });
        const frame = h("div", { class: "tk-map-frame" });
        const menu = h("div", { class: "tk-map-menu", hidden: true },
            h("div", { class: "hint" }, "position :"),
            ...Object.entries(CORNERS).map(([k, label]) => h("button", { class: `small ${T.mapCorner === k ? "on" : ""}`, onclick: (e) => { e.stopPropagation(); T.mapCorner = k; saveViewPrefs(); renderTakes(); } }, label)));
        const box = h("div", { class: `tk-map c-${T.mapCorner}` },
            h("div", { class: "tk-map-head" },
                h("button", { class: "tk-map-btn", title: _t("takes.position_of_the_overview"), onclick: (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; } }, "⚙"),
                h("span", { class: "hint" }, _t("takes.overview")), h("span", { style: "flex:1" }),
                h("button", { class: "tk-map-btn", title: _t("takes.minimize"), onclick: (e) => { e.stopPropagation(); T.mapOpen = false; saveViewPrefs(); renderTakes(); } }, "✕")),
            h("div", { class: "tk-map-body" }, cv, frame), menu);
        const body = box.querySelector(".tk-map-body");
        const centre = (ev) => {
            const parts = viewParts();
            if (!parts || !T.mapScale) return;
            const r = cv.getBoundingClientRect();
            const gx = (ev.clientX - r.left) / T.mapScale, gy = (ev.clientY - r.top) / T.mapScale;
            const { vp } = parts, z = T.zoom.z;
            vp.scrollLeft = gx * z - vp.clientWidth / 2;
            vp.scrollTop = gy * z - vp.clientHeight / 2;
            T.zoom.sx = vp.scrollLeft; T.zoom.sy = vp.scrollTop;
            mapFrame();
        };
        body.addEventListener("mousedown", (e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            centre(e);
            const move = (ev) => centre(ev);
            const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
            window.addEventListener("mousemove", move);
            window.addEventListener("mouseup", up);
        });
        body.addEventListener("wheel", (e) => {
            e.preventDefault();
            const parts = viewParts();
            if (!parts) return;
            const { vp } = parts, z = T.zoom.z;
            const z2 = Math.max(0.25, Math.min(2, z * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
            if (z2 === z) return;
            const cx = (vp.scrollLeft + vp.clientWidth / 2) / z, cy = (vp.scrollTop + vp.clientHeight / 2) / z;
            T.zoom.z = z2;
            applyView(null, false);
            vp.scrollLeft = cx * z2 - vp.clientWidth / 2;
            vp.scrollTop = cy * z2 - vp.clientHeight / 2;
            T.zoom.sx = vp.scrollLeft; T.zoom.sy = vp.scrollTop;
            mapFrame();
        }, { passive: false });
        return box;
    }
    function mapColor(node) {
        if (node.kind === "ghost") return node.job.status === "error" ? H3Theme.c("#c0504d") : H3Theme.c("#e8913a");
        const res = T.resolved && T.resolved[node.index];
        if (!res) return H3Theme.c("#5a606c");
        if (res.chosen === node.record.id) return H3Theme.c("#6aa7ff");
        const state = (res.takes[node.record.id] || ["invalid"])[0];
        if (state === "invalid" || state === "stale") return H3Theme.c("#e0b400");
        return H3Theme.c("#5a606c");
    }
    function drawMinimap() {
        const cv = document.querySelector("#takesView .tk-map-canvas");
        if (!cv || !T.graph) return;
        const g = T.graph;
        const world = mapWorld();
        const s = Math.min(MAP_W / world[0], MAP_H / world[1]);
        T.mapScale = s;
        const dpr = window.devicePixelRatio || 1;
        // fixed size box, like ComfyUI: the content is scaled to fit, the box never changes
        cv.width = MAP_W * dpr; cv.height = MAP_H * dpr;
        cv.style.width = `${MAP_W}px`; cv.style.height = `${MAP_H}px`;
        const c = cv.getContext("2d");
        c.setTransform(dpr, 0, 0, dpr, 0, 0);
        c.fillStyle = H3Theme.c("#08090b"); c.fillRect(0, 0, MAP_W, MAP_H);
        c.setTransform(dpr * s, 0, 0, dpr * s, 0, 0);
        c.fillStyle = H3Theme.c("#0d0f12"); c.fillRect(0, 0, world[0], world[1]);
        c.fillStyle = H3Theme.c("#121418"); c.fillRect(0, 0, g.width, g.height);
        for (const band of g.bands || []) {
            c.globalAlpha = 0.16; c.fillStyle = band.branch.color || "#888";
            c.fillRect(0, band.y - 8, g.width, band.h + 16);
            c.globalAlpha = 1; c.fillRect(0, band.y - 8, 3 / s, band.h + 16);
        }
        const hl = T.highlight || null;
        c.lineWidth = 1.2 / s;
        for (const e of g.edges) {
            const a = g.byKey[e.from], b = g.byKey[e.to];
            if (!a || !b) continue;
            const on = hl && a.record && b.record && hl.has(a.record.id) && hl.has(b.record.id);
            c.strokeStyle = on ? H3Theme.c("#ffffff") : e.cls === "on" ? H3Theme.c("#6aa7ffaa") : H3Theme.c("#59607066");
            c.beginPath(); c.moveTo(a.x + COLW, a.y + CARD_H / 2); c.lineTo(b.x, b.y + CARD_H / 2); c.stroke();
        }
        for (const node of g.nodes) {
            c.fillStyle = mapColor(node);
            c.globalAlpha = node.kind === "take" && mapColor(node) === H3Theme.c("#5a606c") ? 0.7 : 1;
            c.fillRect(node.x, node.y, COLW, CARD_H);
            if (hl && node.record && hl.has(node.record.id)) {
                c.globalAlpha = 1; c.strokeStyle = H3Theme.c("#ffffff"); c.lineWidth = 3 / s;
                c.strokeRect(node.x, node.y, COLW, CARD_H); c.lineWidth = 1.2 / s;
            }
        }
        c.globalAlpha = 1;
        c.setLineDash([4 / s, 3 / s]); c.strokeStyle = H3Theme.c("#8a90a0"); c.lineWidth = 1 / s;
        for (const ph of g.placeholders || []) c.strokeRect(ph.x, ph.y, COLW, CARD_H);
        c.setLineDash([]);
        mapFrame();
    }
    if (typeof document !== "undefined") document.addEventListener("h3theme", () => drawMinimap());
    // what the map shows: the graph, extended to the area the screen covers at the current zoom
    function mapWorld() {
        const parts = viewParts();
        const g = T.graph;
        if (!parts) return [g.width, g.height];
        const z = T.zoom.z;
        return [Math.max(g.width, parts.vp.clientWidth / z), Math.max(g.height, parts.vp.clientHeight / z)];
    }
    function mapFrame() {
        const frame = document.querySelector("#takesView .tk-map-frame");
        const parts = viewParts();
        if (!frame || !parts || !T.mapScale || !T.graphSize) return;
        const { vp } = parts, z = T.zoom.z, s = T.mapScale;
        const x = vp.scrollLeft / z, y = vp.scrollTop / z;
        const fw = vp.clientWidth / z, fh = vp.clientHeight / z;
        Object.assign(frame.style, { left: `${x * s}px`, top: `${y * s}px`, width: `${fw * s}px`, height: `${fh * s}px` });
    }
    // keep the minimap inside the visible part, clear of the scrollbar
    function placeMinimap() {
        const parts = viewParts();
        const box = document.querySelector("#takesView .tk-map, #takesView .tk-map-icon");
        if (!parts || !box) return;
        const bar = parts.vp.offsetWidth - parts.vp.clientWidth;
        box.style.setProperty("--bar", `${bar}px`);
        const room = parts.vp.parentElement.clientHeight;
        box.classList.toggle("squeezed", box.classList.contains("tk-map") && room < 120);
    }

    // ---------------------------------------------------------------- side pane: assembled videos (Encore)
    function videoPane(p) {
        const def = defBranch();
        const exps = (T.exports || []).filter((e) => !e.removed);   // a deleted branch takes its videos away (until restored)
        const asmJobs = T.jobs.filter((j) => j.kind === "assemble" && j.status !== "done");
        if (!exps.length && !asmJobs.length) return null;
        const count = exps.length;
        if (!T.paneOpen) {
            return h("div", { class: "tk-pane folded", title: _t("takes.show_the_assembled_videos"), onclick: () => { T.paneOpen = true; saveViewPrefs(); renderTakes(); } },
                h("div", { class: "tk-pane-tab" }, _t("takes.videos_2", { count })));
        }
        const list = h("div", { class: "tk-pane-list" });
        const branches = branchesList();
        const known = new Set(branches.map((b) => b.id));
        const groups = branches.map((br) => ({ br, id: br.id }));
        if (exps.some((e) => !known.has(e.branch || def)) || asmJobs.some((j) => !known.has(j.branch || def))) groups.push({ br: { name: _t("takes.others"), color: "#888" }, id: null });
        for (const g of groups) {
            const mine = (x) => (g.id === null ? !known.has(x.branch || def) : (x.branch || def) === g.id);
            const jobs = asmJobs.filter(mine);
            const vids = exps.filter(mine).sort((a, b) => (b.created || 0) - (a.created || 0));
            if (!jobs.length && !vids.length) continue;
            list.append(h("div", { class: "tk-pane-group" }, h("i", { class: "tk-branch-dot", style: `background:${g.br.color || "#888"}` }), g.br.name || g.id));
            for (const job of jobs) list.append(paneJob(job));
            for (const ex of vids) list.append(paneVideo(ex));
        }
        const pane = h("div", { class: "tk-pane" },
            h("div", { class: "tk-pane-head" },
                h("b", {}, _t("takes.videos", { count })), h("span", { style: "flex:1" }),
                h("button", { class: "small", title: _t("takes.fold_the_panel"), onclick: () => { T.paneOpen = false; saveViewPrefs(); renderTakes(); } }, "▸")),
            list);
        list.addEventListener("scroll", () => { T.paneScroll = list.scrollTop; });
        requestAnimationFrame(() => { list.scrollTop = T.paneScroll || 0; });
        return pane;
    }
    function paneJob(job) {
        const pct = job.progress ? Math.round(100 * job.progress.value / Math.max(1, job.progress.max)) : 0;
        const live = job.status === "queued" || job.status === "running";
        return h("div", { class: `tk-pane-item tk-pane-job ${job.status}`, "data-job": job.id },
            h("div", { class: "tk-pane-thumb" }, h("span", { class: "tk-ghost-icon" }, job.status === "queued" ? "⏳" : job.status === "error" ? "✖" : "▶")),
            h("div", { class: "tk-pane-meta" }, h("div", {}, _t("takes.assembly")), h("div", { class: "hint tk-ghost-label" }, ghostLabel(job)),
                h("div", { class: "tk-progress", hidden: job.status !== "running" || null }, h("i", { style: `width:${pct}%` })),
                live ? h("button", { class: "small danger", onclick: () => cancelJob(job) }, _t("takes.cancel")) : null,
                job.status === "error" ? h("button", { class: "small", onclick: () => { T.jobs = T.jobs.filter((j) => j !== job); T.studio.removeJob(job.id).catch(() => {}); renderTakes(); } }, _t("takes.remove")) : null));
    }
    function exportTakes(ex) { return new Set(Object.values(ex.takes || {})); }
    function setHighlight(ids) {
        T.highlight = ids;
        for (const el of document.querySelectorAll("#takesView .tk-card.tk-hl")) el.classList.remove("tk-hl");
        if (ids) for (const id of ids) { const el = document.querySelector(`#takesView .tk-card[data-take="${CSS.escape(id)}"]`); if (el) el.classList.add("tk-hl"); }
        drawMinimap();
    }
    function centreOnTake(id) {
        if (T.graph && !T.graph.byKey["t:" + id]) {
            const record = Object.values(T.takes || {}).flat().find((r) => r.id === id);
            if (record && isFolded(branchOfRecord(record))) { setFolded(branchOfRecord(record), false); }
        }
        const node = T.graph && T.graph.byKey["t:" + id];
        const parts = viewParts();
        if (!node || !parts) { toast(_t("takes.this_take_is_not_shown_in")); return; }
        const { vp } = parts, z = T.zoom.z;
        vp.scrollLeft = (node.x + COLW / 2) * z - vp.clientWidth / 2;
        vp.scrollTop = (node.y + CARD_H / 2) * z - vp.clientHeight / 2;
        T.zoom.sx = vp.scrollLeft; T.zoom.sy = vp.scrollTop;
        mapFrame();
    }
    function paneVideo(ex) {
        const video = thumbVideo("x:" + ex.file, () => {
            const v = h("video", { muted: true, loop: true, playsinline: true, preload: "metadata", src: T.studio.viewUrl(ex.file) });
            v.addEventListener("loadeddata", () => { if (v.paused) v.currentTime = Math.min(0.5, (v.duration || 1) / 3); }, { once: true });
            return v;
        });
        const last = ex.takes && ex.takes[String(ex.clips)];
        return h("div", { class: "tk-pane-item", title: _t("takes.mp4_clips_1_to_click_play", { name: ex.name, clips: ex.clips }),
            onclick: () => openExport(ex),
            onmouseenter: () => { setHighlight(exportTakes(ex)); video.muted = !T.soundOnHover; video.currentTime = 0; video.play().catch(() => { video.muted = true; video.play().catch(() => {}); }); },
            onmouseleave: () => { setHighlight(null); video.pause(); video.currentTime = Math.min(0.5, (video.duration || 1) / 3); } },
            h("div", { class: "tk-pane-thumb" }, video),
            h("div", { class: "tk-pane-meta" },
                h("div", { class: "tk-pane-name" }, h("i", { class: "tk-branch-dot", style: `background:${branchColor(ex.branch || defBranch())}` }), ex.name),
                h("div", { class: "hint" }, `${whenMs(ex.created)} · clips 1–${ex.clips}`),
                last ? h("button", { class: "small", title: _t("takes.center_the_view_on_the_last"), onclick: (e) => { e.stopPropagation(); centreOnTake(last); } }, _t("takes.takes")) : null));
    }
    loadViewPrefs();
    window.addEventListener("resize", () => { if (document.querySelector("#takesView .tk-map-canvas")) drawMinimap(); });

    function dependents(job) {
        const out = [];
        const walk = (j) => {
            for (const d of T.jobs) {
                if (d.kind === "clip" && d.clip === j.clip + 1 && d.parentToken === j.token && (d.status === "queued" || d.status === "running") && !out.includes(d)) {
                    out.push(d);
                    walk(d);
                }
            }
        };
        walk(job);
        return out;
    }
    async function cancelJob(job) {
        const deps = dependents(job);
        let targets = [job];
        if (deps.length) {
            if (!await H3Dialog.confirm(_t("takes.waiting_generation_s_continue_this_take", { length: deps.length, v1: [...new Set(deps.map((d) => d.clip))].join(", ") }))) return;
            targets = [job, ...deps];
        }
        try { applyStudioJobs(await T.studio.cancel(targets.map((j) => j.id))); } catch (e) { alert(e.message); }
        T.jobs = T.jobs.filter((j) => !targets.includes(j));
        renderTakes();
    }

    // wanted: {refs: {name: {image?: digest|null, voice?: digest|null}}, size?: [w, h]}
    function conflicting(wanted) {
        const hit = [];
        const free = H3.mode(plan()) === "free";
        for (const [i, list] of Object.entries(T.takes)) {
            for (const r of list) {
                let bad = false;
                if (wanted.branch && branchOfRecord(r) !== wanted.branch) continue;
                if (wanted.size && (r.width !== wanted.size[0] || r.height !== wanted.size[1])) bad = true;
                if (wanted.refSize && ((r.studio && r.studio.ref_image_size) || T.studio.legacyRefSize()) !== wanted.refSize) bad = true;
                if ("song" in wanted && r.studio && "song" in r.studio && (r.studio.song ?? null) !== (wanted.song ?? null)) bad = true;
                for (const [name, want] of Object.entries(wanted.refs || {})) {
                    const had = ((r.studio && r.studio.refs) || {})[name];
                    if (!had) continue;                       // this take does not use this reference
                    if ("image" in want && (had.image ?? null) !== (want.image ?? null)) bad = true;
                    if (free && "voice" in want && (had.voice ?? null) !== (want.voice ?? null)) bad = true;
                }
                if (bad) hit.push({ clip: +i, id: r.id });
            }
        }
        // add every take built on them (continuations, at any depth)
        const ids = new Set(hit.map((x) => x.id));
        for (let i = 2; i <= plan().clips.length; i++) {
            for (const r of T.takes[i] || []) if (!ids.has(r.id) && r.parent && ids.has(r.parent)) { ids.add(r.id); hit.push({ clip: i, id: r.id }); }
        }
        return hit;
    }
    async function resetConflicts(list, why, branch) {
        // only the jobs of this branch matter: the others use their own references, song and size
        if (T.jobs.some((j) => (j.status === "queued" || j.status === "running") && (branch == null || (j.branch || defBranch()) === branch))) {
            alert(_t("takes.generations_of_this_branch_are_running"));
            return false;
        }
        const alive = list.filter((x) => (T.resolved?.[x.clip]?.takes?.[x.id] || [""])[0] !== "invalid");
        if (!alive.length) return true;
        const clips = [...new Set(alive.map((x) => x.clip))].sort((a, b) => a - b);
        return await H3Dialog.confirm(_t("takes.take_s_clip_will_be_invalidated", { why, length: alive.length, v2: clips.length > 1 ? "s" : "", v3: clips.join(", ") }) +
            _t("takes.putting_the_old_value_back_makes"));
    }
    // returns true when the change can be applied
    async function changeReference(branch, name, kind, path) {
        const free = H3.mode(plan()) === "free";
        if (kind === "voice" && !free) return true;
        await studioEnsureTakes();
        const mine = (r) => !branch || branchOfRecord(r) === branch;
        if (!Object.values(T.takes).some((l) => l.some((r) => mine(r) && ((r.studio && r.studio.refs) || {})[name]))) return true;
        const d = path ? await T.studio.digests(kind === "image" ? [path] : [], kind === "voice" ? [path] : []) : null;
        const value = path ? d[kind === "image" ? "images" : "voices"][path] : null;
        const list = conflicting({ branch, refs: { [name]: { [kind]: value } } });
        return resetConflicts(list, _t("takes.changing_of_makes_the_takes_that", { v0: kind === "image" ? _t("takes.the_picture") : _t("takes.the_voice"), name }), branch);
    }
    async function changeSong(branch, path) {
        await studioEnsureTakes();
        const sha = path ? await T.studio.songSha(path) : null;
        const list = conflicting({ branch, song: sha });
        return resetConflicts(list, _t("takes.changing_the_branch_song_makes_the"), branch);
    }
    async function changeSize(branch, w, hh) {
        await studioEnsureTakes();
        const list = conflicting({ branch, size: [w, hh] });
        return resetConflicts(list, _t("takes.the_existing_takes_were_made_at", { w, hh }), branch);
    }
    async function changeRefSize(branch, value) {
        await studioEnsureTakes();
        const list = conflicting({ branch, refSize: value });
        return resetConflicts(list, _t("takes.the_existing_takes_were_made_with", { value }), branch);
    }


    function statusText(nTakes) {
        let text = _t("takes.project_take_s", { project: plan().project, nTakes });
        if (T.jobs.some((j) => j.status === "queued" || j.status === "running")) text += T.socketOpen ? _t("takes.live_tracking") : _t("takes.tracking_by_polling_comfyui");
        if (T.loading) text += _t("takes.reading");
        return text;
    }

    // ---------------------------------------------------------------- Encore
    // api: {listTakes, saveSelection, deleteTakes, generate, jobs, cancel, removeJob, savePlan, settings,
    //       digests, viewUrl, openRefs, openSettings, objectInfo}
    function useStudio(api) {
        T.studio = api;
        T.server = {
            takes: () => api.listTakes(),
            saveSelection: (_f, sel) => api.saveSelection(sel),
            deleteTakes: (_f, list) => api.deleteTakes(list),
            viewUrl: (path) => api.viewUrl(path),
            objectInfo: () => api.objectInfo(),
        };
        T.planFile = "plan.json";
        setInterval(() => {
            const active = T.jobs.some((j) => j.status === "queued" || j.status === "running");
            if (active || (!$("takesView").hidden && Date.now() - (T.lastPoll || 0) > 5000)) studioPoll();
        }, 1000);
    }
    function resetProject() {
        Object.assign(T, { thumbs: new Map(), takes: {}, previewInfo: {}, fileSelection: {}, pick: {}, resolved: null, fingerprints: null, jobs: [], exports: [],
            takesProject: null, settings: null, settingsProject: null, error: null, seenDone: new Set() });
        studioPoll();
    }
    async function studioEnsureTakes() {
        if (T.takesProject !== plan().project) await serverScan();
    }
    let selTimer = null;
    function studioSaveSelection() {
        clearTimeout(selTimer);
        const pick = { ...chosenMap(), branch: T.pickBranch || T.resolved?.branch || null };
        selTimer = setTimeout(() => T.studio.saveSelection(pick).then(() => { T.fileSelection = { ...pick }; })
            .catch((e) => toast(_t("takes.selection_not_saved", { message: e.message }))), 250);
    }
    let pollTimer = null, polling = false;
    function studioPollSoon(ms) { clearTimeout(pollTimer); pollTimer = setTimeout(studioPoll, ms || 300); }
    function applyStudioJobs(data) {
        const before = new Map(T.jobs.map((j) => [j.id, j]));
        T.socketOpen = !!data.socket;
        T.jobs = (data.jobs || []).filter((j) => j.status !== "done" || !T.seenDone.has(j.id)).map((j) => {
            const old = before.get(j.id);
            return old ? Object.assign(old, j) : j;
        });
        return T.jobs;
    }
    async function studioPoll() {
        if (!T.studio || polling || !plan()) return;      // before useStudio(): nothing to ask yet
        polling = true;
        T.lastPoll = Date.now();
        try {
            const before = JSON.stringify(T.jobs.map((j) => [j.id, j.status, j.error, j.suspended, j.dispatched])) + T.queuePaused;
            const data = await T.studio.jobs();
            T.queuePaused = !!(data && data.paused);
            applyStudioJobs(data);
            const built = T.jobs.filter((j) => j.kind === "assemble" && j.status === "done" && !T.seenDone.has(j.id));
            if (built.length) {
                for (const j of built) T.seenDone.add(j.id);
                T.jobs = T.jobs.filter((j) => !built.includes(j));
                try { T.exports = (await T.studio.exports()).exports || []; } catch (_) { /* next time */ }
                toast(_t("takes.assembled_video_2", { v0: built.map((j) => j.export).join(", ") }));
                renderTakes();
                return;
            }
            const done = T.jobs.filter((j) => j.status === "done" && j.take && !T.seenDone.has(j.id));
            if (done.length) {
                for (const j of done) T.seenDone.add(j.id);
                T.jobs = T.jobs.filter((j) => j.status !== "done");
                await serverScan();
                // a new take is chosen when it belongs to the branch of the selection (or there is none yet)
                for (const j of done) {
                    const b = branchOfRecord(recordOf(j.clip, j.take));
                    if ((!T.resolved || !T.resolved.branch || T.resolved.branch === b) && !isFolded(b)) choose(j.clip, j.take, true);
                }
                return;
            }
            const after = JSON.stringify(T.jobs.map((j) => [j.id, j.status, j.error, j.suspended, j.dispatched])) + T.queuePaused;   // a new step only changes labels
            if (before !== after) renderTakes();
            else for (const j of T.jobs) if (j.status === "running" || j.status === "queued") updateGhost(j);
        } catch (_) { /* the Studio is restarting: try again */ }
        finally { polling = false; }
    }

    function onShow() {
        if (T.shownProject !== plan().project || T.shownClips !== plan().clips.length) { T.resolved = null; T.shownProject = plan().project; T.shownClips = plan().clips.length; }
        if (T.server && plan() && H3.framesLegal(plan())) serverScan(); else recompute();
    }
    window.H3Takes = { render: renderTakes, recompute, rescan, onShow, state: T, generate,
        useStudio, resetProject, zoomable, activeBranch: () => (T.resolved && T.resolved.branch) || null, hideZoom, changeReference, changeSize, changeRefSize, changeSong, branchOfRecord, openExport, refresh: () => studioPoll() };
})();
