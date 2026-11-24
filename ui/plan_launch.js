// ---------------------------------------------------------------------------------------------
// Encore - the launch panel (chantier A): every generation opens it, docked on the right of the Takes screen.
// « New take » of a take (fork): pre-filled with that take's portion of plan, seed and settings. « Next clip » after a
// take (or clip 1 of a branch): pre-filled with the clip of the twig's plan, a random seed and the branch's settings.
// The clip is edited with the plan editor itself (its #editor and #side are moved into the panel while it is open).
// When several twigs go through the take it starts from, the panel lets the user choose whose plan it starts from,
// and lights them up in the graph.
// ---------------------------------------------------------------------------------------------
(() => {
    const $ = (id) => document.getElementById(id);
    const ed = () => window.H3Editor;
    const tk = () => window.H3Takes;
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
    const MAX_SEED = 2 ** 48;
    const randomSeed = () => Math.floor(Math.random() * 2 ** 24) * 2 ** 24 + Math.floor(Math.random() * 2 ** 24);
    const short = (id) => (id ? String(id).split("_").pop().slice(0, 4) : "");
    let L = null;          // the open panel

    // ------------------------------------------------------------------ twigs
    function allTakes(T) { return Object.entries(T.takes || {}).flatMap(([i, list]) => list.map((r) => ({ index: +i, r }))); }
    // the chain of take ids from clip 1 to this take
    function chainOf(T, id) {
        const byId = new Map(allTakes(T).map((x) => [x.r.id, x]));
        const out = [];
        let cur = byId.get(id);
        while (cur) { out.unshift(cur.r.id); cur = byId.get(tk().effPred(cur.r, cur.index)); }
        return out;
    }
    // the twigs that go through a take: the take itself, then every end of a branch of takes made after it
    function twigsThrough(T, id) {
        if (!id) return [null];
        const list = allTakes(T);
        const children = new Map();
        for (const x of list) { const p = tk().effPred(x.r, x.index); if (p) (children.get(p) || children.set(p, []).get(p)).push(x); }
        const leaves = [];
        const walk = (tid) => { for (const c of children.get(tid) || []) { if ((children.get(c.r.id) || []).length) walk(c.r.id); else leaves.push(c.r.id); } };
        walk(id);
        return [id, ...leaves];
    }

    // ------------------------------------------------------------------ opening and closing
    async function open(opts) {
        if (L) close();
        const T = opts.takesState, studio = T.studio;
        const index = opts.index;
        const start = opts.mode === "fork" ? opts.record.id : opts.after || null;
        const twigs = twigsThrough(T, start);
        L = { opts, T, studio, index, start, twigs, planFrom: start, editorBefore: null, box: null, node: null, seedIn: null };
        // the editor is borrowed: what it showed is put back when the panel closes
        const S = ed().state;
        L.editorBefore = { plan: S.plan, fileName: S.fileName, sel: S.sel, locked: S.locked, takes: S.lockedTakes, dirty: S.dirty };
        build();
        studio.setMediaBranch(opts.branch);
        await loadPlan(start);
        const preset = opts.mode === "fork" ? presetOf(opts.record) : null;
        L.box = await studio.generationBox(opts.branch, preset);
        L.genBox.replaceChildren(L.box.node);
        document.body.classList.add("launching");
        tk().revealBeside(start, L.node.getBoundingClientRect().width);
        highlightTwig(L.planFrom);
        tick();
    }
    function presetOf(record) {
        const st = (record && record.studio) || {};
        return { loras: st.extra_loras || [], upscale_settings: st.upscale ? { ...(st.upscale.settings || {}), enabled: true } : { enabled: false } };
    }
    function close() {
        if (!L) return;
        clearTimeout(L.timer);
        const pv = $("planView"), editor = $("editor"), side = $("side");
        if (editor && pv) pv.append(editor);
        if (side && pv) pv.append(side);
        L.studio.setMediaBranch(null);
        const b = L.editorBefore;
        if (b && b.plan) {
            ed().setPlan(b.plan, b.fileName, null, { locked: b.locked, takes: b.takes, sel: b.sel });
            ed().state.dirty = b.dirty;
        }
        L.node.remove();
        document.body.classList.remove("launching");
        tk().restoreView();
        tk().highlight([]);
        L = null;
    }

    // the plan the new take starts from: the twig's plan, with the clip of the take forked
    async function loadPlan(leaf) {
        L.planFrom = leaf;
        L.msg.textContent = "";
        let res;
        try { res = await L.studio.twigPlan(L.opts.branch, leaf); }
        catch (e) { L.msg.textContent = e.message; return; }
        L.twig = res;
        const plan = JSON.parse(JSON.stringify(res.plan));
        const k = L.index;
        if (L.opts.mode === "fork") {
            const portion = (L.opts.record.studio || {}).portion;
            if (portion && portion.clip) {
                plan.clips[k - 1] = JSON.parse(JSON.stringify(portion.clip));
                if (portion.edit_instruction != null && plan.edit_video) plan.edit_video.instruction = portion.edit_instruction;
            }
        }
        // the next clip, when the twig's plan has none: the master plan's, else a new clip after the one before
        if (L.opts.mode === "next" && !plan.clips[k - 1] && plan.clips.length === k - 1) {
            let fromMaster = null;
            try { fromMaster = ((await L.studio.twigPlan(L.opts.branch, null)).plan.clips || [])[k - 1] || null; } catch (_) { /* no master plan */ }
            plan.clips.push(fromMaster ? JSON.parse(JSON.stringify(fromMaster)) : copyOfPrevious(plan, k));
            L.msg.textContent = fromMaster ? _t("launch.clip_from_master") : _t("launch.clip_new");
        }
        L.original = plan.clips[k - 1] ? JSON.stringify(plan.clips[k - 1]) : null;
        if (!plan.clips[k - 1]) {
            L.msg.textContent = _t("launch.no_clip_in_plan", { index: k });
            L.go.disabled = true;
            return;
        }
        L.go.disabled = false;
        ed().setPlan(plan, L.title, null, { locked: 0, sel: k - 1 });
        drawWhole();
    }

    // a next clip that no plan has: a copy of the clip before (prompt, length, references, lines…), a new name,
    // continuing it (↪); the opening sentence of its detailed description follows the link
    function copyOfPrevious(plan, k) {
        const prev = plan.clips[k - 2];
        // an edited video: a clip after the segment cannot reuse <Video 1>; the editor's « + clip » knows that case
        if (!prev || (plan.edit_video && /<Video \d+>/.test(prev.prompt || ""))) return ed().newClip(k, plan, prev || null);
        const c = JSON.parse(JSON.stringify(prev));
        delete c.seed;
        const names = new Set(plan.clips.map((x) => x.name));
        const base = `clip_${String(k).padStart(3, "0")}`;
        let name = base, n = 2;
        while (names.has(name)) name = `${base}_${n++}`;
        c.name = name;
        c.continue = true;
        const parts = H3.parseSections(c.prompt || "");
        if (parts) {
            const det = H3Sections.parseDetailed(parts[3]);
            if (!H3Sections.customOpening(det)) {
                parts[3] = H3Sections.composeDetailed(det.style, det.shots, H3Sections.expectedSentence(c, k, H3.mode(plan) === "free", !!plan.start_video));
                c.prompt = H3.composeSections(parts);
            }
        }
        return c;
    }

    // ------------------------------------------------------------------ the panel
    function build() {
        const o = L.opts, k = L.index;
        const br = (tk().branchesList() || []).find((b) => b.id === o.branch) || { name: o.branch };
        L.title = o.mode === "fork" ? _t("launch.title_fork", { index: k }) : k === 1 ? _t("launch.title_first", { name: br.name }) : _t("launch.title_next", { index: k });
        const after = o.after ? _t("launch.after_take", { index: k - 1, take: short(o.after) }) : "";
        L.msg = h("div", { class: "warnline", hidden: false });
        L.go = h("button", { class: "primary", onclick: launch }, _t("launch.generate"));
        L.seedIn = h("input", { class: "launch-seed", value: String(o.mode === "fork" ? o.record.seed ?? randomSeed() : randomSeed()) });
        L.ident = h("div", { class: "warnline", hidden: true }, _t("launch.identical"));
        L.genBox = h("div", {}, h("span", { class: "hint" }, "…"));
        L.whole = h("div", { class: "launch-whole", hidden: true });
        const twigList = L.twigs.length > 1 ? h("div", { class: "launch-twigs" },
            h("h2", {}, _t("launch.start_from_plan_of")),
            L.twigs.map((leaf) => {
                const chain = chainOf(L.T, leaf);
                const label = chain.map((id, i) => `${i + 1}${short(id) ? "·" + short(id) : ""}`).join(" → ");
                const row = h("label", { class: "launch-twig", onmouseenter: () => highlightTwig(leaf), onmouseleave: () => highlightTwig(L.planFrom) },
                    h("input", { type: "radio", name: "launchTwig", checked: leaf === L.planFrom || null, onchange: () => loadPlan(leaf).then(() => highlightTwig(leaf)) }),
                    h("span", {}, label), leaf === L.start ? h("span", { class: "hint" }, _t("launch.the_take_itself")) : null);
                return row;
            }),
            h("button", { class: "small", onclick: () => { L.whole.hidden = !L.whole.hidden; drawWhole(); } }, _t("launch.whole_plan")))
            : h("div", {}, h("button", { class: "small", onclick: () => { L.whole.hidden = !L.whole.hidden; drawWhole(); } }, _t("launch.whole_plan")));
        L.node = h("aside", { id: "launchPanel", class: "launch-panel" },
            h("div", { class: "launch-head" }, h("b", {}, L.title), h("span", { class: "hint" }, `${br.name}${after ? " · " + after : ""}`),
                h("span", { style: "flex:1" }), h("button", { class: "small", title: "Échap", onclick: close }, "✕")),
            h("div", { class: "launch-body", id: "launchBody" },
                twigList, L.whole,
                h("div", { id: "launchEditor" }),
                h("div", { class: "card launch-gen" }, h("h2", {}, _t("launch.generation")),
                    h("div", { class: "launch-seedrow" }, h("label", {}, _t("launch.seed")), L.seedIn,
                        h("button", { class: "small", title: _t("launch.new_seed"), onclick: () => { L.seedIn.value = String(randomSeed()); tick(); } }, "🎲"),
                        h("span", { class: "hint" }, o.mode === "fork" ? _t("launch.seed_of_take") : _t("launch.seed_random"))),
                    L.genBox),
                L.ident),
            h("div", { class: "launch-foot" }, L.msg, h("span", { style: "flex:1" }), h("button", { onclick: close }, _t("launch.cancel")), L.go));
        document.body.append(L.node);
        const host = $("launchEditor");
        host.append($("editor"), $("side"));
        L.node.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    }
    function drawWhole() {
        if (!L || L.whole.hidden || !L.twig) return;
        const p = L.twig.plan, locked = L.twig.locked || 0;
        L.whole.replaceChildren(h("h2", {}, _t("launch.whole_plan_title")),
            ...p.clips.map((c, i) => h("div", { class: `launch-clip${i + 1 === L.index ? " cur" : ""}${i < locked ? " locked" : ""}` },
                h("b", {}, `${i < locked ? "🔒" : ""}${i + 1} ${c.continue ? "↪" : i ? "✂" : ""} ${c.name || ""}`),
                h("span", { class: "hint" }, ` ${tk().clipLength(c.frames) || ""} · `),
                h("span", { class: "launch-prompt" }, String(c.prompt || "").replace(/\s+/g, " ").slice(0, 160)))));
    }
    function highlightTwig(leaf) {
        if (!L) return;
        const ids = leaf ? chainOf(L.T, leaf) : [];
        tk().highlight(ids);
    }
    // the warning « identical to the take forked », kept up to date while the panel is open
    function tick() {
        if (!L) return;
        clearTimeout(L.timer);
        if (L.opts.mode === "fork") {
            const clip = (ed().state.plan.clips || [])[L.index - 1];
            const same = clip && JSON.stringify(clip) === L.original && String(L.seedIn.value).trim() === String(L.opts.record.seed)
                && !(L.box && L.box.changed());
            L.ident.hidden = !same;
        }
        L.timer = setTimeout(tick, 700);
    }

    async function launch() {
        if (!L) return;
        const raw = String(L.seedIn.value).trim();
        const seed = raw === "" ? null : Number(raw);
        if (raw !== "" && !(Number.isInteger(seed) && seed >= 0 && seed <= MAX_SEED)) { alert(_t("studio.invalid_seed_an_integer_from_0", { v0: MAX_SEED })); return; }
        const plan = ed().state.plan;
        const entry = JSON.parse(JSON.stringify(plan.clips[L.index - 1]));
        const gen = L.box ? L.box.value() : {};
        const k = L.index, o = L.opts;
        L.go.disabled = true;
        const job = await tk().generate(k, { after: o.after || null, planFrom: L.planFrom, entry, seed, branch: o.branch,
            loras: gen.loras, upscaleSettings: gen.upscale_settings, editInstruction: plan.edit_video ? plan.edit_video.instruction ?? null : null });
        if (job) close(); else if (L) L.go.disabled = false;
    }

    window.H3Launch = { open, close, isOpen: () => !!L };
})();
