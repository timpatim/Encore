// ---------------------------------------------------------------------------------------------
// Encore - "Takes" tab: the takes of every clip, one band per branch, as a dependency graph.
// Encore's server holds the takes and drives ComfyUI: this tab only asks it (see useStudio).
// ---------------------------------------------------------------------------------------------
(() => {
    const COLW = 196, CARD_H = 158, TOP = 54, LEFT = 16;
    const T = {
        takes: {}, fileSelection: {}, pick: {}, fingerprints: null, resolved: null, soundOnHover: false, loading: false,
        server: null, settings: null, jobs: [], previewInfo: {}, planFile: null, socketOpen: false, error: null,
        studio: null, seenDone: new Set(),          // studio: Encore's API, given by useStudio()
    };
    const ed = () => window.H3Editor;
    // the plan of the selected twig (Encore), else the plan in the editor
    const plan = () => (T.studio && T.studio.twig && T.studio.twig() && T.studio.twig().plan) || ed().state.plan;
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
        T.fingerprints = plan() ? {} : null;     // (no fingerprints any more: kept as "the takes can be shown")
        T.resolved = plan() ? resolveWith(T.pick) : null;
        renderTakes();
    }

    // the take before a take in time: the one it continues, or the one it was timed after (new scene)
    function predOf(r) { return (r && ((r.studio && r.studio.predecessor) || r.parent)) || null; }
    // a take can come right after prevId: made after it, or a new scene (✂) that starts there at the same moment
    // (the server lists them: T.fits)
    // the clips a duplicated branch takes over from another one (by reference): [take ids of clips 1..k], null for a
    // clip left free between two portions (0.49)
    function baseOf(branch) { return (((branchesList().find((b) => b.id === branch) || {}).base) || {}).takes || []; }
    // 0.49: the take of a branch's master line for a clip (generations waiting included), the oldest one
    function lineTakeOf(branch, index) {
        const own = (T.takes[index] || []).filter((x) => branchOfRecord(x) === branch && x.studio && x.studio.line)
            .sort((a, b) => (a.saved_at || 0) - (b.saved_at || 0));
        if (own.length) return own[0].id;
        const j = T.jobs.find((x) => x.kind === "clip" && Number(x.clip) === Number(index) && (x.branch || defBranch()) === branch && x.record
            && x.record.studio && x.record.studio.line && ["queued", "running"].includes(x.status));
        return j ? j.take_id : null;
    }
    // 0.49: a clip taken over right after a clip left free follows, in that branch, its own take of that clip (the
    // selected one, otherwise the one of its master line)
    function holePred(r, index, branch) {
        if (!branch || !r || index < 2) return null;
        const base = baseOf(branch);
        if (base[index - 1] !== r.id || base[index - 2]) return null;
        const sel = T.resolved && T.resolved.branch === branch && T.resolved[index - 1] && T.resolved[index - 1].chosen;
        if (sel && branchOfRecord(recordOf(index - 1, sel)) === branch) return sel;
        return lineTakeOf(branch, index - 1);
    }
    function inBranch(r, branch) { return !!r && (branchOfRecord(r) === branch || baseOf(branch).includes(r.id)); }
    function linkOk(r, prevId) { return !!r && (predOf(r) === prevId || ((T.fits || {})[r.id] || []).includes(prevId)); }
    // the take before a take in the twig shown: a new scene hangs on the take selected before it when it fits there
    function effPred(r, index, branch = null) {
        const hole = holePred(r, index, branch);
        if (hole) return hole;
        const sel = T.resolved && T.resolved[index - 1] && T.resolved[index - 1].chosen;
        return sel && sel !== predOf(r) && linkOk(r, sel) ? sel : predOf(r);
    }
    // chantier A: a take never becomes invalid. The selection is a twig (a chain of predecessors from clip 1) in
    // one branch; a take is "ok" when it follows the take chosen for the clip before, "other" otherwise.
    function twigResolve(sel, branch) {
        const bySaved = (a, b) => (a.saved_at || 0) - (b.saved_at || 0);
        let active = branch || null;
        if (!active && sel && sel[1]) active = branchOfRecord(recordOf(1, sel[1]));
        if (!active) {
            const c1 = [...(T.takes[1] || [])].sort(bySaved).pop();
            const any = Object.values(T.takes || {}).flat()[0];
            active = c1 ? branchOfRecord(c1) : any ? branchOfRecord(any) : defBranch();
        }
        const out = { branch: active };
        const last = Math.max(0, (plan()?.clips || []).length, ...Object.keys(T.takes || {}).map(Number));
        let prev = null, broken = false;
        for (let i = 1; i <= last; i++) {
            const states = {};
            for (const r of [...(T.takes[i] || [])].sort(bySaved)) {
                if (!inBranch(r, active)) states[r.id] = ["other", _t("takes.other_branch")];
                else if (i > 1 && !linkOk(r, prev) && !holeOk(r, i, prev, active)) states[r.id] = ["other", _t("takes.built_on_another_take_of_the")];
                else states[r.id] = ["ok", ""];
            }
            // a generation still waiting can be in the selection too (its take id is known at launch)
            for (const j of T.jobs) {
                if (j.kind !== "clip" || Number(j.clip) !== i || !j.record || !["queued", "running"].includes(j.status)) continue;
                states[j.take_id] = inBranch(j.record, active) && (i === 1 || linkOk(j.record, prev)) ? ["ok", ""] : ["other", ""];
            }
            const want = sel && sel[i];
            const chosen = !broken && want && states[want] && states[want][0] === "ok" ? want : null;
            if (!chosen) broken = true;
            out[i] = { chosen, takes: states };
            prev = chosen;
        }
        return out;
    }
    // 0.49: a clip taken over after a clip left free fits after any take of that clip made in the branch
    function holeOk(r, i, prev, branch) {
        const base = baseOf(branch);
        if (!prev || i < 2 || base[i - 1] !== r.id || base[i - 2]) return false;
        const p = recordOf(i - 1, prev);
        return !!p && branchOfRecord(p) === branch;
    }
    function resolveWith(pick) {
        const resolve = (sel, branch) => twigResolve(sel, branch);
        const res = resolve(pick, T.pickBranch);
        if (!res.branch || !isFolded(res.branch)) return res;
        // a folded branch never holds the selection: it goes to the first twig of the first unfolded branch
        const target = (branchesList().find((b) => !isFolded(b.id)) || {}).id || null;
        if (!target) return res;
        const first = firstTwig(target);
        T.pickBranch = target;
        T.pick = first;
        if (T.fileSelection) setTimeout(studioSaveSelection, 0);   // once T.resolved holds the new result
        return resolve(first, target);
    }
    // the first twig of a branch: the top line of its tree (the clips taken over, then the oldest take that follows)
    function firstTwig(branch) {
        const pick = {};
        const base = baseOf(branch);
        const last = Math.max(0, (plan()?.clips || []).length, ...Object.keys(T.takes || {}).map(Number));
        for (let i = 1; i <= last; i++) {
            const states = twigResolve(pick, branch)[i]?.takes || {};
            const ok = Object.keys(states).filter((id) => states[id][0] === "ok");
            if (!ok.length) break;
            const rank = (id) => { const r = recordOf(i, id); return base.includes(id) ? -1 : r && r.saved_at ? r.saved_at : Infinity; };
            pick[i] = ok.sort((a, b) => rank(a) - rank(b))[0];
        }
        return pick;
    }
    const unusable = (state) => state === "stale" || state === "invalid";
    function chosenMap() {
        const out = {};
        if (!T.resolved) return out;
        for (const [i, v] of Object.entries(T.resolved)) if (v.chosen) out[+i] = v.chosen;
        return out;
    }

    // ------------------------------------------------------------------ choosing
    function recordOf(index, id) {
        return (T.takes[index] || []).find((r) => r.id === id)
            || ((T.jobs.find((j) => j.kind === "clip" && Number(j.clip) === Number(index) && j.take_id === id) || {}).record);
    }
    function recordAny(id) { for (const list of Object.values(T.takes)) for (const r of list) if (r.id === id) return r; return null; }
    const hasPreview = (id) => !!T.previewInfo[id];
    function choose(index, id, quiet, inBand) {
        const state = T.resolved?.[index]?.takes?.[id];
        if (!state) return;
        let pick = chosenMap();
        const b = inBand || branchOfRecord(recordOf(index, id));
        if (b !== T.resolved?.branch) pick = {};
        T.pickBranch = b;
        pick[index] = id;
        // the twig through this take: its predecessors, and after it the takes chosen that still follow it
        let i = index, record = recordOf(index, id);
        while (i > 1 && record && predOf(record)) {
            // a new scene that fits after the take already chosen before it keeps that one (and what is before it)
            if (pick[i - 1] && pick[i - 1] !== predOf(record) && linkOk(record, pick[i - 1])) break;
            pick[i - 1] = predOf(record);
            record = recordOf(i - 1, pick[i - 1]);
            i--;
        }
        for (let k = index + 1; pick[k]; k++) {
            const r = recordOf(k, pick[k]);
            if (!linkOk(r, pick[k - 1])) { for (let m = k; pick[m]; m++) delete pick[m]; break; }
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
        const video = h("video", { controls: true, autoplay: true, loop: true, style: "width:100%;max-height:62vh;background:#000;border-radius:6px" });
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
            if (listing.twig && T.studio.setTwig) T.studio.setTwig(listing.twig);
            T.fits = listing.fits || {};
            T.masters = listing.masters || {};
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

    // a generation without the launch panel: {after, planFrom, entry, seed, branch, loras, upscaleSettings, editInstruction}
    async function generate(clipIndex, opts = {}) {
        try {
            const job = await T.studio.generate({ clip: clipIndex, after: opts.after || null, plan_from: opts.planFrom || null,
                entry: opts.entry || null, seed: opts.seed ?? null, branch: opts.branch || null, loras: opts.loras ?? null,
                upscale_settings: opts.upscaleSettings || null, edit_instruction: opts.editInstruction ?? null, line: !!opts.line });
            if (!T.jobs.some((j) => j.id === job.id)) T.jobs.push(job);
            studioPollSoon(300);
            renderTakes();
            return job;
        } catch (e) {
            alert(_t("takes.cannot_start_the_generation", { v0: e.message }));
            return null;
        }
    }
    // the generation settings a take was made with (LoRA and upscale), to make another one alike
    function takeSettings(record) {
        const st = (record && record.studio) || {};
        return { loras: st.extra_loras || [], upscaleSettings: st.upscale ? { ...(st.upscale.settings || {}), enabled: true } : { enabled: false } };
    }
    // the launch panel (plan_launch.js): « new take » of a take (fork), or the clip after a take (or clip 1)
    function openLaunch(opts) {
        if (window.H3Launch) window.H3Launch.open({ ...opts, takesState: T });
    }
    // a take the band takes over from another branch (0.48.2): the new take is a variant in that band's branch
    // after: the take before it in that band (0.49: a clip taken over after a clip left free)
    function launchFork(index, record, band = null, after = undefined) { openLaunch({ mode: "fork", index, record, after: after !== undefined ? after : effPred(record, index, band), branch: band || branchOfRecord(record) }); }
    function launchNext(index, after, branch) { openLaunch({ mode: "next", index, after, branch }); }

    async function assemble(leafClip, leafId, band = null) {
        try {
            await T.studio.savePlan();
            const job = await T.studio.assemble(leafClip, leafId, band);
            if (!T.jobs.some((j) => j.id === job.id)) T.jobs.push(job);
            toast(_t("takes.assembly_added", { index: leafClip }));
            studioPollSoon(300);
            renderTakes();
        } catch (e) {
            alert(_t("takes.cannot_start_the_assembly", { v0: e.message }));
        }
    }

    // ◎ : the generation running in this project, brought to the middle of the view (its branch unfolded)
    function runningClip() { return T.jobs.find((j) => j.kind === "clip" && j.status === "running") || null; }
    function centreOnRunning() {
        const job = runningClip();
        if (!job) return;
        const branch = job.branch || defBranch();
        if (isFolded(branch)) setFolded(branch, false);
        const node = T.graph && T.graph.byKey["g:" + job.id];
        const parts = viewParts();
        if (!node || !parts) return;
        const { vp } = parts, z = T.zoom.z;
        vp.scrollLeft = (node.x + COLW / 2) * z - vp.clientWidth / 2;
        vp.scrollTop = (node.y + CARD_H / 2) * z - vp.clientHeight / 2;
        T.zoom.sx = vp.scrollLeft; T.zoom.sy = vp.scrollTop;
        stickPanes(); mapFrame();
        const card = document.querySelector(`#takesView [data-job="${CSS.escape(job.id)}"]`);
        if (card) { card.classList.remove("tk-flash"); void card.offsetWidth; card.classList.add("tk-flash"); }
    }

    // --------------------------------------------------------------- progress
    function updateGhost(job) {
        const node = document.querySelector(`[data-job="${job.id}"]`);
        if (!node && job.kind === "assemble") {   // side pane folded: only the label of the top bar changes
            const a = document.getElementById("tkAssembleState");
            if (a && job.status === "running") a.textContent = _t("takes.assembly_state", { state: ghostLabel(job) });
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
        if (job.kind === "assemble") { const a = document.getElementById("tkAssembleState"); if (a && job.status === "running") a.textContent = _t("takes.assembly_state", { state: ghostLabel(job) }); }
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
        if (index === 1 && plan().start_video) return entry && entry.continue ? _t("takes.plan_continues_video", { ref: plan().start_video.ref }) : _t("takes.plan_new_scene");
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
    // what a clip of the plan (v7) says: its subjects with their pictures and settings, its anchors, its texts; the
    // definitions are the clip's own when it was generated (defs), otherwise the plan's
    function clipDetails(entry, p, index, other) {
        if (!entry) return [];
        const defs = H3.definitions(p, entry);
        const url = (label) => { const f = defs.files[label]; return f && f.file ? T.studio.viewUrl(f.file) : null; };
        const names = H3.clipSubjects(p, entry, index);
        const uses = Object.fromEntries((entry.subjects || []).filter((u) => u && u.name).map((u) => [u.name, u]));
        const subjects = names.map((n) => {
            const s = defs.subjects[n] || {};
            const u = uses[n] || {};
            return h("div", { class: "tk-plan-refcell" },
                h("div", { class: "tk-plan-refpair" }, ...(s.pictures || []).map((pic) => refThumb(url(pic.file), `@${n} · ${pic.role || ""}`))),
                h("div", {}, h("b", {}, "@" + n), h("span", { class: "hint" }, ` ${_t("sx.kind_" + (s.kind || "person"))}`)),
                h("div", { class: "hint" }, s.description || ""),
                h("div", { class: "hint" }, _t("sx.keep_" + (u.keep || "identical")) + (s.voice ? ` · 🎙 ${_t("sx.voice_keep_" + (u.voice_keep || "timbre"))}` : "")
                    + (u.note ? ` · ${u.note}` : "")));
        });
        const a = entry.anchors || {};
        const anchors = [[_t("sx.anchor_first"), a.first], ...(a.keyframes || []).map((k) => [`${_t("sx.anchor_keyframe")} ${k.at} s`, k.file]), [_t("sx.anchor_last"), a.last]]
            .filter(([, f]) => f).map(([label, f]) => h("div", { class: "tk-plan-refcell" }, refThumb(url(f), label), h("div", { class: "hint" }, label)));
        const text = (key) => {
            const mine = entry[key] || "", theirs = other ? other[key] || "" : mine;
            return mine !== theirs ? diffNode(wordDiff(mine, theirs)) : h("div", { class: "tk-plan-text" }, mine || "—");
        };
        return [
            planRow(_t("takes.plan_subjects"), subjects.length ? h("div", { class: "tk-plan-refs" }, subjects) : "—"),
            anchors.length ? planRow(_t("sx.anchors"), h("div", { class: "tk-plan-refs" }, anchors)) : null,
            h("div", { class: "tk-plan-prompt" },
                ...[["summary", "sx.summary"], ["description", "sx.description"], ["soundscape", "sx.soundscape"], ["music", "sx.music"]].map(([k, label]) =>
                    h("div", { class: "tk-plan-sec" }, h("div", { class: "tk-plan-sec-name" }, _t(label)), text(k))),
                entry.prompt_override ? h("div", { class: "tk-plan-sec changed" }, h("div", { class: "tk-plan-sec-name" }, _t("sx.override_title")),
                    h("div", { class: "tk-plan-text" }, entry.prompt_override)) : null),
        ];
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
        const lines = linesText(clip, free);
        const body = h("div", { class: "tk-plan" },
            planRow(_t("takes.plan_name"), h("b", {}, `${index}. ${clip.name || ""}`)),
            planRow(_t("takes.plan_length"), framesText(clip.frames)),
            planRow(_t("takes.plan_link"), continueText(clip, index)),
            row.end ? planRow(_t("takes.plan_in_video"), (() => {
                const first = H3.finalStart(p), shown = index > 1 || H3.startVideo(p) ? Math.max(row.visible, first) : 0;
                return `${clipLength(shown - first) || "0"} → ${clipLength(row.end - first)}`;
            })()) : null,
            ...clipDetails(clip, p, index, null),
            planRow(free ? _t("takes.plan_lines") : _t("takes.plan_lyrics"), h("div", { class: "tk-plan-text" }, lines || "—")),
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
        // chantier A: the portion of plan of the take, as it was made (there is no « plan now » to compare with)
        const then = info.snapshot, now = info.snapshot;
        const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
        const cmpRow = (label, a, b, fmt = (v) => v ?? "—") => {
            const diff = then && !same(a, b);
            return h("div", { class: `tk-plan-row${diff ? " changed" : ""}` }, h("label", {}, label),
                h("div", {}, then ? fmt(a) : "—", diff ? h("div", { class: "tk-plan-now" }, _t("takes.plan_now"), fmt(b)) : null));
        };
        const source = !then ? _t("takes.plan_source_unknown") : info.job ? _t("takes.plan_source_job") : _t("takes.plan_source_record");
        const fullSame = true;
        const shift = !free && info.raw_start != null && info.now_raw_start != null && info.raw_start !== info.now_raw_start;
        const body = h("div", { class: "tk-plan" },
            h("div", { class: "hint", style: "margin-bottom:8px" }, head),
            h("div", { class: "tk-plan-banner" }, source),
            cmpRow(_t("takes.plan_name"), then && then.name, now && now.name),
            cmpRow(_t("takes.plan_length"), then && then.frames, now && now.frames, framesText),
            cmpRow(_t("takes.plan_link"), then && !!then.continue, now && !!now.continue, (v) => continueText({ continue: v }, index)),
            shift ? h("div", { class: "tk-plan-row changed" }, h("label", {}, _t("takes.plan_song_window")),
                h("div", {}, _t("takes.plan_song_shift", { then: clipLength(info.raw_start) || "0", now: clipLength(info.now_raw_start) || "0" }))) : null,
            ...clipDetails(then, p, index, null),
            cmpRow(free ? _t("takes.plan_lines") : _t("takes.plan_lyrics"), linesText(then, free), linesText(now, free), (v) => h("div", { class: "tk-plan-text" }, v || "—")),
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
        // a branch name being typed is not thrown away by a redraw (the queue is polled): it comes after
        if (document.activeElement && document.activeElement.classList.contains("tk-band-name") && document.activeElement.closest("#takesView")) { T.renderLater = true; return; }
        hideZoom();
        const box = $("takesView");
        if (!box || box.hidden) return;
        box.innerHTML = "";
        const p = plan();
        keepOneUnfolded();
        // a resolution computed for another plan (another number of clips) is useless
        if (T.resolved && !p.clips.every((_c, k) => T.resolved[k + 1])) T.resolved = null;
        const nTakes = Object.values(T.takes).reduce((a, l) => a + l.length, 0);
        const bar = h("div", { class: "tk-bar" },
            h("button", { onclick: rescan }, _t("takes.refresh")),
            h("label", { class: "tk-check" }, h("input", { type: "checkbox", checked: T.soundOnHover || null, onchange: (e) => { T.soundOnHover = e.target.checked; } }), _t("takes.sound_on_hover")),
            h("span", { class: "tk-status" }, statusText(nTakes)),
            h("span", { style: "flex:1" }),
            h("button", { class: "tk-to-running", onclick: centreOnRunning, disabled: !runningClip() || null,
                title: runningClip() ? _t("takes.to_running_title") : _t("takes.to_running_none") }, _t("takes.to_running")));
        box.append(bar);
        if (T.error) { box.append(h("div", { class: "empty" }, h("p", {}, _t("takes.error_2", { error: T.error })), h("button", { onclick: rescan }, _t("takes.try_again")))); return; }
        if (T.loading && !T.resolved) { box.append(h("div", { class: "empty" }, _t("takes.reading_the_takes"))); return; }
        if (!T.resolved) { box.append(h("div", { class: "empty" }, _t("takes.the_plan_has_an_invalid_clip"))); return; }
        box.append(h("div", { class: "tk-legend" },
            h("span", {}, h("i", { class: "lg chosen" }), _t("takes.chosen_take")),
            h("span", {}, h("i", { class: "lg" }), _t("takes.usable")),
            h("span", {}, h("i", { class: "lg other" }), _t("takes.built_on_another_take_of_the")),
            h("span", {}, _t("takes.click_choose_used_to_assemble_before") + _t("takes.hover_play_double_click_larger_preview") + _t("takes.new_take_of_the_clip_box"))));

        if (!branchesList().length) {
            box.append(h("div", { class: "tk-area" }, h("div", { class: "empty", style: "flex:1" },
                h("button", { class: "primary tk-newbranch-big", onclick: newBranch }, _t("takes.new_branch")),
                h("p", { class: "hint" }, _t("takes.a_branch_starts_at_clip_1"))),
                videoPane(p)));
            return;
        }
        box.append(viewBar());
        box.append(selectionBar(p));
        const graph = buildBands(p);
        const viewport = h("div", { class: "tk-viewport" });
        const canvas = h("div", { class: "tk-canvas", style: `width:${graph.width}px;height:${graph.height}px` });
        const svgNS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(svgNS, "svg");
        svg.setAttribute("width", graph.width);
        svg.setAttribute("height", graph.height);
        svg.classList.add("tk-svg");
        canvas.append(svg);
        const n = columnCount(p);
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
        if (startCol()) {
            const sv = H3.startVideo(p);
            top.append(h("div", { class: "tk-col-head tk-col-start", style: `left:${colX(0)}px;width:${COLW}px` },
                h("div", { class: "tk-col-name" }, h("b", {}, "▶ "), _t("takes.start_video_column")),
                h("div", { class: "hint" }, `${startVideoName() || _t("takes.start_video_no_file")} · ${clipLength(sv.frames)}`)));
        }
        for (let index = 1; index <= n; index++) {
            const clip = p.clips[index - 1] || { name: "", continue: true };
            const res = T.resolved[index] || {};
            const count = (T.takes[index] || []).length;
            top.append(h("div", { class: "tk-col-head", style: `left:${colX(index)}px;width:${COLW}px` },
                h("div", { class: "tk-col-name" }, p.clips[index - 1] ? planButton(index) : null, h("b", {}, `${index} `), (clip.continue ? "↪ " : "") + (clip.name || "")),
                h("div", { class: "hint" }, _t("takes.take_s", { count }))));
            if (index > 1 && !clip.continue) {
                canvas.append(h("div", { class: "tk-cut", style: `left:${colX(index) - gapX() / 2}px;height:${graph.height - 10}px` }));
                top.append(h("span", { class: "tk-cut-mark", style: `left:${colX(index) - gapX() / 2 - 7}px` }, "✂"));
            }
        }
        for (const node of graph.nodes) canvas.append(node.kind === "take" ? takeCard(node, p) : node.kind === "export" ? exportCard(node)
            : node.kind === "startvideo" ? startVideoCard(node, p) : ghostCard(node, p));
        for (const slot of graph.slots || []) canvas.append(slotCard(slot));
        for (const cell of graph.cells || []) canvas.append(cellCard(cell));

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
    // folded branch headers all take the width of the widest one
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

    // ---------------------------------------------------------------- layout: a tree per branch
    const gapX = () => 130;
    const gapY = () => 34;
    const HEADW = 200;
    // the start video, when it opens the final video, has a column of its own before clip 1 (index 0)
    const startCol = () => { const sv = H3.startVideo(plan()); return sv && sv.in_assembly ? 1 : 0; };
    const colX = (i) => LEFT + HEADW + 30 + (i - 1 + startCol()) * (COLW + gapX());

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
    // « + nouvelle branche »: empty, from a plan file or a duplicate (plan_branch.js)
    function newBranch() { window.H3Branch.create(); }
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
                h("span", { class: "hint" }, _t("takes.take_s", { count: band.count }) + (band.running ? " · " + _t("takes.folded_running", { count: band.running }) : "")));
        }
        const free = H3.mode(p) === "free";
        const active = T.resolved?.branch === br.id;
        return h("div", { class: `tk-band-head tk-stick-x${active ? " active" : ""}`, "data-branch": br.id, style: `left:${LEFT}px;top:${band.y}px;width:${HEADW}px;min-height:${Math.min(band.h, CARD_H)}px;border-color:${br.color}` },
            h("div", { class: "tk-band-title" }, foldToggle(br, false), h("i", { style: `background:${br.color}` }),
                nameField(br),
                active ? h("span", { class: "hint" }, _t("takes.selection")) : null),
            br.base && br.base.takes ? h("div", { class: "hint tk-band-base" }, _t("takes.takes_over", { k: br.base.takes.filter(Boolean).length,
                name: (branchesList().find((b) => b.id === br.base.from) || { name: br.base.from }).name })) : null,
            h("div", { class: "hint" }, _t("takes.mp_ref", { width: br.width, height: br.height, v2: ((br.width * br.height) / (1024 * 1024)).toFixed(2).replace(/0$/, "").replace(".", H3I18n.decimal()), v3: br.ref_image_size || "max" })),
            !free ? h("div", { class: "hint" }, "♪ " + (br.song ? br.song.split("/").pop() : _t("takes.no_song"))) : null,
            h("div", { class: "tk-inline", style: "margin-top:6px" },
                h("button", { class: "small tk-brsettings", onclick: () => window.H3Branch.settings(br.id),
                    title: [br.upscale && br.upscale.enabled ? "⇧ " + _t("takes.latent_upscale_first_pass_at_a") : "",
                        (br.loras || []).length ? _t("takes.lora_added_to_the_takes_of") + T.studio.fmtLoras(br.loras) : ""].filter(Boolean).join("\n") || null },
                    _t("takes.branch_settings"), br.upscale && br.upscale.enabled ? h("span", { class: "tk-up-on" }, " ⇧") : null,
                    (br.loras || []).length ? h("span", { class: "tk-lora-on" }, ` L${br.loras.length > 1 ? "×" + br.loras.length : ""}`) : null),
                h("button", { class: "small tk-master", title: _t("takes.master_plan_title"), onclick: () => T.studio.openPlanScreen({ branch: br.id, leaf: null }) }, _t("takes.master_plan_button")),
                fillButton(br),
                h("button", { class: "small tk-dup", title: _t("takes.duplicate_branch_title"), onclick: () => window.H3Branch.create({ how: "copy", source: br.id, duplicate: true }) }, _t("takes.duplicate_branch")),
                h("button", { class: "small danger", title: _t("takes.delete_the_branch_what_is_in"),
                    disabled: T.jobs.some((j) => (j.status === "queued" || j.status === "running") && (j.branch || defBranch()) === br.id) || null,
                    onclick: () => T.studio.deleteBranch(br.id) }, _t("takes.delete"))));
    }
    // the name of a branch, edited in place: Enter or leaving the field saves, Esc gives the old name back
    function nameField(br) {
        const input = h("input", { class: "tk-band-name", value: br.name, title: _t("takes.branch_name_hint"), spellcheck: "false",
            onmousedown: (e) => e.stopPropagation(), onclick: (e) => e.stopPropagation(),
            onkeydown: (e) => {
                if (e.key === "Enter") { e.preventDefault(); input.blur(); }
                else if (e.key === "Escape") { input.value = br.name; input.blur(); }
            },
            onblur: async () => {
                const name = input.value.trim();
                if (!name) input.value = br.name;
                else if (name !== br.name) await T.studio.renameBranch(br.id, name);
                if (T.renderLater) { T.renderLater = false; renderTakes(); }
            } });
        return input;
    }
    // the selected twig: its plan (generated clips, then what comes after), ▶▶ and the assembly
    function selectionBar(p) {
        const chosen = chosenMap();
        const last = Math.max(0, ...Object.keys(chosen).map(Number));
        const branch = T.resolved?.branch || defBranch();
        const br = branchesList().find((b) => b.id === branch) || {};
        const leaf = last ? chosen[last] : null;
        const chain = Array.from({ length: last }, (_v, k) => `${k + 1}`).join(" → ");
        const total = (p.clips || []).length;
        let end = 0;
        if (last && H3.framesLegal(p)) { const rows = H3.timeline(p); end = rows[last - 1] ? rows[last - 1].end - H3.finalStart(p) : 0; }
        return h("div", { class: "tk-selbar" },
            h("span", { class: "hint" }, _t("takes.selection_label")),
            h("b", { style: `border-left:4px solid ${br.color || "#888"};padding-left:6px` }, `${br.name || "?"} : ${leaf ? chain : _t("takes.selection_empty")}`),
            h("span", { class: "hint" }, leaf ? _t("takes.selection_info", { length: clipLength(end) || "0", next: Math.max(0, total - last) }) : _t("takes.selection_master_info", { count: total })),
            h("button", { class: "small primary tk-twigplan", onclick: () => T.studio.openPlanScreen({ branch, leaf }) },
                leaf ? _t("takes.plan_of_selection") : _t("takes.master_plan_of", { name: br.name || "?" })),
            leaf && br.id ? fillButton(br, leaf) : null,
            leaf ? h("button", { class: "small", onclick: async () => {
                const job = T.jobs.find((j) => j.kind === "clip" && j.take_id === leaf && ["queued", "running"].includes(j.status));
                if (!job) return assemble(last, leaf);
                try {          // the take is not made yet: the assembly starts after its generation
                    const made = await T.studio.assembleAfter(job.id);
                    if (!T.jobs.some((j) => j.id === made.id)) T.jobs.push(made);
                    toast(_t("takes.assembly_of_clips_1_to_planned", { index: last })); studioPollSoon(300);
                } catch (err) { alert(err.message); }
            } }, _t("takes.assemble_1", { index: last })) : null);
    }
    // ▶▶ : generates the clips that have no take yet, each one after the one before: the master line of a branch (band
    // header), or the selected twig (selection bar). Its tooltip comes from a dry run on the server, asked again when
    // takes, jobs, the selection or the master plans change.
    function fillKey(leaf) {
        const all = Object.values(T.takes || {}).flat();
        return JSON.stringify([all.length, Math.max(0, ...all.map((r) => r.saved_at || 0)), T.jobs.filter((j) => j.status === "queued" || j.status === "running").map((j) => j.id),
            leaf || "", JSON.stringify((T.masters || {})), (plan()?.clips || []).length, JSON.stringify(plan()?.clips || []).length]);
    }
    // the dry run of ▶▶: the master line of a branch (no leaf), or the selection (its leaf)
    function fillInfo(brId, leaf = null) {
        T.fill = T.fill || {};
        const slot = `${brId}|${leaf || ""}`;
        const key = fillKey(leaf), cur = T.fill[slot];
        if (!cur || cur.key !== key) {
            if (!cur || !cur.loading || cur.key !== key) {
                T.fill[slot] = { key, loading: true, data: cur && cur.data, error: cur && cur.error };
                T.studio.fillBranch(brId, true, true, leaf).then((data) => { T.fill[slot] = { key, data }; recompute(); })
                    .catch((e) => { T.fill[slot] = { key, error: e.message }; recompute(); });
            }
        }
        return T.fill[slot];
    }
    function clipRange(items) {
        const list = items.map((i) => i.clip);
        if (!list.length) return "";
        const runs = [];
        for (const c of list) { const last = runs[runs.length - 1]; if (last && c === last[1] + 1) last[1] = c; else runs.push([c, c]); }
        return runs.map(([a, b]) => (a === b ? `${a}` : _t("takes.to", { a, b }))).join(", ");
    }
    // ▶▶ of a branch: the empty cells of its master line; ▶▶ of the selection (leaf): the rest of the selected twig
    function fillButton(br, leaf = null) {
        const info = fillInfo(br.id, leaf);
        const data = info.data;
        // a fixed label (the header has a fixed width): what it will do is in the tooltip
        let title = leaf ? _t("takes.fill_selection_title") : _t("takes.fill_line_title"), disabled = true;
        if (info.error) { title = _t("takes.fill_unavailable") + "\n" + info.error; }
        else if (data) {
            const count = data.items.length;
            disabled = !count;
            const what = !count ? (leaf ? _t("takes.selection_complete") : _t("takes.line_complete"))
                : _t("takes.generate_2", { v0: count === 1 ? _t("takes.the_clip") : _t("takes.the_clips"), v1: clipRange(data.items) });
            title = (leaf ? _t("takes.fill_selection_title") : _t("takes.fill_line_title")) + "\n" + what;
        }
        return h("button", { class: `small tk-fill${leaf ? " tk-fill-sel" : ""}`, disabled: disabled || null, title, onclick: () => confirmFill(br, leaf) },
            leaf ? _t("takes.fill_selection_label") : _t("takes.fill_label"));
    }
    async function confirmFill(br, leaf = null) {
        let data;
        try { data = await T.studio.fillBranch(br.id, true, true, leaf); } catch (e) { alert(e.message); return; }
        if (!data.items.length) { alert(_t("takes.nothing_to_generate_each_clip_has")); return; }
        const fmt = (s) => (s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)} h ${String(Math.round(s % 3600 / 60)).padStart(2, "0")}`);
        const lines = data.items.map((it) => `• clip ${it.clip} ${it.name}${it.new_scene && it.clip > 1 ? _t("takes.new_scene") : ""}`);
        const head = _t("takes.branch_clip_s_to_generate_in", { name: br.name, length: data.items.length })
            + (data.line ? _t("takes.starting_point_the_master_plan") : _t("takes.starting_point_the_selection_of_this"))
            + (data.eta ? _t("takes.estimated_time_from_previous_generations", { v0: fmt(data.eta) }) : "");
        const last = data.items[data.items.length - 1].clip;
        const answer = await H3Dialog.confirm(`${head}\n\n${lines.join("\n")}`,
            { ok: _t("takes.start"), danger: false, check: { label: _t("takes.assemble_the_branch_at_the_end") + last + ")", checked: true } });
        if (!answer) return;
        try {
            const res = await T.studio.fillBranch(br.id, false, answer.checked, leaf);
            toast(_t("takes.generation_s_added_to_the_queue", { length: (res.launched || []).length }) + (res.assembly ? _t("takes.then_assembly") : ""));
            studioPollSoon(300);
        } catch (e) { alert(e.message); }
    }
    function buildBands(p) {
        const n = columnCount(p), def = defBranch();
        const nodes = [], edges = [], placeholders = [], bands = [], byKey = {}, slots = [], cells = [];
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
            const startKey = startCol() ? "v:" + br.id : null;
            if (startKey) items.push({ key: startKey, kind: "startvideo", index: 0, order: -1, branch: br.id });
            // a duplicated branch: the clips it takes over come first, shown dimmed (⇡ the branch they come from)
            const base = (br.base && br.base.takes) || [];
            base.forEach((id, k) => {
                const record = id ? recordOf(k + 1, id) : null;
                if (!record) return;
                const key = `t:${id}@${br.id}`;
                // 0.49: after a clip left free, it hangs on the branch's own take of that clip (or on its empty box)
                items.push({ key, kind: "take", index: k + 1, record, order: -1, reusedIn: br.id, afterHole: k > 0 && !base[k - 1],
                    reusedPrev: k && base[k - 1] ? `t:${base[k - 1]}@${br.id}` : null });
                keyOfToken[`${k + 1}:${tokenOf(id)}`] = key;
            });
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
            // the master line (0.48): the clips taken over, then the takes made from the master plan itself, one per
            // clip, first in the tree (its top row); its empty cells follow it, the first one can be generated
            const master = (T.masters || {})[br.id] || { clips: [] };
            const lineAt = {};
            for (const it of items) {
                const st = it.kind === "take" ? ((it.record || {}).studio || {}) : it.kind === "ghost" ? (((it.job || {}).record || {}).studio || {}) : {};
                const on = it.reusedIn || (it.kind === "take" && st.line) || (it.kind === "ghost" && st.line && !["error", "cancelled"].includes(it.job.status));
                if (on && !lineAt[it.index]) { it.line = true; it.order = -1; lineAt[it.index] = it; }
            }
            for (const it of items) {
                const clip = p.clips[it.index - 1] || {};
                it.parent = null;
                if (it.index === 1 && startKey && clip.continue) { it.parent = startKey; edges.push({ from: startKey, to: it.key, cls: "start" }); }
                if (it.index <= 1) continue;
                if (it.reusedIn) {
                    if (it.reusedPrev) { it.parent = it.reusedPrev; edges.push({ from: it.reusedPrev, to: it.key, cls: "reused" }); }
                    continue;
                }
                // every take hangs on the take before it: the one it continues (↪) or the one it was timed after (✂)
                // (a take of the master line stays on it, even when a new scene could follow the selection)
                const pred = it.kind === "take" ? (it.line ? predOf(it.record) : effPred(it.record, it.index)) : it.job.predecessor;
                const key = pred ? keyOfToken[`${it.index - 1}:${tokenOf(pred)}`] : null;
                const cut = it.kind === "take" ? !it.record.parent : !it.job.parentToken;
                if (key) { it.parent = key; edges.push({ from: key, to: it.key, cls: cut ? "cut" : linkClass(it, key) }); }
            }
            const local = {};
            for (const it of items) local[it.key] = it;
            for (const it of items) if (it.parent && !local[it.parent]) it.parent = null;
            let end = 0;
            while (lineAt[end + 1]) end++;
            let prevKey = end ? lineAt[end].key : (startKey && (master.clips[0] || {}).continue ? startKey : null);
            const idOf = (it) => (!it ? null : it.kind === "ghost" ? it.job.take_id : it.kind === "take" ? it.record.id : null);
            // 0.49: the clips taken over after clips left free: on the master line, after the box (or the take) of the
            // clip before
            for (let idx = end + 1; idx <= Math.max(master.clips.length, base.length); idx++) {
                const at = lineAt[idx];
                if (at) {
                    if (at.reusedIn && at.afterHole) {
                        at.parent = prevKey;
                        at.reusedAfter = idOf(local[prevKey]);
                        if (prevKey) edges.push({ from: prevKey, to: at.key, cls: local[prevKey] && local[prevKey].kind === "cell" ? "cell" : "reused" });
                    }
                    prevKey = at.key;
                    continue;
                }
                if (idx > master.clips.length) break;
                const before = idx === end + 1 && end ? lineAt[end] : null;
                const cell = { key: `c:${br.id}:${idx}`, kind: "cell", index: idx, branch: br.id, order: -2, parent: prevKey,
                    active: idx === end + 1, clip: master.clips[idx - 1],
                    after: before ? idOf(before) : null };
                items.push(cell);
                local[cell.key] = cell;
                if (prevKey) edges.push({ from: prevKey, to: cell.key, cls: "cell" });
                prevKey = cell.key;
            }
            // a clip taken over after a clip left free that has a take already (the line goes past it)
            for (const it of items) {
                if (!it.reusedIn || !it.afterHole || it.parent) continue;
                const before = lineAt[it.index - 1];
                if (before) { it.parent = before.key; it.reusedAfter = idOf(before); edges.push({ from: before.key, to: it.key, cls: "reused" }); }
            }
            // an empty box to the right of each end of the branch: the next clip, to generate after this take
            const hasChild = new Set(items.filter((it) => it.parent).map((it) => it.parent));
            for (const it of [...items]) {
                if (it.kind === "startvideo" || it.kind === "cell" || hasChild.has(it.key)) continue;
                if (it.reusedIn && base[it.index]) continue;
                if (it.kind === "ghost" && ["error", "cancelled", "done"].includes(it.job.status)) continue;
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
            {
                const span = {};
                const sizeOf = (it) => {
                    const kids = children[it.key] || [];
                    const total = kids.reduce((acc, k) => acc + sizeOf(k), 0) + VG * Math.max(0, kids.length - 1);
                    return (span[it.key] = Math.max(CARD_H, total));
                };
                const place = (it, top) => {
                    const kids = children[it.key] || [];
                    // aligned on the top: the first child of each take is on its row, so the master line is a straight row
                    if (!kids.length) it.y = top;
                    else {
                        let yy = top;
                        for (const k of kids) { place(k, yy); yy += span[k.key] + VG; }
                        it.y = kids[0].y;
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
            }
            // "générer": clip 1, when the branch has none yet (every other clip comes after a take)
            for (let index = 1; index <= Math.max(1, Math.min(1, n)); index++) {
                if (items.some((it) => it.index === index)) continue;
                const yy = colBottom[index] !== undefined ? colBottom[index] + VG : y;
                placeholders.push({ index, branch: br.id, x: colX(index), y: yy });
                colBottom[index] = yy + CARD_H;
            }
            const bottom = Math.max(y + CARD_H + 40, ...Object.values(colBottom));
            bands.push({ branch: br, y, h: bottom - y });
            for (const it of items) { it.band = br.id; if (it.kind === "slot") slots.push(it); else if (it.kind === "cell") cells.push(it); else nodes.push(it); byKey[it.key] = it; }
            y = bottom + BAND_GAP;
        }
        const width = colX(n + 1) + COLW + LEFT;   // the « + clip suivant » column; assembled videos are in the side pane
        return { nodes, edges, byKey, placeholders, bands, slots, cells, newBranchY: y - BAND_GAP / 2, width, height: y + 40 };
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
        const res = T.resolved[index] || { takes: {} };
        const [state, why] = res.takes[record.id] || ["other", ""];
        const reused = node.reusedIn || null;
        const band = reused || branchOfRecord(record);
        const chosen = res.chosen === record.id && T.resolved.branch === band;
        const video = thumbVideo("t:" + record.id, () => {
            const v = h("video", { muted: true, loop: true, playsinline: true, preload: "auto" });
            v.muted = true;
            return v;
        });
        if (!video.dataset.loading && hasPreview(record.id)) { video.dataset.loading = "1"; attachThumb(video, record.id); }
        const branch = branchOfRecord(record);
        // (0.48.2) a take taken over from another branch can be made again too: the variant belongs to this band's branch
        // 0.49: a clip taken over after a clip left free waits for the branch's take of that clip
        const waits = reused && node.afterHole && !node.reusedAfter;
        const actions = h("div", { class: "tk-actions" },
            h("button", { class: "small tk-retake", disabled: waits || null,
                title: waits ? _t("takes.portion_waits_title", { index: index - 1 }) : reused ? _t("takes.new_take_reused_title", { index }) : _t("takes.new_take_panel_title", { index }),
                onclick: (e) => { e.stopPropagation(); launchFork(index, record, reused ? band : null, reused && node.afterHole ? node.reusedAfter : undefined); } }, _t("takes.new_take_short")),
            h("button", { class: "small tk-next", disabled: waits || null, title: waits ? _t("takes.portion_waits_title", { index: index - 1 }) : _t("takes.next_clip_panel_title", { index: index + 1 }),
                onclick: (e) => { e.stopPropagation(); launchNext(index + 1, record.id, band); } }, _t("takes.next_clip_short")));
        const from = reused ? (branchesList().find((b) => b.id === branch) || { name: branch }).name : null;
        return h("div", {
            class: `tk-card ${chosen ? "chosen" : state}${reused ? " tk-reused" : ""}${T.highlight && T.highlight.has && T.highlight.has(record.id) ? " tk-hl" : ""}`, "data-take": record.id,
            "data-band": band,
            style: `left:${node.x}px;top:${node.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: _t("takes.seed", { id: record.id, seed: record.seed, v2: when(record.saved_at), v3: why ? "\n" + why : "" }),
            onclick: () => {
                if (T.dragged) return;
                clearTimeout(T.clickTimer);
                T.clickTimer = setTimeout(() => choose(index, record.id, false, band), 230);
            },
            ondblclick: (e) => { e.preventDefault(); clearTimeout(T.clickTimer); openViewer(index, record.id); },
            onmouseenter: () => { if (!video.src) return; video.muted = !T.soundOnHover; video.currentTime = 0; video.play().catch(() => { video.muted = true; video.play().catch(() => {}); }); },
            onmouseleave: () => { video.pause(); video.currentTime = Math.min(0.5, (video.duration || 1) / 3); },
        },
            branch ? h("i", { class: "tk-branch-mark", style: `background:${branchColor(branch)}` }) : null,
            reused ? h("span", { class: "tk-reused-tag", title: _t("takes.taken_over_from", { name: from }) }, "⇡ " + from) : null,
            record.studio ? badges(record.studio.upscale, record.studio.upscale ? _t("takes.latent_upscale_summary", { summary: record.studio.upscale.summary }) : "", record.studio.extra_loras) : null,
            h("div", { class: "tk-thumb" }, hasPreview(record.id) ? video : h("span", { class: "hint" }, _t("takes.no_preview")),
                h("span", { class: "tk-dur", title: _t("takes.clip_length") }, clipLength(record.frames || (clip || {}).frames)),
                node.line && !reused ? h("span", { class: "tk-line-tag", title: _t("takes.line_take_title") }, _t("takes.line_take_tag")) : null),
            h("div", { class: "tk-meta" }, h("span", { class: "tk-seedbox" }, chosen ? "✓ " : "", reused ? h("span", { class: "hint" }, String(record.seed ?? "")) : seedField(record, (seed) => {
                // the same take again with another seed: same portion of plan, same settings
                generate(index, { after: effPred(record, index), planFrom: record.id, seed, branch, ...takeSettings(record) });
            })), h("span", { class: "hint" }, when(record.saved_at))),
            actions,
            reused ? null : h("button", { class: "small danger tk-del", title: _t("trash.delete_take_title"),
                onclick: (e) => { e.stopPropagation(); window.H3Trash.deleteTake(index, record.id); } }, "🗑"),
            planButton(index, record),
            leafButton(index, record, reused ? band : null));
    }

    // on every take, shown when the mouse is over the card: assembles the twig ending with it (clips 1 to this one)
    function leafButton(index, record, band) {
        return h("button", { class: "small tk-asm-btn", title: _t("takes.assemble_clips_1_to_along_this", { index }),
            onclick: (e) => { e.stopPropagation(); assemble(index, record.id, band); } }, _t("takes.assemble_1", { index }));
    }
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

    function badges(upscale, upTitle, loras) {
        if (!upscale && !(loras && loras.length)) return null;
        return h("span", { class: "tk-badges" },
            upscale ? h("span", { class: "tk-up-badge", title: upTitle }, "⇧") : null,
            loras && loras.length ? h("span", { class: "tk-lora-badge", title: _t("takes.extra_lora") + T.studio.fmtLoras(loras) }, loras.length > 1 ? _t("takes.l", { length: loras.length }) : "L") : null);
    }
    // the next clip after a take (or a take still waiting): opens the launch panel
    function slotCard(slot) {
        const index = slot.index;
        const after = slot.after.kind === "take" ? slot.after.record.id : slot.after.job.take_id;
        const launch = () => { if (!T.dragged) launchNext(index, after, slot.branch); };
        const src = sourceThumb(index, slot.branch);
        return h("div", { class: `tk-card tk-placeholder tk-slot${src ? " has-src" : ""}`, style: `left:${slot.x}px;top:${slot.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: _t("takes.generate_clip_following_this_take", { index }), onclick: launch,
            onmouseenter: () => srcHover(src, true), onmouseleave: () => srcHover(src, false) },
            src, h("div", { class: "tk-plus" }, "+"), h("div", { class: "hint" }, _t("takes.clip_following", { index })),
            h("div", { class: "hint tk-slot-name" }, (plan().clips[index - 1] || {}).name || ""),
            plan().clips[index - 1] ? planButton(index, null, { branch: slot.branch }) : null);
    }

    function ghostCard(node, p) {
        const job = node.job, index = node.index;
        const pct = job.progress ? Math.round(100 * job.progress.value / Math.max(1, job.progress.max)) : 0;
        const live = job.status === "queued" || job.status === "running";
        const picked = live && job.take_id && T.resolved && T.resolved[index] && T.resolved[index].chosen === job.take_id && T.resolved.branch === (job.branch || defBranch());
        return h("div", { class: `tk-card tk-ghost ${job.status}${picked ? " chosen" : ""}`, "data-job": job.id, "data-take": job.take_id || null, style: `left:${node.x}px;top:${node.y}px;width:${COLW}px;height:${CARD_H}px`, title: job.error || (job.preview ? _t("takes.double_click_larger_preview") : ""),
            // a click chooses it like a take: the selection goes through the take it will make
            onclick: () => { if (T.dragged || !live || !job.record) return; clearTimeout(T.clickTimer); T.clickTimer = setTimeout(() => choose(index, job.take_id, false, job.branch || defBranch()), 230); },
            ondblclick: (e) => { e.preventDefault(); clearTimeout(T.clickTimer); if (job.preview) openLive(job); },
            onmouseenter: (e) => { const v = e.currentTarget.querySelector("video.tk-live"); if (v && T.soundOnHover) v.muted = false; },
            onmouseleave: (e) => { const v = e.currentTarget.querySelector("video.tk-live"); if (v) v.muted = true; } },
            h("div", { class: "tk-thumb" }, job.preview && live
                ? liveElement(job)
                : h("span", { class: "tk-ghost-icon" }, job.status === "queued" ? "⏳" : job.status === "error" ? "✖" : job.status === "done" ? "✓" : "▶"),
                job.status === "running" ? h("div", { class: "tk-progress" }, h("i", { style: `width:${pct}%` })) : null),
            h("div", { class: "tk-ghost-label" }, ghostLabel(job)),
            h("div", { class: "tk-actions show" },
                live && job.kind === "clip" && job.record ? h("button", { class: "small tk-retake", title: _t("takes.new_take_panel_title", { index }),
                    onclick: (e) => { e.stopPropagation(); launchFork(index, job.record); } }, _t("takes.new_take_short")) : null,
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
    const startVideoName = () => { const f = window.H3Editor && H3Editor.media && H3Editor.media.startVideoFile ? H3Editor.media.startVideoFile() : null; return f ? f.split("/").pop() : null; };
    // the start video segment (the same in every branch): plays on hover, a click opens its settings
    // the clips shown: those of the plan, of the takes and of the generations waiting (a clip can be generated
    // after the end of the plan: « + clip suivant »)
    function columnCount(p) {
        return Math.max((p.clips || []).length, ...Object.keys(T.takes || {}).map(Number).filter((k) => (T.takes[k] || []).length),
            ...T.jobs.filter((j) => j.kind === "clip" && j.clip).map((j) => Number(j.clip)));
    }
    // the plan header with the segment of a branch's video (each branch has its own segment, in its master plan)
    function withSegment(p, branch) {
        const seg = T.studio.segment ? T.studio.segment(branch) : null;
        if (!seg) return p;
        return p.start_video ? { ...p, start_video: seg } : p.edit_video ? { ...p, edit_video: { ...p.edit_video, ...seg } } : p;
    }
    function startVideoCard(node, p) {
        p = withSegment(p, node.branch);
        const sv = H3.startVideo(p);
        const media = window.H3Editor && H3Editor.media;
        const file = media && media.startVideoFile ? media.startVideoFile() : null;
        const key = file ? `s:${file}:${sv.start_frame}:${sv.end_frame}` : null;
        // a small copy of the segment only, made once by the server; the same <video> survives the redraws
        const video = key ? thumbVideo(key, () => {
            const v = h("video", { muted: true, loop: true, playsinline: true, preload: "auto" });
            v.dataset.state = "wait";
            queueMicrotask(() => attachSegment(v, key, file, sv));      // once it is in T.thumbs
            return v;
        }) : null;
        const rest = () => { if (video && video.readyState) video.currentTime = Math.min(0.5, (video.duration || 1) / 3); };
        return h("div", { class: "tk-card tk-startvid", "data-start": node.branch, "data-svthumb": key || "", style: `left:${node.x}px;top:${node.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: _t("takes.start_video_card_title"),
            // the start video settings belong to the plan: the plan screen opens first (what changes there is saved)
            onclick: async () => { if (T.studio.openPlanScreen) await T.studio.openPlanScreen({ branch: node.branch, leaf: null }); if (window.H3Editor && H3Editor.openStartVideo) H3Editor.openStartVideo(); },
            onmouseenter: () => { if (!video || video.dataset.state !== "ready") return; video.muted = !T.soundOnHover; video.currentTime = 0; video.play().catch(() => { video.muted = true; video.play().catch(() => {}); }); },
            onmouseleave: () => { if (!video) return; video.pause(); rest(); } },
            h("div", { class: "tk-thumb" }, video || h("span", { class: "tk-ghost-icon" }, "▶"),
                video && video.dataset.state === "wait" ? h("span", { class: "tk-sv-wait" }, _t("takes.start_video_preparing")) : null),
            h("div", { class: "tk-meta" }, h("span", {}, startVideoName() || _t("takes.start_video_no_file")),
                h("span", { class: "hint" }, `${clipLength(sv.start_frame) || "0"} → ${clipLength(sv.end_frame)}`)));
    }
    // edited video: the slice of the source a clip edits, behind its « + » card (plays on hover)
    function sourceThumb(index, branch) {
        const p = withSegment(plan(), branch);
        if (!p.edit_video) return null;
        const media = window.H3Editor && H3Editor.media;
        const file = media && media.startVideoFile ? media.startVideoFile() : null;
        const slice = H3.editSlice(p, index);
        if (!file || !slice) return null;
        const row = H3.timeline(p)[index - 1];
        const seg = { start_frame: slice[0] + row.context, end_frame: slice[0] + slice[1] };    // what the clip shows (not its lead-in)
        const key = `src:${branch}:${file}:${seg.start_frame}:${seg.end_frame}`;
        const video = thumbVideo(key, () => {
            const v = h("video", { muted: true, loop: true, playsinline: true, preload: "auto", class: "tk-src-thumb" });
            v.dataset.state = "wait";
            queueMicrotask(() => attachSegment(v, key, file, seg));
            return v;
        });
        return video;
    }
    const srcHover = (video, on) => {
        if (!video || video.dataset.state !== "ready") return;
        if (on) { video.muted = !T.soundOnHover; video.currentTime = 0; video.play().catch(() => { video.muted = true; video.play().catch(() => {}); }); }
        else { video.pause(); video.currentTime = Math.min(0.5, (video.duration || 1) / 3); }
    };
    async function attachSegment(video, key, file, sv) {
        const done = (src) => {
            video.addEventListener("loadeddata", () => {
                video.dataset.state = "ready";
                if (video.paused) video.currentTime = Math.min(0.5, (video.duration || 1) / 3);
                for (const el of document.querySelectorAll(`[data-svthumb="${CSS.escape(key)}"] .tk-sv-wait`)) el.remove();
            }, { once: true });
            video.src = src;
        };
        const original = () => {      // no ffmpeg (or it failed): the file itself, from the start of the segment
            const url = H3Editor.media.video();
            if (url) done(`${url}#t=${(sv.start_frame / 24).toFixed(3)},${(sv.end_frame / 24).toFixed(3)}`);
        };
        let asked = false;
        for (;;) {
            if (T.thumbs.get(key) !== video) return;        // another file or segment since
            let st;
            try {
                st = await T.studio.segmentThumb(file, sv.start_frame, sv.end_frame);
                if (st.state === "none" && !asked) { asked = true; st = await T.studio.segmentThumb(file, sv.start_frame, sv.end_frame, "POST"); }
            } catch (_) { original(); return; }
            if (st.state === "done") { done(T.studio.viewUrl(st.path)); return; }
            if (st.state !== "running") { original(); return; }
            await new Promise((r) => setTimeout(r, 600));
        }
    }
    function exportCard(node) {
        const ex = node.export;
        const video = thumbVideo("e:" + ex.file, () => {      // the same <video> survives the redraws
            const v = h("video", { muted: true, loop: true, playsinline: true, preload: "metadata", src: T.studio.viewUrl(ex.file) });
            v.addEventListener("loadeddata", () => { if (v.paused) v.currentTime = Math.min(0.5, (v.duration || 1) / 3); }, { once: true });
            return v;
        });
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
        const video = h("video", { controls: true, autoplay: true, loop: true, src: T.studio.viewUrl(ex.file), style: "width:100%;max-height:62vh;background:#000;border-radius:6px" });
        const overlay = h("div", { class: "tk-modal", onclick: (e) => { if (e.target === overlay) close(); } },
            h("div", { class: "tk-box" },
                h("div", { class: "tk-box-head" }, h("b", {}, `${ex.name}.mp4`),
                    h("span", { class: "hint" }, _t("takes.clips_1_to", { v0: ex.branch_name || "", clips: ex.clips, v2: ex.size ? ex.size.join(" × ") : "", v3: whenMs(ex.created) })),
                    h("span", { style: "flex:1" }),
                    ex.infos ? h("button", { title: _t("takes.how_the_video_was_made_clips"), onclick: () => window.open(T.studio.infosUrl(ex.infos), "_blank") }, "infos") : null,
                    h("button", { onclick: close }, _t("takes.close"))),
                video));
        document.body.append(overlay);
        document.addEventListener("keydown", onKey);
    }

    // an empty cell of the master line: the clip of the master plan, generated once, in order (the first one only)
    function cellCard(cell) {
        const clip = cell.clip || {};
        const src = cell.active ? sourceThumb(cell.index, cell.branch) : null;     // an edited video: the slice this clip edits
        return h("div", { class: `tk-card tk-cell${cell.active ? " active" : ""}${src ? " has-src" : ""}`, "data-cell": `${cell.branch}:${cell.index}`,
            style: `left:${cell.x}px;top:${cell.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: cell.active ? _t("takes.line_cell_title", { index: cell.index }) + (src ? "\n" + _t("takes.edit_source_hint") : "")
                : _t("takes.line_cell_later", { index: cell.index, before: cell.index - 1 }),
            onclick: () => { if (!T.dragged && cell.active) openLaunch({ mode: "line", index: cell.index, after: cell.after, branch: cell.branch }); },
            onmouseenter: () => srcHover(src, true), onmouseleave: () => srcHover(src, false) },
            src,
            h("div", { class: "tk-plus" }, cell.active ? "▶" : ""),
            h("div", { class: "hint" }, `${cell.index} ${clip.continue && cell.index > 1 ? "↪ " : ""}${clip.name || ""}`),
            h("div", { class: "hint tk-cell-label" }, _t("takes.line_cell_label")),
            planButton(cell.index, null, { branch: cell.branch }));
    }
    function placeholderCard(ph, p) {
        const index = ph.index;
        const src = sourceThumb(index, ph.branch);
        return h("div", { class: `tk-card tk-placeholder${src ? " has-src" : ""}`, "data-branch": ph.branch, style: `left:${ph.x}px;top:${ph.y}px;width:${COLW}px;height:${CARD_H}px`,
            title: _t("takes.generate_clip_1_of_this_branch") + (src ? "\n" + _t("takes.edit_source_hint") : ""),
            onclick: () => { if (!T.dragged) launchNext(1, null, ph.branch); }, onmouseenter: () => srcHover(src, true), onmouseleave: () => srcHover(src, false) },
            src, h("div", { class: "tk-plus" }, "+"), h("div", { class: "hint" }, _t("takes.generate")),
            planButton(index, null, { branch: ph.branch }));
    }

    // ---------------------------------------------------------------- zoom and pan
    function loadViewPrefs() {
        try {
            const v = JSON.parse(localStorage.getItem("h3clipplan.view") || "{}");
            T.mapCorner = ["tl", "tr", "bl", "br"].includes(v.mapCorner) ? v.mapCorner : "br";
            T.mapOpen = v.mapOpen !== false;
            T.paneOpen = v.paneOpen !== false;
        } catch (_) { /* storage unavailable */ }
        if (!T.mapCorner) T.mapCorner = "br";
        if (T.mapOpen === undefined) T.mapOpen = true;
        if (T.paneOpen === undefined) T.paneOpen = true;
        if (!T.zoom) T.zoom = { z: 1, sx: 0, sy: 0 };
    }
    function saveViewPrefs() {
        try { localStorage.setItem("h3clipplan.view", JSON.stringify({ mapCorner: T.mapCorner, mapOpen: T.mapOpen, paneOpen: T.paneOpen })); } catch (_) { /* ignore */ }
    }
    function viewBar() {
        return h("div", { class: "tk-viewbar" },
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
        sizer.style.width = `${Math.ceil(w * z) + (T.extraRight || 0)}px`;     // extraRight: room beside the launch panel
        // the lowest card can be scrolled up to the top of the view (under the clip names), and no further
        const limit = Math.max(0, (lowestTop() - TOP - 4) * z);
        sizer.style.height = `${Math.ceil(limit + vp.clientHeight)}px`;
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
            const r = cv.getBoundingClientRect(), [ox, oy] = T.mapOffset || [0, 0];
            const gx = (ev.clientX - r.left - ox) / T.mapScale, gy = (ev.clientY - r.top - oy) / T.mapScale;
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
    // in the selection: the take (or the generation waiting) chosen for its clip, in the band of the selection
    function mapSelected(node) {
        const res = T.resolved && T.resolved[node.index];
        const id = node.kind === "ghost" ? node.job.take_id : node.record && node.record.id;
        return !!(res && id && res.chosen === id && node.band === T.resolved.branch);
    }
    function mapColor(node) {
        if (mapSelected(node)) return H3Theme.c("#6aa7ff");
        if (node.kind === "ghost") return node.job.status === "error" ? H3Theme.c("#c0504d") : H3Theme.c("#e8913a");
        const res = T.resolved && T.resolved[node.index];
        if (!res) return H3Theme.c("#5a606c");
        const state = (res.takes[node.record.id] || ["invalid"])[0];
        if (state === "invalid" || state === "stale") return H3Theme.c("#e0b400");
        return H3Theme.c("#5a606c");
    }
    function drawMinimap() {
        const cv = document.querySelector("#takesView .tk-map-canvas");
        if (!cv || !T.graph) return;
        const g = T.graph;
        // the graph alone fills the map, from its top; the frame of the screen may go past its edges (cut there)
        const world = [g.width, g.height];
        const s = Math.min(MAP_W / world[0], MAP_H / world[1]);
        const ox = (MAP_W - world[0] * s) / 2, oy = 0;      // on the top (centred across when the height limits it)
        T.mapScale = s; T.mapOffset = [ox, oy];
        const dpr = window.devicePixelRatio || 1;
        // fixed size box, like ComfyUI: the content is scaled to fit, the box never changes
        cv.width = MAP_W * dpr; cv.height = MAP_H * dpr;
        cv.style.width = `${MAP_W}px`; cv.style.height = `${MAP_H}px`;
        const c = cv.getContext("2d");
        c.setTransform(dpr, 0, 0, dpr, 0, 0);
        c.fillStyle = H3Theme.c("#08090b"); c.fillRect(0, 0, MAP_W, MAP_H);
        c.setTransform(dpr * s, 0, 0, dpr * s, dpr * ox, dpr * oy);
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
            const sel = mapSelected(a) && mapSelected(b);
            c.lineWidth = (on || sel ? 3 : 1.2) / s;
            c.strokeStyle = on ? H3Theme.c("#ffffff") : sel ? H3Theme.c("#6aa7ff") : H3Theme.c("#59607066");
            c.beginPath(); c.moveTo(a.x + COLW, a.y + CARD_H / 2); c.lineTo(b.x, b.y + CARD_H / 2); c.stroke();
        }
        for (const node of g.nodes) {
            c.fillStyle = mapColor(node);
            c.globalAlpha = node.kind === "take" && mapColor(node) === H3Theme.c("#5a606c") ? 0.7 : 1;
            c.fillRect(node.x, node.y, COLW, CARD_H);
            if (mapSelected(node)) {
                c.globalAlpha = 1; c.strokeStyle = H3Theme.c("#cfe0ff"); c.lineWidth = 2 / s;
                c.strokeRect(node.x, node.y, COLW, CARD_H); c.lineWidth = 1.2 / s;
            }
            if (hl && node.record && hl.has(node.record.id)) {
                c.globalAlpha = 1; c.strokeStyle = H3Theme.c("#ffffff"); c.lineWidth = 3 / s;
                c.strokeRect(node.x, node.y, COLW, CARD_H); c.lineWidth = 1.2 / s;
            }
        }
        c.globalAlpha = 1;
        c.setLineDash([4 / s, 3 / s]); c.strokeStyle = H3Theme.c("#8a90a0"); c.lineWidth = 1 / s;
        for (const ph of [...(g.placeholders || []), ...(g.cells || [])]) c.strokeRect(ph.x, ph.y, COLW, CARD_H);
        c.setLineDash([]);
        mapFrame();
    }
    if (typeof document !== "undefined") document.addEventListener("h3theme", () => drawMinimap());
    function mapFrame() {
        const frame = document.querySelector("#takesView .tk-map-frame");
        const parts = viewParts();
        if (!frame || !parts || !T.mapScale || !T.graphSize) return;
        const { vp } = parts, z = T.zoom.z, s = T.mapScale, [ox, oy] = T.mapOffset || [0, 0];
        // the frame of the screen, cut by the edges of the map (the map body hides what goes past)
        Object.assign(frame.style, { left: `${ox + vp.scrollLeft / z * s}px`, top: `${oy + vp.scrollTop / z * s}px`,
            width: `${vp.clientWidth / z * s}px`, height: `${vp.clientHeight / z * s}px` });
    }
    // the top of the lowest card (or folded band): the view scrolls down until it reaches the top of the screen
    function lowestTop() {
        const g = T.graph;
        if (!g) return 0;
        const tops = [...g.nodes.map((n) => n.y), ...(g.slots || []).map((n) => n.y), ...(g.placeholders || []).map((n) => n.y), ...(g.cells || []).map((n) => n.y),
            ...(g.bands || []).filter((b) => b.folded).map((b) => b.y)];
        return tops.length ? Math.max(...tops) : 0;
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
            // an assembly waiting or running shows on the folded tab: launching one is never without a sign
            const busy = asmJobs.filter((j) => j.status === "queued" || j.status === "running");
            const run = busy.find((j) => j.status === "running");
            return h("div", { class: "tk-pane folded", title: _t("takes.show_the_assembled_videos"), onclick: () => { T.paneOpen = true; saveViewPrefs(); renderTakes(); } },
                h("div", { class: "tk-pane-tab" }, _t("takes.videos_2", { count })),
                busy.length ? h("div", { class: "tk-pane-busy", id: "tkAssembleState" }, run ? _t("takes.assembly_state", { state: ghostLabel(run) }) : _t("takes.assemblies_waiting", { count: busy.length })) : null);
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
            ondblclick: () => openExport(ex),
            onmouseenter: () => { setHighlight(exportTakes(ex)); video.muted = !T.soundOnHover; video.currentTime = 0; video.play().catch(() => { video.muted = true; video.play().catch(() => {}); }); },
            onmouseleave: () => { setHighlight(null); video.pause(); video.currentTime = Math.min(0.5, (video.duration || 1) / 3); } },
            h("div", { class: "tk-pane-thumb" }, video),
            h("div", { class: "tk-pane-meta" },
                h("div", { class: "tk-pane-name" }, h("i", { class: "tk-branch-dot", style: `background:${branchColor(ex.branch || defBranch())}` }), ex.name),
                h("div", { class: "hint" }, `${whenMs(ex.created)} · clips 1–${ex.clips}`),
                last ? h("button", { class: "small", title: _t("takes.center_the_view_on_the_last"), onclick: (e) => { e.stopPropagation(); centreOnTake(last); } }, _t("takes.takes")) : null));
    }
    loadViewPrefs();
    window.addEventListener("resize", () => { if (document.querySelector("#takesView .tk-viewport")) applyView(null, true); else if (document.querySelector("#takesView .tk-map-canvas")) drawMinimap(); });

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
    // chantier A: once a branch has takes, its size, song, video and reference files are fixed (a new reference can
    // still be added); another branch is made to change them. Returns true when the change can be applied.
    const branchHasTakes = (branch) => Object.values(T.takes || {}).some((l) => l.some((r) => !branch || branchOfRecord(r) === branch))
        || (!!branch && !!((branchesList().find((b) => b.id === branch) || {}).base));
    function frozen(branch, what) {
        alert(_t("takes.branch_frozen", { what }));
        return false;
    }
    async function confirmStartVideo(_sha) {
        await studioEnsureTakes();
        return branchHasTakes(null) ? frozen(null, _t("takes.the_start_video")) : true;
    }
    async function takeCount(index) {
        await studioEnsureTakes();
        return (T.takes[index] || []).length;
    }
    async function changeSong(branch, _path) {
        await studioEnsureTakes();
        return branchHasTakes(branch) ? frozen(branch, _t("takes.the_song")) : true;
    }
    async function changeSize(branch, _w, _hh) {
        await studioEnsureTakes();
        return branchHasTakes(branch) ? frozen(branch, _t("takes.the_picture_size")) : true;
    }
    async function changeRefSize(_branch, _value) {
        return true;          // a generation setting: each take keeps the one it was made with
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
        selTimer = setTimeout(() => T.studio.saveSelection(pick).then((listing) => {
            T.fileSelection = { ...pick };
            if (listing && listing.fits) T.fits = listing.fits;
            if (listing && listing.twig && T.studio.setTwig) { T.studio.setTwig(listing.twig); renderTakes(); }
        })
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
    // the launch panel: highlight takes; a new take of a take known by its id (from the plan screen)
    function highlight(ids) { setHighlight(ids && ids.length ? new Set(ids) : null); }
    // the launch panel lies over the right of the screen: the take it starts from is brought into the part left
    // visible (the view goes back where it was when the panel closes)
    let viewBefore = null;
    function revealBeside(takeId, panelWidth) {
        const parts = viewParts();
        const card = takeId ? document.querySelector(`#takesView .tk-card[data-take="${CSS.escape(takeId)}"]:not(.tk-reused), #takesView .tk-card[data-take="${CSS.escape(takeId)}"]`) : null;
        if (!parts || !card) return;
        const r = card.getBoundingClientRect(), vr = parts.vp.getBoundingClientRect();
        const limit = Math.min(vr.right, window.innerWidth - panelWidth) - 24;
        viewBefore = { sx: parts.vp.scrollLeft, sy: parts.vp.scrollTop };
        if (r.right > limit) {
            const want = parts.vp.scrollLeft + r.right - limit, max = parts.vp.scrollWidth - parts.vp.clientWidth;
            // a graph narrower than the view cannot scroll that far: room is added on its right while the panel is open
            if (want > max) { T.extraRight = Math.ceil(want - max); parts.sizer.style.width = `${parts.sizer.offsetWidth + T.extraRight}px`; }
            parts.vp.scrollLeft = want;
            T.zoom.sx = parts.vp.scrollLeft;
            stickPanes();
        }
        if (r.left < vr.left + 8) parts.vp.scrollLeft -= vr.left + 8 - r.left;
    }
    function restoreView() {
        const parts = viewParts();
        if (parts && viewBefore) {
            T.zoom.sx = viewBefore.sx; T.zoom.sy = viewBefore.sy;
            T.extraRight = 0;
            applyView(null, true);           // the sizer back to the graph's width, the scroll back where it was
        }
        viewBefore = null;
    }
    function launchForkById(index, takeId) {
        const record = recordOf(index, takeId);
        if (record) launchFork(index, record);
    }
    window.H3Takes = { render: renderTakes, previewUrl, recompute, rescan, onShow, state: T, generate, highlight, launchForkById, predOf, effPred, takeSettings, revealBeside, restoreView,
        recordOf, branchesList: () => branchesList(), clipLength,
        useStudio, resetProject, zoomable, branchHasTakes: (b) => branchHasTakes(b), activeBranch: () => (T.resolved && T.resolved.branch) || null, hideZoom, confirmStartVideo, takeCount, changeSize, changeRefSize, changeSong, branchOfRecord, openExport, refresh: () => studioPoll() };
})();
