// ---------------------------------------------------------------------------------------------
// Encore - the launch panel (chantier A): every generation opens it, docked on the right of the Takes screen.
// « New take » of a take (fork): pre-filled with that take's portion of plan, seed and settings. « Next clip » after a
// take (or clip 1 of a branch): pre-filled with the clip of the twig's plan, a random seed (a new take too, 0.49.1: its
// take's seed can be put back) and the branch's settings.
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
        const band = (L && L.opts && L.opts.branch) || null;     // 0.49: clips taken over after clips left free
        while (cur) { out.unshift(cur.r.id); cur = byId.get(tk().effPred(cur.r, cur.index, band)); }
        return out;
    }
    // the twigs that go through a take: the take itself, then every end of a branch of takes made after it
    function twigsThrough(T, id) {
        if (!id) return [null];
        const list = allTakes(T);
        const children = new Map();
        const band = (L && L.opts && L.opts.branch) || null;
        for (const x of list) { const p = tk().effPred(x.r, x.index, band); if (p) (children.get(p) || children.set(p, []).get(p)).push(x); }
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
        // a cell of the master line (0.48): the clip of the master plan as it is, no twig to choose
        L = { opts, T, studio, index, start, twigs: [], planFrom: start, editorBefore: null, box: null, node: null, seedIn: null };
        L.twigs = opts.mode === "line" ? [] : twigsThrough(T, start);
        // the editor is borrowed: what it showed is put back when the panel closes
        const S = ed().state;
        L.editorBefore = { plan: S.plan, fileName: S.fileName, sel: S.sel, locked: S.locked, takes: S.lockedTakes, dirty: S.dirty };
        build();
        studio.setMediaBranch(opts.branch);
        await loadPlan(start);
        drawTwigs();
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
        try { res = await L.studio.twigPlan(L.opts.branch, L.opts.mode === "line" ? null : leaf); }
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
        // the master line takes the clip of the master plan as it is: shown read-only
        ed().setPlan(plan, L.title, null, L.opts.mode === "line" ? { locked: k, sel: k - 1, lineCell: true } : { locked: 0, sel: k - 1, lockLength: res.lock_length || [] });
        drawWhole();
    }

    // a next clip that no plan has: a copy of the clip before (texts, subjects, length, lines…), a new name,
    // continuing it (↪); the opening sentence of its shot 1 is the server's (it follows the link)
    function copyOfPrevious(plan, k) {
        const prev = plan.clips[k - 2];
        // an edited video: a clip after the segment cannot name <Video 1>; the editor's « + clip » knows that case
        if (!prev || (plan.edit_video && /<Video \d+>/.test(prev.description || ""))) return ed().newClip(k, plan, prev || null);
        const c = JSON.parse(JSON.stringify(prev));
        delete c.seed;
        const names = new Set(plan.clips.map((x) => x.name));
        const base = `clip_${String(k).padStart(3, "0")}`;
        let name = base, n = 2;
        while (names.has(name)) name = `${base}_${n++}`;
        c.name = name;
        c.continue = true;
        delete c.defs;                         // the plan's subjects as they are now
        if (c.anchors) { delete c.anchors.first; if (!Object.keys(c.anchors).length) delete c.anchors; }   // its first frames are the previous clip's
        return c;
    }

    // ------------------------------------------------------------------ the panel
    function build() {
        const o = L.opts, k = L.index;
        const br = (tk().branchesList() || []).find((b) => b.id === o.branch) || { name: o.branch };
        L.title = o.mode === "fork" ? _t("launch.title_fork", { index: k }) : o.mode === "line" ? _t("launch.title_line", { index: k, name: br.name })
            : k === 1 ? _t("launch.title_first", { name: br.name }) : _t("launch.title_next", { index: k });
        const after = o.after ? _t("launch.after_take", { index: k - 1, take: short(o.after) }) : "";
        L.msg = h("div", { class: "warnline", hidden: false });
        L.go = h("button", { class: "primary", onclick: launch }, _t("launch.generate"));
        // 0.49.1: a new take starts with a new seed; the seed of the take redone can be put back
        L.seedIn = h("input", { class: "launch-seed", value: String(randomSeed()) });
        L.ident = h("div", { class: "warnline", hidden: true }, _t("launch.identical"));
        L.genBox = h("div", {}, h("span", { class: "hint" }, "…"));
        L.whole = h("div", { class: "launch-whole", hidden: true });
        // « plan of the following clips » (0.48.2): drawn once the plans of the twigs are known (drawTwigs)
        L.twigBox = h("div", { class: "launch-twigs" });
        const twigList = L.twigBox;
        L.node = h("aside", { id: "launchPanel", class: "launch-panel" },
            h("div", { class: "launch-head" }, h("b", {}, L.title), h("span", { class: "hint" }, `${br.name}${after ? " · " + after : ""}`),
                h("span", { style: "flex:1" }), h("button", { class: "small", title: "Échap", onclick: close }, "✕")),
            h("div", { class: "launch-body", id: "launchBody" },
                twigList, L.whole,
                h("div", { id: "launchEditor" }),
                h("div", { class: "card launch-gen" }, h("h2", {}, _t("launch.generation")),
                    h("div", { class: "launch-seedrow" }, h("label", {}, _t("launch.seed")), L.seedIn,
                        h("button", { class: "small", title: _t("launch.new_seed"), onclick: () => { L.seedIn.value = String(randomSeed()); tick(); } }, "🎲"),
                        h("span", { class: "hint" }, _t("launch.seed_random")),
                        o.mode === "fork" && o.record.seed != null ? h("button", { class: "small launch-seed-back", title: _t("launch.seed_back_title", { seed: o.record.seed }),
                            onclick: () => { L.seedIn.value = String(o.record.seed); tick(); } }, _t("launch.seed_back")) : null),
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
                h("span", { class: "launch-prompt" }, String(c.prompt_override || c.summary || c.description || "").replace(/\s+/g, " ").slice(0, 160)))));
    }
    // ------------------------------------------------------------------ the plan of the following clips (0.48.2)
    // One choice per distinct plan, not per twig: twigs whose plans are the same from this clip on are one choice. Each
    // shows the takes of its twig as small thumbnails (the place of the new take dashed), how far it goes and what its
    // plan changes. When every twig has the same plan, the section is not shown: the choice would change nothing.
    function rangeText(list) {
        const parts = [];
        for (let i = 0; i < list.length; i++) {
            let j = i;
            while (j + 1 < list.length && list[j + 1] === list[j] + 1) j++;
            parts.push(j > i + 1 ? _t("launch.range", { a: list[i], b: list[j] }) : j === i + 1 ? `${list[i]}, ${list[j]}` : String(list[i]));
            i = j;
        }
        return parts.join(", ");
    }
    const bare = (c) => { if (!c || typeof c !== "object") return c; const x = { ...c }; delete x.defs; delete x.seed; return x; };
    function diffText(a, b, from) {
        const mod = [], add = [], rem = [];
        for (let i = from; i < Math.max(a.length, b.length); i++) {
            if (i >= b.length) rem.push(i + 1);
            else if (i >= a.length) add.push(i + 1);
            else if (JSON.stringify(bare(a[i])) !== JSON.stringify(bare(b[i]))) mod.push(i + 1);
        }
        const out = [];
        if (mod.length) out.push(_t(mod.length > 1 ? "launch.diff_modified_n" : "launch.diff_modified", { list: rangeText(mod) }));
        if (add.length) out.push(_t(add.length > 1 ? "launch.diff_added_n" : "launch.diff_added", { list: rangeText(add) }));
        if (rem.length) out.push(_t(rem.length > 1 ? "launch.diff_removed_n" : "launch.diff_removed", { list: rangeText(rem) }));
        return out.join(", ");
    }
    function twigThumbs(leaf, k) {
        const chain = leaf ? chainOf(L.T, leaf) : [];
        const n = Math.max(chain.length, k);
        const out = [];
        for (let i = 1; i <= n; i++) {
            if (i === k && L.opts.mode !== "line") { out.push(h("span", { class: "launch-th new", title: _t("launch.the_new_take") }, String(i))); continue; }
            const id = chain[i - 1];
            const cell = h("span", { class: "launch-th", title: id ? `${i} · ${short(id)}` : String(i) }, String(i));
            if (id && tk().previewUrl) tk().previewUrl(id).then((url) => {
                if (!url || !L) return;
                const v = h("video", { muted: true, preload: "metadata", playsinline: true });
                v.muted = true;
                v.addEventListener("loadeddata", () => { v.currentTime = Math.min(0.5, (v.duration || 1) / 3); }, { once: true });
                v.src = url;
                cell.replaceChildren(v);
            });
            out.push(cell);
        }
        return h("div", { class: "launch-ths" }, ...out);
    }
    async function drawTwigs() {
        const box = L && L.twigBox;
        if (!box) return;
        const whole = h("button", { class: "small", onclick: () => { L.whole.hidden = !L.whole.hidden; drawWhole(); } }, _t("launch.whole_plan"));
        box.replaceChildren(whole);
        if (L.twigs.length < 2) return;
        const k = L.index, from = L.opts.mode === "fork" ? k : k - 1;       // 0-based: the clips the choice decides
        const plans = await Promise.all(L.twigs.map((leaf) => L.studio.twigPlan(L.opts.branch, leaf).then((r) => r.plan.clips || []).catch(() => null)));
        if (!L || L.twigBox !== box) return;
        const groups = [];
        L.twigs.forEach((leaf, i) => {
            if (!plans[i]) return;
            // a generated clip carries what it was made with (defs) and its seed: not a change of plan
            const key = JSON.stringify(plans[i].slice(from).map(bare));
            let g = groups.find((x) => x.key === key);
            if (!g) groups.push(g = { key, leaves: [], clips: plans[i] });
            g.leaves.push(leaf);
        });
        if (groups.length < 2) return;
        const depth = (leaf) => (leaf ? chainOf(L.T, leaf).length : 0);
        const base = groups.find((g) => g.leaves.includes(L.start)) || groups[0];
        const ordered = [base, ...groups.filter((g) => g !== base)];
        const rows = ordered.map((g) => {
            const rep = g.leaves.reduce((a, b) => (depth(b) > depth(a) ? b : a), g.leaves[0]);
            const mine = g === base;
            const others = g.leaves.filter((x) => x !== L.start);
            const title = mine ? (L.opts.mode === "fork" ? _t("launch.plan_this_take") : _t("launch.plan_take_before", { index: k - 1 }))
                : _t("launch.plan_twig_to", { index: depth(rep) });
            const tag = mine ? null : diffText(base.clips, g.clips, from);
            const pick = () => loadPlan(rep).then(() => { highlightTwig(rep); for (const r of box.querySelectorAll(".launch-opt")) r.classList.toggle("on", r === row); });
            const row = h("label", { class: `launch-opt${g.leaves.includes(L.planFrom) ? " on" : ""}`, onmouseenter: () => highlightTwig(rep), onmouseleave: () => highlightTwig(L.planFrom) },
                h("input", { type: "radio", name: "launchTwig", checked: g.leaves.includes(L.planFrom) || null, onchange: pick }),
                h("div", { class: "launch-opt-body" },
                    h("div", {}, h("span", {}, title), mine ? h("span", { class: "hint" }, " · " + _t("launch.plan_as_made")) : null,
                        tag ? h("span", { class: "launch-tag" }, tag) : null),
                    twigThumbs(rep, k),
                    mine && others.length ? h("div", { class: "hint" }, _t("launch.kept_by", { count: others.length, index: Math.max(...others.map(depth)) })) : null));
            return row;
        });
        const intro = L.opts.mode === "fork" ? _t("launch.following_intro_fork", { index: k, next: k + 1 }) : _t("launch.following_intro_next", { index: k });
        box.replaceChildren(h("h2", {}, _t("launch.following_plan")), h("div", { class: "hint" }, intro), ...rows, whole);
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
        const job = o.mode === "line"
            ? await tk().generate(k, { branch: o.branch, line: true, seed, loras: gen.loras, upscaleSettings: gen.upscale_settings })
            : await tk().generate(k, { after: o.after || null, planFrom: L.planFrom, entry, seed, branch: o.branch,
                loras: gen.loras, upscaleSettings: gen.upscale_settings, editInstruction: plan.edit_video ? plan.edit_video.instruction ?? null : null });
        if (job) close(); else if (L) L.go.disabled = false;
    }

    window.H3Launch = { open, close, isOpen: () => !!L };
})();
