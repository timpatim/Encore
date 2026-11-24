// ---------------------------------------------------------------------------------------------
// Encore - projects, imports, references and settings on top of the plan editor.
// Active only when the page is served by Encore (/api/ping answers "h3studio").
// ---------------------------------------------------------------------------------------------
(() => {
    const RATIOS = [["16:9", 16 / 9], ["9:16", 9 / 16], ["4:3", 4 / 3], ["3:4", 3 / 4], ["3:2", 3 / 2], ["2:3", 2 / 3]];
    // same megapixels and same sizes as ComfyUI: 1 MP = 1024 × 1024 pixels, each side rounded to a multiple of 32
    const MEGAPIXELS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.98, 1.0, 1.2, 1.5, 1.8, 2.0];
    const MPX = 1024 * 1024;
    const round32 = (v) => Math.max(64, Math.round(v / 32) * 32);
    // replaceChildren without the empty parts (null, false…), which it would write as text (« null »)
    const fill = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
    // ComfyUI's lists (object_info): the values of a node's combo input
    const COMBOS = {
        unet_name: ["UNETLoader", "unet_name"], weight_dtype: ["UNETLoader", "weight_dtype"],
        clip_name: ["CLIPLoader", "clip_name"], clip_type: ["CLIPLoader", "type"],
        video_vae: ["VAELoader", "vae_name"], audio_vae: ["VAELoader", "vae_name"],
        attention: ["ModelAttentionBackend", "attention"], lora_name: ["LoraLoaderModelOnly", "lora_name"],
        sampler_name: ["KSamplerSelect", "sampler_name"], scheduler: ["BasicScheduler", "scheduler"],
        song: ["LoadAudio", "audio"],
    };
    function comboValues(info, nodeClass, input) {
        const node = info && info[nodeClass];
        if (!node) return null;
        const spec = (node.input?.required || {})[input] || (node.input?.optional || {})[input];
        if (!spec) return null;
        if (Array.isArray(spec[0])) return spec[0];
        if (spec[0] === "COMBO" && spec[1] && Array.isArray(spec[1].options)) return spec[1].options;
        return null;
    }
    function presets() {
        const out = [];
        for (const [label, r] of RATIOS) {
            for (const mp of MEGAPIXELS) {
                const w = round32(Math.sqrt(mp * MPX * r)), h = round32(Math.sqrt(mp * MPX / r));
                out.push({ ratio: label, mp, w, h, real: (w * h) / MPX });
            }
        }
        return out;
    }
    const zoom = (img, label) => (window.H3Takes && window.H3Takes.zoomable ? window.H3Takes.zoomable(img, label) : img);
    const fmtMp = (v) => v.toFixed(2).replace(/0$/, "").replace(".", H3I18n.decimal());

    const P = { name: null, settings: null, branches: [], resources: null, info: null, config: null, saveTimer: null };
    const ed = () => window.H3Editor;
    const $ = (id) => document.getElementById(id);
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
        for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid instanceof Node ? kid : String(kid));
        return node;
    }
    async function api(path, options = {}) {
        // X-Encore: the server refuses a write without it, which another web page cannot send (CSRF)
        const response = await fetch(path, { ...options, headers: { ...(options.headers || {}), "X-Encore": "1" } });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (_) { data = { error: text }; }
        if (!response.ok || (data && data.error)) {
            const error = new Error((data && data.error) || `HTTP ${response.status}`);
            error.code = data && data.code;          // a fixed word (the message is translated)
            throw error;
        }
        return data;
    }
    const put = (path, body) => api(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const fileUrl = (rel) => `/files/${encodeURIComponent(P.name)}/${rel.split("/").map(encodeURIComponent).join("/")}`;
    const toast = (t) => ed().toast(t);
    const plan = () => ed().state.plan;

    // the Encore icon (the same drawing as web/encore_icon.svg)
    function logo(size = 20) {
        const src = (document.querySelector('link[rel="icon"]') || {}).href || "";
        return h("img", { class: "studio-logo", src, width: size, height: size, alt: "" });
    }
    // windows opened later always come on top of those opened before (installation screen, dialogs, folder browser…)
    let zTop = 100;
    const nextZ = () => ++zTop;
    function modal(title, body, { wide = false, onClose } = {}) {
        const close = () => { overlay.remove(); onClose && onClose(); };
        const overlay = h("div", { class: "tk-modal", style: `z-index:${nextZ()}`, onclick: (e) => { if (e.target === overlay) close(); } },
            h("div", { class: `tk-box tk-form${wide ? " wide" : ""}` },
                h("div", { class: "tk-box-head" }, h("b", {}, title), h("span", { style: "flex:1" }), h("button", { onclick: close }, _t("studio.close"))), body));
        document.body.append(overlay);
        return { overlay, close };
    }
    function pickFiles(accept, multiple) {
        return new Promise((resolve) => {
            const input = h("input", { type: "file", accept, multiple: multiple || null, hidden: true });
            input.addEventListener("change", () => { resolve([...input.files]); input.remove(); });
            document.body.append(input);
            input.click();
        });
    }

    // ------------------------------------------------------------------ start
    function checkVersion(server) {
        const page = window.ENCORE_BUILD;
        const old = document.getElementById("encoreVersionBanner");
        if (!page || !server || server === page) { if (old) old.remove(); return; }
        if (old) return;
        document.body.prepend(h("div", { id: "encoreVersionBanner", class: "encore-version-banner" },
            _t("studio.version_mismatch", { page, server }), " ",
            h("button", { class: "small", onclick: () => location.reload() }, _t("studio.reload_the_page"))));
    }
    async function start() {
        try {
            const ping = await api("/api/ping");
            if (ping.app !== "encore") return;
            checkVersion(ping.version);
        } catch (_) { return; }
        // a server updated (or an old one still running) while the page is open: say so
        setInterval(() => api("/api/ping").then((p) => checkVersion(p.version)).catch(() => {}), 30000);
        document.body.classList.add("studio");
        document.title = "Encore";
        ed().saveHook = savePlan;
        if (window.H3Takes) window.H3Takes.useStudio(takesApi());
        decorateHeader();
        P.config = await api("/api/config");
        if (await needsSetup()) {
            await new Promise((resolve) => { afterSetup = resolve; openSetup({ blocking: true }); });
            P.config = await api("/api/config");
        }
        let last = null;
        try { last = localStorage.getItem("h3studio.project"); } catch (_) { last = null; }
        if (P.config.configured && last) {
            try { await openProject(last); return; } catch (_) { /* fall back to the list */ }
        }
        showHome();
    }

    function decorateHeader() {
        for (const id of ["newMenu", "btnOpen", "btnSaveAs"]) { const el = $(id); if (el) el.style.display = "none"; }
        // two rows: the application (all projects) above, the open project below
        const header = document.querySelector("header");
        const title = header.querySelector(".title");
        if (title) title.style.display = "none";
        const app = h("div", { class: "studio-app" },
            h("span", { class: "studio-app-title" }, logo(34), "Encore"),
            h("button", { onclick: showHome, title: _t("studio.project_list") }, _t("studio.projects")),
            h("button", { onclick: () => openSettings({ defaults: true }), title: _t("studio.settings_template_for_new_projects") }, _t("studio.default_settings_2")),
            h("button", { onclick: () => openSetup(), title: _t("studio.comfyui_custom_nodes_and_default_models") }, _t("studio.installation_2")),
            h("span", { class: "spacer" }),
            // light / dark, saved in Encore's settings
            h("button", { id: "studioThemeBtn", class: "studio-theme-btn", onclick: () => setTheme(H3Theme.get() === "light" ? "dark" : "light") }),
            // ComfyUI connection: green / orange / red; a click shows the details
            h("button", { id: "studioComfyBtn", class: "studio-comfy-state unknown", onclick: openComfyPanel, title: _t("studio.connection_to_comfyui") },
                h("i", { class: "studio-comfy-dot" }), h("span", { class: "studio-comfy-text" }, _t("studio.comfyui"))),
            // the state of the queue, always in sight; a click opens the generation manager
            h("button", { id: "studioQueueBtn", class: "studio-queue-state idle", onclick: openQueue, title: _t("studio.generation_queue_all_projects_click_to") },
                h("span", { class: "studio-qs-text" }, _t("studio.empty_queue")), h("span", { class: "studio-qs-bar" }, h("i", {}))));
        header.before(app);
        header.classList.add("studio-project-row");
        showThemeButton();
        $("viewTabs").before(h("span", { class: "studio-project-label" }, _t("studio.project"), h("b", { id: "studioProject", class: "studio-project" }, "")));
        const anchor = $("btnSave");
        const bar = h("span", { class: "studio-bar" },
            h("button", { onclick: importPlan }, _t("studio.import_a_plan")),
            h("button", { onclick: openResources }, _t("studio.resources")),
            h("button", { onclick: openCheckpoints }, _t("studio.checkpoints_2")),
            h("button", { onclick: openExports }, _t("studio.assembled_videos")),
            h("button", { onclick: () => openSettings() }, _t("studio.project_settings")));
        anchor.before(bar);
    }

    // ------------------------------------------------------------------ theme
    function showThemeButton() {
        const b = $("studioThemeBtn");
        if (!b) return;
        const light = H3Theme.get() === "light";
        b.textContent = light ? "☾" : "☀";
        b.title = light ? _t("studio.theme_to_dark") : _t("studio.theme_to_light");
    }
    async function setTheme(theme) {
        H3Theme.set(theme);
        showThemeButton();
        try { await put("/api/config", { theme }); } catch (e) { toast(e.message); }
    }
    document.addEventListener("h3theme", () => { showThemeButton(); const sel = document.querySelector("#studioThemeSelect"); if (sel) sel.value = H3Theme.get(); });

    // the Plan tab shows the pictures, voices and song of a branch: the one of the current selection, else the first
    function mediaBranch() {
        const id = window.H3Takes && window.H3Takes.activeBranch ? window.H3Takes.activeBranch() : null;
        return P.branches.find((b) => b.id === id) || P.branches[0] || null;
    }
    const media = {
        label: () => (mediaBranch() || {}).name || "?",
        image: (name) => { const r = ((mediaBranch() || {}).refs || {})[name]; return r && r.image ? fileUrl(r.image) : null; },
        voice: (name) => { const r = ((mediaBranch() || {}).refs || {})[name]; return r && r.voice ? fileUrl(r.voice) : null; },
        song: () => { const b = mediaBranch(); return b && b.song ? fileUrl(b.song) : null; },
        // the start video: one file for the project, chosen in the plan settings
        video: () => (P.startVideoFile ? fileUrl(P.startVideoFile) : null),
        videos: () => (P.resources && P.resources.videos) || [],
        startVideoFile: () => P.startVideoFile,
        playableVideo: (rel, cls) => playableVideo(rel, cls),
        importVideo: async () => {
            const [file] = await pickFiles(ACCEPT.videos);
            if (!file) return null;
            const [path] = await importFiles("videos", [file]);
            return path;
        },
        // another file: the takes of clip 1 made with the current one (and those that continue them) are listed first
        setStartVideoFile: async (rel) => {
            if ((rel || null) === (P.startVideoFile || null)) return true;
            if (P.startVideoFile && window.H3Takes && window.H3Takes.confirmStartVideo
                && !(await window.H3Takes.confirmStartVideo(rel ? ((P.resources.videos || []).find((v) => v.path === rel) || {}).sha || null : null))) return false;
            const res = await put(`/api/projects/${encodeURIComponent(P.name)}/start-video`, { file: rel || null });
            P.startVideoFile = res.start_video_file || null;
            if (window.H3Takes) window.H3Takes.recompute();
            return true;
        },
        clip1Takes: async () => (window.H3Takes && window.H3Takes.takeCount ? window.H3Takes.takeCount(1) : 0),
        // edited video: the changes of shot in a segment (frames of the file), found by the server with ffmpeg
        sceneCuts: async (rel, start, end) => (await api(`/api/projects/${encodeURIComponent(P.name)}/resources/scenes?path=${encodeURIComponent(rel)}&start=${start}&end=${end}`)).cuts || [],
        branchSizes: () => P.branches.map((b) => ({ id: b.id, name: b.name, width: Number(b.width), height: Number(b.height) })),
        // the branches take the proportions of the video, about the same number of pixels (multiples of 32)
        fitBranchSizes: async (vw, vh, ids) => {
            for (const id of ids) {
                const b = P.branches.find((x) => x.id === id);
                if (!b) continue;
                const area = Number(b.width) * Number(b.height), ratio = vw / vh;
                const r32 = (v) => Math.max(64, Math.round(v / 32) * 32);
                const w = r32(Math.sqrt(area * ratio)), hh = r32(Math.sqrt(area / ratio));
                if (window.H3Takes && !(await window.H3Takes.changeSize(id, w, hh))) return;
                await putBranch(id, { width: w, height: hh });
            }
        },
    };

    // ------------------------------------------------------------------ projects
    async function openProject(name) {
        const data = await api(`/api/projects/${encodeURIComponent(name)}`);
        P.name = data.name;
        P.settings = data.settings;
        P.branches = data.branches || [];
        P.legacyRefSize = data.legacy_ref_image_size || "match";
        P.clipDefaults = data.clip_defaults || {};
        P.startVideoFile = data.start_video_file || null;
        P.resources = data.resources;
        ed().media = media;
        ed().setPlan(data.plan, `${data.name} · plan.json`, null);
        if (window.H3Takes) window.H3Takes.resetProject();
        $("studioProject").textContent = data.name;
        document.title = `${data.name} — Encore`;
        try { localStorage.setItem("h3studio.project", data.name); } catch (_) { /* ignore */ }
        closeHome();
        if (data.validation.errors.length) toast(_t("studio.the_plan_has_error_s_see", { length: data.validation.errors.length }));
    }

    async function savePlan(planObject) {
        if (!P.name) throw new Error(_t("studio.no_project_open"));
        const res = await put(`/api/projects/${encodeURIComponent(P.name)}/plan`, planObject);
        if (res.plan.project !== planObject.project) planObject.project = res.plan.project;
        planObject.version = 3;
        const e = res.validation.errors.length;
        toast(res.notes.length ? res.notes.join(" ; ") : e ? _t("studio.plan_saved_error_s_to_fix", { e }) : _t("studio.plan_saved_in_the_project"));
    }

    async function importPlan() {
        if (!P.name) return showHome();
        const [file] = await pickFiles(".json,application/json");
        if (!file) return;
        if (ed().state.dirty && !await H3Dialog.confirm(_t("studio.the_plan_shown_has_unsaved_changes"))) return;
        try {
            const res = await api(`/api/projects/${encodeURIComponent(P.name)}/import-plan?filename=${encodeURIComponent(file.name)}`,
                { method: "POST", body: await file.arrayBuffer() });
            ed().setPlan(res.plan, `${P.name} · plan.json`, null);
            toast(_t("studio.copied_into_the_project_the_old", { name: file.name }));
        } catch (e) { alert(e.message); }
    }

    function closeHome() { const el = $("studioHome"); if (el) el.remove(); }

    async function showHome() {
        closeHome();
        P.config = await api("/api/config");
        const home = h("div", { id: "studioHome", class: "studio-home" });
        document.body.append(home);
        const comfyState = h("span", { class: "hint" }, _t("studio.checking"));
        api("/api/comfy/ping").then((r) => {
            comfyState.textContent = r.ok ? _t("studio.connected", { v0: r.devices?.[0]?.name ? " · " + r.devices[0].name : "" }) : r.error;
            comfyState.className = r.ok ? "ok" : "bad";
        }).catch((e) => { comfyState.textContent = e.message; comfyState.className = "bad"; });
        const rootIn = h("input", { value: P.config.projects_root, style: "flex:1" });
        const urlIn = h("input", { value: P.config.comfy_url, style: "width:260px" });
        const saveCfg = async (changes) => {
            try { P.config = await post("/api/config", { ...changes, configured: true }); showHome(); }
            catch (e) { alert(e.message); }
        };
        let list = { projects: [] };
        try { list = await api("/api/projects"); } catch (e) { /* root may not exist yet */ }
        const nameIn = h("input", { placeholder: "nom_du_projet", pattern: "[A-Za-z0-9][A-Za-z0-9_-]*" });
        const modeSel = h("select", {}, h("option", { value: "free" }, _t("studio.free_sound_generated_by_h3")), h("option", { value: "music_video" }, _t("studio.music_video_song_provided")));
        const create = async () => {
            try {
                const res = await post("/api/projects", { name: nameIn.value.trim(), mode: modeSel.value });
                if (!P.config.configured) await post("/api/config", { configured: true });
                await openProject(res.name);
            } catch (e) { alert(e.message); }
        };
        home.append(h("div", { class: "studio-home-box" },
            h("div", { class: "studio-home-head" }, h("h1", { class: "studio-home-title" }, logo(64), "Encore"), h("span", { class: "hint" }, `version ${P.config.studio_version}`),
                h("span", { style: "flex:1" }), P.name ? h("button", { onclick: closeHome }, _t("studio.back_to", { name: P.name })) : null),
            !P.config.configured ? h("div", { class: "studio-first" },
                h("b", {}, _t("studio.first_launch")), h("p", {}, _t("studio.choose_the_folder_where_encore_keeps"))) : null,
            h("section", {}, h("h3", {}, _t("studio.projects_folder")),
                h("div", { class: "tk-inline" }, rootIn,
                    h("button", { onclick: async () => { const path = await browseFolder(rootIn.value); if (path) rootIn.value = path; } }, _t("studio.browse")),
                    h("button", { onclick: () => saveCfg({ projects_root: rootIn.value }) }, _t("studio.use_this_folder"))),
                h("div", { class: "hint" }, _t("studio.full_path_on_this_pc_for"))),
            h("section", {}, h("h3", {}, "ComfyUI"),
                h("div", { class: "tk-inline" }, urlIn, h("button", { onclick: () => saveCfg({ comfy_url: urlIn.value }) }, _t("studio.save")), comfyState),
                h("label", { class: "tk-check", style: "margin-top:6px" }, h("input", { type: "checkbox", checked: P.config.purge_comfy_copy !== false || null,
                    onchange: (e) => saveCfg({ purge_comfy_copy: e.target.checked }) }),
                    _t("studio.empty_the_working_copy_in_comfyui")),
                h("div", { class: "hint" }, _t("studio.custom_nodes_comfyui_s_python_and"), h("button", { class: "small", onclick: () => openSetup() }, _t("studio.installation_2")))),
            h("section", {}, h("h3", {}, _t("studio.default_settings")),
                h("div", { class: "tk-inline" }, h("button", { onclick: () => openSettings({ defaults: true }) }, _t("studio.default_settings_2")),
                    h("span", { class: "hint" }, _t("studio.models_lora_sampling_previews_and_first")))),
            h("section", {}, h("h3", {}, _t("studio.checkpoints")),
                h("div", { class: "tk-inline" }, h("label", {}, _t("studio.automatic_checkpoints_kept_per_project")),
                    h("input", { type: "number", min: 0, value: P.config.checkpoint_limit || 0, style: "width:80px",
                        onchange: (e) => saveCfg({ checkpoint_limit: Math.max(0, Math.trunc(Number(e.target.value) || 0)) }) }),
                    h("span", { class: "hint" }, _t("studio.0_no_limit_manual_checkpoints_are")))),
            h("section", {}, h("h3", {}, _t("studio.new_project")),
                h("div", { class: "tk-inline" }, nameIn, modeSel, h("button", { class: "primary", onclick: create }, _t("studio.create"))),
                h("div", { class: "hint" }, _t("studio.letters_digits_and_it_is_also"))),
            h("section", {}, h("h3", {}, _t("studio.projects_2", { length: list.projects.length })),
                list.projects.length ? h("div", { class: "studio-projects" }, list.projects.map((p) => h("button", { class: `studio-card${p.name === P.name ? " current" : ""}`, onclick: () => openProject(p.name).catch((e) => alert(e.message)) },
                    h("b", {}, p.name), h("span", { class: "hint" }, `${p.mode === "music_video" ? _t("studio.music_video") : _t("studio.free")} · ${p.clips} clip(s)`),
                    h("span", { class: "hint" }, p.updated ? new Date(p.updated * 1000).toLocaleString("fr-FR") : ""))))
                    : h("p", { class: "hint" }, _t("studio.no_project_in_this_folder")))));
    }

    // ------------------------------------------------------------------ choosing a folder
    // A folder browser in the page: the Studio lists the folders of this PC.
    function browseFolder(initial) {
        return new Promise((resolve) => {
            let current = null, result = null;
            const body = h("div", { class: "studio-browser" });
            const dlg = modal(_t("studio.choose_a_folder"), body, { wide: true, onClose: () => resolve(result) });
            const go = async (path) => {
                try { current = await api(`/api/dirs?path=${encodeURIComponent(path || "")}`); }
                catch (e) { alert(e.message); if (current) return; current = await api("/api/dirs"); }
                draw();
            };
            const draw = () => {
                const nameIn = h("input", { placeholder: _t("studio.new_folder"), style: "width:200px" });
                fill(body, 
                    h("div", { class: "tk-inline studio-places" },
                        current.drives.map((d) => h("button", { class: "small", onclick: () => go(d.path) }, d.label)),
                        h("span", { class: "hint" }, " · "),
                        current.places.map((d) => h("button", { class: "small", onclick: () => go(d.path) }, d.label))),
                    h("div", { class: "studio-path" }, current.path || _t("studio.choose_a_drive_or_a_location")),
                    current.path ? h("div", { class: "studio-dirs" },
                        current.parent ? h("button", { class: "studio-dir up", onclick: () => go(current.parent) }, _t("studio.parent_folder")) : null,
                        current.dirs.length ? current.dirs.map((d) => h("button", { class: "studio-dir", onclick: () => go(joinPath(current.path, d)) }, "📁 " + d))
                            : h("div", { class: "hint", style: "padding:6px" }, _t("studio.no_subfolder"))) : null,
                    current.path ? h("div", { class: "tk-inline", style: "margin-top:10px" },
                        nameIn,
                        h("button", { onclick: async () => { try { current = await post("/api/dirs", { path: current.path, name: nameIn.value }); draw(); } catch (e) { alert(e.message); } } }, _t("studio.create")),
                        h("span", { style: "flex:1" }),
                        h("button", { class: "primary", onclick: () => { result = current.path; dlg.close(); } }, _t("studio.choose_this_folder"))) : null);
            };
            go(initial).catch(() => go(""));
        });
    }
    const joinPath = (base, name) => (/[\\/]$/.test(base) ? base + name : base + (base.includes("\\") ? "\\" : "/") + name);

    // ------------------------------------------------------------------ checkpoints
    async function saveIfDirty() {
        if (ed().state.dirty) { await savePlan(ed().state.plan); ed().state.dirty = false; ed().render(); }
    }
    function applyProject(data) {
        P.settings = data.settings;
        P.branches = data.branches || [];
        P.legacyRefSize = data.legacy_ref_image_size || "match";
        P.clipDefaults = data.clip_defaults || {};
        P.startVideoFile = data.start_video_file || null;
        P.resources = data.resources;
        ed().media = media;
        ed().setPlan(data.plan, `${data.name} · plan.json`, null);
        if (window.H3Takes) window.H3Takes.resetProject();
    }
    async function restoreCheckpoint(id, label) {
        if (!await H3Dialog.confirm(_t("studio.restore_the_plan_settings_branches_and", { label }) +
            _t("studio.a_checkpoint_of_the_current_state"))) return false;
        try {
            await saveIfDirty();
            const res = await post(`/api/projects/${encodeURIComponent(P.name)}/checkpoints/${encodeURIComponent(id)}/restore`, {});
            applyProject(res.project);
            toast(_t("studio.state_restored_previous_state", { name: res.saved_before.name }));
            return true;
        } catch (e) { alert(e.message); return false; }
    }
    async function openExports() {
        if (!P.name) return showHome();
        let list = [];
        try { list = (await api(`/api/projects/${encodeURIComponent(P.name)}/exports`)).exports; } catch (e) { alert(e.message); return; }
        const when = (t) => new Date(t * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
        const body = h("div", {},
            h("p", { class: "hint" }, _t("studio.files_in_exports_of_the_projects", { name: P.name })),
            list.length ? h("div", { class: "studio-exports" }, list.map((ex) => h("div", { class: "studio-export" },
                h("video", { controls: true, preload: "metadata", src: `${fileUrl(ex.file)}?t=1` }),
                h("div", { class: "studio-export-info" },
                    h("b", {}, `${ex.name}.mp4`),
                    ex.removed ? h("div", { class: "tk-band-warn" }, _t("studio.branch_removed_restore_the_state_of")) : null,
                    h("div", { class: "hint" }, _t("studio.clips_1_to", { v0: ex.branch_name || "", clips: ex.clips, v2: ex.size ? ex.size.join(" × ") : "", v3: when(ex.created) })),
                    ex.infos ? h("button", { class: "small", title: _t("studio.infos_md_file_the_full_details"), onclick: () => window.open(`/api/projects/${encodeURIComponent(P.name)}/infos?file=${encodeURIComponent(ex.infos)}`, "_blank") }, "infos") : null,
                    ex.checkpoint ? h("button", { class: "small", onclick: async () => { if (await restoreCheckpoint(ex.checkpoint, _t("studio.the_state_of", { name: ex.name }))) dlg.close(); } }, _t("studio.restore_the_state_of_this_video")) : null))))
                : h("p", { class: "hint" }, _t("studio.no_assembled_video_yet_assemble_button")));
        const dlg = modal(_t("studio.assembled_videos_of", { name: P.name }), body, { wide: true });
    }
    async function openCheckpoints() {
        if (!P.name) return showHome();
        const base = `/api/projects/${encodeURIComponent(P.name)}/checkpoints`;
        const body = h("div", {});
        const when = (t) => new Date(t * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
        const draw = async () => {
            let list = [];
            try { list = (await api(base)).checkpoints; } catch (e) { alert(e.message); }
            const nameIn = h("input", { placeholder: _t("studio.checkpoint_name_optional"), style: "flex:1" });
            fill(body, 
                h("div", { class: "tk-inline" }, nameIn, h("button", { class: "primary", onclick: async () => {
                    try { await saveIfDirty(); await post(base, { name: nameIn.value }); toast(_t("studio.checkpoint_created")); draw(); } catch (e) { alert(e.message); }
                } }, _t("studio.create_a_checkpoint"))),
                h("p", { class: "hint" }, _t("studio.a_checkpoint_records_the_plan_settings") +
                    _t("studio.restoring_puts_everything_back_as_it")),
                list.length ? h("div", { class: "studio-cps" }, list.map((cp) => h("div", { class: `studio-cp ${cp.kind}` },
                    h("div", { class: "studio-cp-main" },
                        h("b", {}, cp.name),
                        h("span", { class: "hint" }, ` ${when(cp.created)}`),
                        h("div", { class: "hint" }, _t("studio.branch_es_take_s_clip_s", { v0: cp.kind === "auto" ? _t("studio.automatic") + (cp.reason ? " — " + cp.reason : "") : _t("studio.manual"), branches: cp.branches, takes: cp.takes, clips: cp.clips }))),
                    h("button", { class: "small", onclick: async () => {
                        const label = await H3Dialog.prompt(_t("studio.checkpoint_name"), cp.name);
                        if (!label || !label.trim()) return;
                        try { await put(`${base}/${encodeURIComponent(cp.id)}`, { name: label.trim() }); draw(); } catch (e) { alert(e.message); }
                    } }, _t("studio.rename")),
                    h("button", { class: "small primary", onclick: async () => {
                        if (!await H3Dialog.confirm(_t("studio.restore_the_plan_settings_branches_and_2", { name: cp.name }) +
                            _t("studio.a_checkpoint_of_the_current_state"))) return;
                        try {
                            await saveIfDirty();
                            const res = await post(`${base}/${encodeURIComponent(cp.id)}/restore`, {});
                            applyProject(res.project);
                            toast(_t("studio.restored_previous_state", { name: cp.name, v1: res.saved_before.name }));
                            draw();
                        } catch (e) { alert(e.message); }
                    } }, _t("studio.restore")))))
                    : h("p", { class: "hint" }, _t("studio.no_checkpoint_yet")));
        };
        modal(_t("studio.checkpoints_of", { name: P.name }), body, { wide: true });
        draw();
    }

    // ------------------------------------------------------------------ settings storage
    function saveSettings() {
        clearTimeout(P.saveTimer);
        P.saveTimer = setTimeout(() => put(`/api/projects/${encodeURIComponent(P.name)}/settings`, P.settings)
            .catch((e) => toast(_t("studio.settings_not_saved", { message: e.message }))), 300);
    }
    async function refreshResources() {
        P.resources = await api(`/api/projects/${encodeURIComponent(P.name)}/resources`);
        return P.resources;
    }
    // Import files into the project's resources. The file is sent as it is read (no copy in memory), with a
    // progress window (file, %, MB, cancel) as soon as the transfer takes more than a moment.
    async function importFiles(kind, files) {
        const added = [];
        const total = files.reduce((n, f) => n + f.size, 0);
        let done = 0, cancelled = false, xhr = null, win = null;
        const bar = h("div", { class: "studio-progress-bar" }), label = h("div", { class: "hint" });
        const showProgress = () => {
            if (win) return;
            win = modal(_t("studio.importing"), h("div", { class: "studio-progress" }, label, h("div", { class: "studio-progress-track" }, bar),
                h("div", { class: "tk-inline", style: "justify-content:flex-end;margin-top:8px" },
                    h("button", { onclick: () => { cancelled = true; if (xhr) xhr.abort(); } }, _t("studio.cancel")))),
            { onClose: () => { cancelled = true; if (xhr) xhr.abort(); } });
        };
        const timer = setTimeout(showProgress, 400);
        const mb = (n) => (n / 1048576).toFixed(n < 10485760 ? 1 : 0).replace(".", H3I18n.decimal());
        try {
            for (const file of files) {
                if (cancelled) break;
                const res = await new Promise((resolve, reject) => {
                    xhr = new XMLHttpRequest();
                    xhr.open("POST", `/api/projects/${encodeURIComponent(P.name)}/resources?kind=${kind}&filename=${encodeURIComponent(file.name)}`);
                    xhr.setRequestHeader("X-Encore", "1");
                    xhr.upload.onprogress = (e) => {
                        const sent = done + (e.lengthComputable ? e.loaded : 0);
                        bar.style.width = `${total ? Math.min(100, (100 * sent) / total) : 100}%`;
                        label.textContent = _t("studio.importing_file", { file: file.name, v1: total ? Math.floor((100 * sent) / total) : 100, v2: mb(sent), v3: mb(total) });
                    };
                    xhr.onload = () => {
                        let data = null;
                        try { data = JSON.parse(xhr.responseText || "null"); } catch (_) { data = { error: xhr.responseText }; }
                        if (xhr.status >= 400 || (data && data.error)) reject(new Error((data && data.error) || `HTTP ${xhr.status}`));
                        else resolve(data);
                    };
                    xhr.onerror = () => reject(new Error(_t("studio.import_failed")));
                    xhr.onabort = () => reject(Object.assign(new Error(_t("studio.import_cancelled")), { code: "cancelled" }));
                    xhr.send(file);
                });
                added.push(res.path);
                done += file.size;
            }
        } finally {
            clearTimeout(timer);
            if (win) win.overlay.remove();
            await refreshResources();
        }
        return added;
    }
    const ACCEPT = { images: "image/*", voices: "audio/*", songs: "audio/*", videos: "video/*" };
    const KIND_LABEL = { images: _t("studio.pictures"), voices: _t("studio.voices"), songs: _t("studio.songs"), videos: _t("studio.videos") };
    // a player for a project video; when the browser cannot play it (AVI, ProRes, HEVC…), a light H.264 copy is made
    // by the server (ffmpeg), with its progress under the player, and played instead. ComfyUI always gets the original.
    function playableVideo(rel, cls) {
        const video = h("video", { controls: true, preload: "metadata", class: cls });
        const note = h("div", { class: "hint studio-preview-note", hidden: true });
        const wrap = h("div", { class: "studio-playable" }, video, note);
        const q = `/api/projects/${encodeURIComponent(P.name)}/resources/preview?path=${encodeURIComponent(rel)}`;
        let tried = false, seen = false;
        const play = (path) => { note.hidden = true; video.src = `${fileUrl(path)}?v=${Date.now()}`; };
        const say = (text, ...buttons) => { note.hidden = false; note.replaceChildren(h("span", {}, text), ...buttons); };
        const failed = (err) => say(err.code === "no_ffmpeg" ? err.message : _t("studio.preview_failed", { error: err.message }),
            " ", h("button", { class: "small", onclick: () => make() }, _t("studio.preview_retry")));
        async function follow() {
            for (;;) {
                if (wrap.isConnected) seen = true; else if (seen) return;      // the player was closed or drawn again
                let st;
                try { st = await api(q); } catch (err) { failed(err); return; }
                if (st.state === "done") { play(st.path); return; }
                if (st.state === "error") { failed({ message: st.error || "?" }); return; }
                if (st.state === "none") { say(_t("studio.preview_cancelled"), " ", h("button", { class: "small", onclick: () => make() }, _t("studio.preview_retry"))); return; }
                const bar = h("div", { class: "studio-progress-track" }, h("div", { class: "studio-progress-bar", style: `width:${Math.round(100 * st.progress)}%` }));
                say(_t("studio.preview_making", { v0: Math.round(100 * st.progress) }), " ",
                    h("button", { class: "small", onclick: () => api(q, { method: "DELETE" }).catch(() => {}) }, _t("studio.cancel")), bar);
                await new Promise((r) => setTimeout(r, 700));
            }
        }
        async function make() {
            say(_t("studio.preview_making", { v0: 0 }));
            try { await api(q, { method: "POST" }); } catch (err) { failed(err); return; }
            follow();
        }
        const unplayable = () => { if (tried) return; tried = true; make(); };
        video.addEventListener("error", unplayable);
        video.addEventListener("loadedmetadata", () => { if (!video.videoWidth) unplayable(); });     // sound only: the picture is not decoded
        api(q).then((st) => {
            if (st.state === "done") { tried = true; play(st.path); }
            else if (st.state === "running") { tried = true; follow(); }
            else video.src = fileUrl(rel);
        }).catch(() => { video.src = fileUrl(rel); });
        return { wrap, video };
    }
    function preview(kind, rel) {
        if (kind === "videos") return playableVideo(rel, "studio-res-video").wrap;
        return kind === "images" ? zoom(h("img", { src: fileUrl(rel), class: "tk-refimg", loading: "lazy" }), rel.split("/").pop())
            : h("audio", { controls: true, preload: "none", src: fileUrl(rel) });
    }

    // ------------------------------------------------------------------ resources dialog
    function openResources() {
        if (!P.name) return showHome();
        const body = h("div", {});
        const mb = (size) => _t("studio.mb_2", { v0: (size / 1e6).toFixed(1).replace(".", H3I18n.decimal()) });
        // delete a file: refused while the project uses it, a warning when checkpoints or takes still need it
        const remove = async (it) => {
            const base = `/api/projects/${encodeURIComponent(P.name)}/resources?path=${encodeURIComponent(it.path)}`;
            try {
                const use = await api(`/api/projects/${encodeURIComponent(P.name)}/resources/usage?path=${encodeURIComponent(it.path)}`);
                if (use.current.length) { await H3Dialog.alert(_t("resources.in_use", { file: it.name, v1: use.current.join("; ") })); return; }
                const why = [use.checkpoints.length ? _t("studio.used_by_checkpoints", { v0: use.checkpoints.join(", ") }) : null,
                    use.takes ? _t("studio.used_by_takes", { count: use.takes }) : null].filter(Boolean);
                const ok = await H3Dialog.confirm(why.length ? _t("studio.delete_resource_used", { file: it.name, v1: mb(it.size), v2: why.map((w) => "• " + w).join("\n") })
                    : _t("studio.delete_resource_confirm", { file: it.name, v1: mb(it.size) }));
                if (!ok) return;
                await api(base + (why.length ? "&confirm=1" : ""), { method: "DELETE" });
            } catch (e) { await H3Dialog.alert(e.message); }
            await refreshResources();
            draw();
        };
        const draw = () => {
            fill(body);
            const all = Object.values(P.resources).flat();
            body.append(h("p", { class: "hint" }, _t("studio.resources_total", { count: all.length, v1: mb(all.reduce((n, it) => n + (it.size || 0), 0)) })));
            for (const kind of ["images", "voices", "songs", "videos"]) {
                const items = P.resources[kind] || [];
                body.append(h("h3", {}, `${KIND_LABEL[kind]} (${items.length})`),
                    h("button", { onclick: async () => { const files = await pickFiles(ACCEPT[kind], true); if (files.length) { try { await importFiles(kind, files); } catch (e) { alert(e.message); } draw(); } } }, _t("studio.import")),
                    h("div", { class: kind === "images" || kind === "videos" ? "studio-grid" : "studio-list" }, items.map((it) => h("div", { class: "studio-res" },
                        preview(kind, it.path),
                        h("div", { class: "studio-res-foot" },
                            h("div", { class: "studio-res-name", title: it.path }, it.name, h("span", { class: "hint" }, mb(it.size))),
                            // outside the name, which is cut when long: always visible
                            h("button", { class: "small danger studio-res-del", title: _t("studio.delete_resource"), onclick: () => remove(it) }, "🗑"))))));
            }
            body.append(h("p", { class: "hint" }, _t("studio.imported_files_are_copied_into_the")));
        };
        draw();
        modal(_t("studio.resources_of_project", { name: P.name }), body, { wide: true });
    }

    // ------------------------------------------------------------------ references dialog
    // picture size: presets by ratio and megapixels; onChange(w, h) returns false to refuse
    // how H3 sizes the reference pictures: "max" (default) or "match" (the size of the video)
    function refSizePicker(value, onChange) {
        const box = h("div", { class: "tk-inline" });
        const draw = (current) => {
            fill(box, ...["max", "match"].map((v) => h("button", { class: `small ${current === v ? "on primary" : ""}`,
                onclick: async () => { if (v !== current && (await onChange(v)) !== false) draw(v); } }, v === "max" ? _t("studio.max_default") : "match")),
                h("span", { class: "hint" }, _t("studio.passed_to_the_h3_reference_encoder")));
        };
        draw(value);
        return box;
    }
    function sizePicker(width, height, onChange) {
        const all = presets();
        const box = h("div", {});
        let w0 = width, h0 = height;
        const draw = () => {
            const current = all.find((p) => p.w === w0 && p.h === h0);
            const wIn = h("input", { type: "number", step: 32, min: 64, value: w0, style: "width:90px" });
            const hIn = h("input", { type: "number", step: 32, min: 64, value: h0, style: "width:90px" });
            const set = async (w, hh) => {
                if (w % 32 || hh % 32 || w < 64 || hh < 64) { alert(_t("studio.the_size_must_be_a_multiple")); draw(); return; }
                if (w === w0 && hh === h0) return;
                if ((await onChange(w, hh)) !== false) { w0 = w; h0 = hh; }
                draw();
            };
            wIn.addEventListener("change", () => set(Number(wIn.value), h0));
            hIn.addEventListener("change", () => set(w0, Number(hIn.value)));
            const presetSel = h("select", { onchange: (e) => { if (e.target.value) { const [w, hh] = e.target.value.split("x").map(Number); set(w, hh); } } },
                h("option", { value: "", selected: !current || null }, current ? _t("studio.presets") : _t("studio.custom")),
                RATIOS.map(([label]) => h("optgroup", { label },
                    all.filter((p) => p.ratio === label).map((p) => h("option", { value: `${p.w}x${p.h}`, selected: (current && current === p) || null },
                        _t("studio.mp_2", { ratio: p.ratio, v1: fmtMp(p.mp), w: p.w, h: p.h }))))));
            fill(box, h("div", { class: "tk-inline" }, presetSel),
                h("div", { class: "tk-inline", style: "margin-top:4px" }, wIn, " × ", hIn, h("span", { class: "hint" }, _t("studio.mp_multiples_of_32", { w0, h0, v2: fmtMp(w0 * h0 / MPX) }))));
        };
        draw();
        return box;
    }

    // a branch's set: the files of its references and, for a music video, its song
    function branchById(id) { return P.branches.find((b) => b.id === id); }
    async function putBranch(id, changes) {
        const res = await put(`/api/projects/${encodeURIComponent(P.name)}/branches/${encodeURIComponent(id)}`, changes);
        P.branches = res.branches;
        if (window.H3Takes) window.H3Takes.recompute();
        return res.branch;
    }
    // remove a whole branch; its takes kept by a checkpoint stay on disk, the others are deleted
    async function deleteBranch(id) {
        const br = branchById(id);
        if (!br) return;
        const url = `/api/projects/${encodeURIComponent(P.name)}/branches/${encodeURIComponent(id)}`;
        try {
            await saveIfDirty();
            let res = await api(url, { method: "DELETE" });
            if (res.needs_confirm) {
                const videos = res.delete_videos ? _t("studio.its_assembled_video_s_will_be", { delete_videos: res.delete_videos }) : "";
                const msg = res.keep
                    ? _t("studio.take_s_of_are_in_no", { delete: res.delete, name: br.name }) +
                      _t("studio.the_other_s_stay_in_checkpoint", { keep: res.keep, checkpoints: res.checkpoints, videos })
                    : _t("studio.is_in_no_checkpoint_its_take", { name: br.name, delete: res.delete, videos });
                if (!await H3Dialog.confirm(msg)) return;
                res = await api(url + "?confirm=1", { method: "DELETE" });
            }
            applyProject(res.project);
            toast(res.checkpoints ? _t("studio.removed_stays_in_checkpoint_s", { name: br.name, checkpoints: res.checkpoints }) : _t("studio.deleted", { name: br.name }));
        } catch (e) { alert(e.message); }
    }
    async function renameBranch(id) {
        const br = branchById(id);
        const name = await H3Dialog.prompt(_t("studio.branch_name"), br ? br.name : "");
        if (!name || !name.trim()) return;
        try { await putBranch(id, { name: name.trim() }); } catch (e) { alert(e.message); }
    }
    function openBranch(id, { first = false } = {}) {
        return new Promise((resolve) => {
            const br = branchById(id);
            if (!br) { resolve(); return; }
            const free = H3.mode(plan()) === "free";
            const body = h("div", { class: "tk-refs" });
            const draw = () => {
                const branch = branchById(id);
                fill(body);
                if (first) body.append(h("p", { class: "hint" }, _t("studio.choose_the_size_and_files_of")));
                body.append(h("div", { class: "tk-ref" }, h("div", { class: "tk-refimg empty" }, "▭"),
                    h("div", { class: "tk-refbody" }, h("b", {}, _t("studio.picture_size")),
                        sizePicker(Number(branch.width), Number(branch.height), async (w, hh) => {
                            try {
                                if (window.H3Takes && !(await window.H3Takes.changeSize(id, w, hh))) return false;
                                await putBranch(id, { width: w, height: hh });
                            } catch (e) { alert(e.message); return false; }
                            return true;
                        }),
                        h("b", { style: "display:block;margin-top:10px" }, _t("studio.reference_size")),
                        refSizePicker(branch.ref_image_size || "max", async (value) => {
                            try {
                                if (window.H3Takes && !(await window.H3Takes.changeRefSize(id, value))) return false;
                                await putBranch(id, { ref_image_size: value });
                            } catch (e) { alert(e.message); return false; }
                            return true;
                        }))));
                if (!free) {
                    const player = h("audio", { controls: true, style: "width:100%;margin-top:4px", src: branch.song ? fileUrl(branch.song) : null });
                    const setSong = async (path) => {
                        try {
                            if ((branch.song || "") !== (path || "") && window.H3Takes && !(await window.H3Takes.changeSong(id, path || null))) { draw(); return; }
                            await putBranch(id, { song: path || "" });
                        } catch (e) { alert(e.message); }
                        draw();
                    };
                    const sel = h("select", { onchange: (e) => setSong(e.target.value) },
                        h("option", { value: "" }, _t("studio.none_3")), (P.resources.songs || []).map((it) => h("option", { value: it.path, selected: it.path === branch.song || null }, it.name)));
                    const up = h("button", { onclick: async () => {
                        const [file] = await pickFiles("audio/*");
                        if (!file) return;
                        try { const [path] = await importFiles("songs", [file]); await setSong(path); } catch (e) { alert(e.message); draw(); }
                    } }, _t("studio.import"));
                    body.append(h("div", { class: "tk-ref" }, h("div", { class: "tk-refimg empty" }, "♪"),
                        h("div", { class: "tk-refbody" }, h("b", {}, _t("studio.song")), h("div", { class: "tk-inline" }, sel, up), player)));
                }
                const names = Object.keys(plan().refs || {}).filter((n) => n !== (plan().start_video || plan().edit_video || {}).ref);
                if (!names.length) body.append(h("p", { class: "hint" }, _t("studio.the_plan_declares_no_reference_plan")));
                for (const name of names) {
                    const r = { ...((branch.refs || {})[name] || {}) };
                    const kinds = H3.referenceKinds(plan(), name);
                    // a reference changed: the takes of this branch made with the old file are invalidated, after confirmation
                    const setRef = async (kind, value) => {
                        try {
                            if ((r[kind] || null) !== (value || null) && window.H3Takes && !(await window.H3Takes.changeReference(id, name, kind, value))) { draw(); return; }
                            const refs = JSON.parse(JSON.stringify(branch.refs || {}));
                            refs[name] = { ...(refs[name] || {}), [kind]: value || null };
                            await putBranch(id, { refs });
                        } catch (e) { alert(e.message); }
                        draw();
                    };
                    const pick = (kind, label, list) => {
                        const folder = { image: "images", voice: "voices", video: "videos" }[kind];
                        const sel = h("select", { onchange: (e) => setRef(kind, e.target.value || null) },
                            h("option", { value: "" }, label),
                            list.map((it) => h("option", { value: it.path, selected: it.path === r[kind] || null }, it.name)));
                        const up = h("button", { onclick: async () => {
                            const [file] = await pickFiles(ACCEPT[folder]);
                            if (!file) return;
                            try { const [path] = await importFiles(folder, [file]); await setRef(kind, path); } catch (e) { alert(e.message); draw(); }
                        } }, _t("studio.import"));
                        return h("div", { class: "tk-inline" }, sel, up);
                    };
                    if (kinds.includes("video")) continue;    // the start video is chosen in the plan settings, for every branch
                    body.append(h("div", { class: "tk-ref" },
                        r.image ? zoom(h("img", { src: fileUrl(r.image), class: "tk-refimg" }), name) : h("div", { class: "tk-refimg empty" }, _t("studio.no_picture_2")),
                        h("div", { class: "tk-refbody" },
                            h("div", {}, h("b", {}, name), h("span", { class: "hint" }, `  ${plan().refs[name] || ""}`)),
                            h("div", { class: "hint" }, kinds.length ? _t("studio.the_prompts_use", { v0: kinds.map((k) => _t("check." + k)).join(" + ") }) : _t("studio.not_cited_in_the_prompts")),
                            h("label", {}, _t("studio.picture")), pick("image", _t("studio.no_picture"), P.resources.images || []),
                            free ? [h("label", {}, _t("studio.voice")), pick("voice", _t("studio.no_voice_h3_chooses"), P.resources.voices || []),
                                r.voice ? h("audio", { controls: true, src: fileUrl(r.voice), style: "width:100%" }) : null] : null)));
                }
            };
            draw();
            modal(_t("studio.references_of", { name: br.name }), body, { onClose: () => { if (window.H3Takes) window.H3Takes.render(); resolve(); } });
        });
    }

    // ------------------------------------------------------------------ generation manager (the Studio's queue)
    // One job at a time in ComfyUI; the others wait here, frozen as they were launched. A group is a job and the
    // jobs that continue it: its order never changes, the whole group moves.
    const fmtDur = (sec) => {
        sec = Math.max(0, Math.round(sec));
        if (sec < 60) return `${sec} s`;
        const m = Math.floor(sec / 60), r = sec % 60;
        return m < 60 ? `${m} min${r ? " " + String(r).padStart(2, "0") : ""}` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
    };
    let queueTimer = null;
    const seenErrors = new Set();
    async function refreshQueueBadge() {
        const btn = $("studioQueueBtn");
        if (!btn) return;
        try {
            const q = await api("/api/queue");
            const run = q.sent.find((j) => j.status === "running") || q.sent[0];
            const newErrors = (q.errors || []).filter((e) => !seenErrors.has(e.id));
            const more = q.waiting ? _t("studio.waiting_5", { waiting: q.waiting }) : "";
            let text, cls, short, pct = 0;
            if (run) {
                const what = run.kind === "assemble" ? _t("studio.assembly_1", { clips: run.clips }) : `clip ${run.clip}`;
                const prog = run.progress ? ` · ${run.progress.value}/${run.progress.max}` : "";
                pct = run.progress ? Math.round(100 * run.progress.value / Math.max(1, run.progress.max)) : 0;
                text = run.status === "running"
                    ? `▶ ${run.step || _t("studio.preparing")} · ${run.project} · ${what}${prog}${run.eta != null ? _t("studio.left", { time: fmtDur(run.eta) }) : ""}${more}`
                    : _t("studio.sent", { project: run.project, what, more }) + (run.comfy_ahead ? _t("studio.comfy_ahead", { n: run.comfy_ahead }) : "");
                short = run.progress ? `▶ ${run.progress.value}/${run.progress.max}` : "▶";
                cls = "running";
                if (q.paused) { text = _t("studio.pause_requested", { v0: text.slice(2) }); cls = "paused"; }
            } else if (q.paused && q.waiting) {
                text = _t("studio.queue_paused_waiting", { waiting: q.waiting }); cls = "paused"; short = "⏸";
            } else if (q.waiting) {
                text = _t("studio.waiting_4", { waiting: q.waiting }); cls = "running"; short = "⏳";
            } else {
                text = q.paused ? _t("studio.queue_paused_empty") : _t("studio.empty_queue"); cls = q.paused ? "paused" : "idle"; short = "";
            }
            if (newErrors.length) { text = _t("studio.error_s", { length: newErrors.length, text }); cls = "error"; }
            if (q.comfy) showComfyState(q.comfy);
            btn.className = `studio-queue-state ${cls}`;
            btn.querySelector(".studio-qs-text").textContent = text;
            btn.querySelector(".studio-qs-bar i").style.width = `${pct}%`;
            btn.querySelector(".studio-qs-bar").style.visibility = run && run.status === "running" ? "visible" : "hidden";
            const plain = document.title.replace(/^[▶⏸⏳✖][^·]*· /u, "");      // the editor keeps its own title
            document.title = short ? `${short} · ${plain}` : plain;
            return q;
        } catch (_) { return null; }
    }
    setInterval(refreshQueueBadge, 1500);

    // ------------------------------------------------------------------ ComfyUI connection indicator
    let comfyState = null, lastEpoch = null;
    const fmtSince = (s) => (s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}`);
    function showComfyState(c) {
        comfyState = c;
        const btn = $("studioComfyBtn");
        if (!btn) return;
        const cls = c.ok === true ? "ok" : c.ok === false ? (c.for_s < 10 && c.epoch > 0 ? "retry" : "down") : "unknown";
        btn.className = `studio-comfy-state ${cls}`;
        btn.querySelector(".studio-comfy-text").textContent = c.ok === true ? _t("studio.comfyui_connected")
            : cls === "retry" ? _t("studio.comfyui_reconnecting") : c.ok === false ? _t("studio.comfyui_unreachable") : _t("studio.comfyui");
        btn.title = c.ok ? _t("studio.comfyui_at_connected_for", { v0: c.version || "", url: c.url, v2: fmtSince(c.for_s) })
            : _t("studio.comfyui_has_not_answered_at_for", { v0: c.url || "?", v1: fmtSince(c.for_s), v2: c.error ? " (" + c.error + ")" : "" });
        if (c.ok && lastEpoch !== null && c.epoch !== lastEpoch) {
            P.info = null;                              // restarted: node and model lists may have changed
            if (window.H3Takes) window.H3Takes.recompute();
            onComfyBack();
        }
        if (c.ok) lastEpoch = c.epoch;
    }
    function openComfyPanel() {
        const body = h("div", { class: "studio-upscale" });
        const draw = () => {
            const c = comfyState || {};
            fill(body, ...[
                h("div", { class: `studio-comfy-big ${c.ok ? "ok" : "down"}` }, h("i", { class: "studio-comfy-dot" }),
                    c.ok ? _t("studio.connected_for", { v0: fmtSince(c.for_s || 0) }) : _t("studio.unreachable_for", { v0: fmtSince(c.for_s || 0) })),
                h("div", { class: "tk-row" }, h("label", {}, _t("studio.address")), h("span", {}, c.url || "—"), h("span")),
                h("div", { class: "tk-row" }, h("label", {}, _t("studio.version")), h("span", {}, c.version || "—"), h("span")),
                c.ok ? null : h("div", { class: "tk-row" }, h("label", {}, _t("studio.error")), h("span", { class: "hint" }, c.error || "—"), h("span")),
                c.ok ? null : h("p", { class: "hint" }, _t("studio.check_that_comfyui_is_running_and")
                    + _t("studio.started_generations_wait_in_the_queue")),
                h("div", { class: "studio-dlg-actions" },
                    h("button", { onclick: async () => { try { showComfyState(await post("/api/comfy/check", {})); } catch (_) { /* ignore */ } draw(); } }, _t("studio.try_again")))].filter(Boolean));
        };
        draw();
        const timer = setInterval(draw, 1500);
        modal(_t("studio.connection_to_comfyui_2"), body, { onClose: () => clearInterval(timer) });
    }
    function jobTitle(j) {
        const len = j.frames ? (j.frames / 24 < 60 ? `${(j.frames / 24).toFixed(1).replace(".", H3I18n.decimal())} s` : `${Math.floor(j.frames / 24 / 60)} min ${String(Math.round(j.frames / 24 % 60)).padStart(2, "0")}`) : "";
        const what = (j.kind === "assemble" ? _t("studio.assembly_of_clips_1_to", { clips: j.clips }) + (j.with_invalid ? " ⚠" : "") : `clip ${j.clip}${j.parentToken ? _t("studio.next") : ""}`) + (len ? ` · ${len}` : "");
        return [h("b", {}, j.project), " · ", h("i", { class: "tk-branch-dot", style: `background:${j.branch_color || "#888"}` }), ` ${j.branch_name || j.branch || ""} · ${what}`,
            j.kind === "assemble" ? "" : _t("studio.seed_2", { seed: j.seed }), j.upscale ? h("span", { class: "tk-up-badge inline", title: _t("studio.with_latent_upscale") }, "⇧") : "",
            j.loras && j.loras.length ? h("span", { class: "tk-lora-badge", style: "margin-left:4px", title: _t("studio.extra_lora_2") + fmtLoras(j.loras) }, _t("studio.lora_2") + fmtLoras(j.loras)) : ""];
    }
    const openLots = new Set();
    function openQueue() {
        let dragging = null, closed = false;
        const body = h("div", { class: "studio-queue" });
        const act = async (path, payload, confirmText) => {
            if (confirmText && !await H3Dialog.confirm(confirmText)) return;
            try { draw(await api(`/api/queue/${path}`, { method: "POST", body: JSON.stringify(payload || {}) })); }
            catch (e) { alert(e.message); }
            if (window.H3Takes) window.H3Takes.refresh && window.H3Takes.refresh();
        };
        const cancelJob = (j) => act("cancel", { ids: [j.id] }, j.dependents
            ? _t("studio.cancel_this_job_and_the_job", { dependents: j.dependents }) : null);
        const state = (j, q) => {
            if (j.dispatched) {
                if (j.status === "running") {
                    const p = j.progress ? ` ${j.progress.value}/${j.progress.max}` : "";
                    return `▶ ${j.step || _t("studio.preparing")}${p}` + (j.eta != null ? _t("studio.left", { time: fmtDur(j.eta) }) : "");
                }
                if (j.status === "harvest") return _t("studio.collecting");
                return j.comfy_ahead ? _t("studio.sent_waits_behind", { n: j.comfy_ahead }) : _t("studio.sent_to_comfyui_waiting_for_its");
            }
            if (j.suspended) return _t("studio.suspended");
            if (q.paused) return _t("studio.queue_paused");
            if (j.start_in != null && j.at_least) return _t("studio.start_at_least", { v0: fmtDur(j.start_in) });
            return j.start_in == null ? _t("studio.waiting") : j.start_in < 5 ? _t("studio.starting_soon") : _t("studio.start_3", { v0: fmtDur(j.start_in) });
        };
        const draw = (q) => {
            if (!q || dragging) return;
            const sent = q.sent.map((j) => h("div", { class: `studio-q-job ${j.status}` },
                h("div", { class: "studio-q-line" }, ...jobTitle(j), h("span", { style: "flex:1" }),
                    h("span", { class: "hint" }, state(j, q)),
                    j.status !== "harvest" ? h("button", { class: "small danger", onclick: () => cancelJob(j) }, _t("studio.cancel_2")) : null),
                j.status === "running" && j.progress ? h("div", { class: "tk-progress" }, h("i", { style: `width:${Math.round(100 * j.progress.value / Math.max(1, j.progress.max))}%` })) : null));
            const groups = q.groups.map((g, n) => {
                const box = h("div", { class: `studio-q-group${g.suspended ? " suspended" : ""}`, "data-group": g.id },
                    h("div", { class: "studio-q-ghead" },
                        h("span", { class: "studio-q-handle", title: _t("studio.drag_to_move_the_whole_group") }, "≡"),
                        g.label ? h("span", { class: "studio-q-lot" }, g.label, h("span", { class: "hint" }, _t("studio.batch_jobs_waiting", { length: g.jobs.length })))
                            : h("span", { class: "hint" }, g.jobs.length > 1 ? _t("studio.group_of_fixed_order_each_job", { length: g.jobs.length }) : ""),
                        h("span", { style: "flex:1" }),
                        h("button", { class: "small", title: _t("studio.to_the_top_of_the_queue"), disabled: n === 0 || null, onclick: () => act("move", { group: g.id, before: q.groups[0].id }) }, "⤒"),
                        h("button", { class: "small", title: _t("studio.move_up"), disabled: n === 0 || null, onclick: () => act("move", { group: g.id, before: q.groups[n - 1].id }) }, "↑"),
                        h("button", { class: "small", title: _t("studio.move_down"), disabled: n === q.groups.length - 1 || null, onclick: () => act("move", { group: g.id, before: q.groups[n + 2] ? q.groups[n + 2].id : null }) }, "↓"),
                        h("button", { class: "small", title: _t("studio.to_the_end_of_the_queue"), disabled: n === q.groups.length - 1 || null, onclick: () => act("move", { group: g.id, before: null }) }, "⤓"),
                        h("button", { class: "small", onclick: () => act("suspend", { group: g.id, suspended: !g.suspended }) }, g.suspended ? _t("studio.resume_2") : _t("studio.suspend")),
                        g.jobs.length > 1 ? h("button", { class: "small danger", onclick: () => act("cancel", { ids: g.jobs.map((j) => j.id) }, _t("studio.cancel_the_jobs_of_this_group", { length: g.jobs.length })) }, _t("studio.cancel_the_group")) : null),
                    ...(() => {
                        const lines = g.jobs.map((j) => h("div", { class: "studio-q-line" }, ...jobTitle(j), h("span", { style: "flex:1" }),
                            h("span", { class: "hint" }, j.kind === "assemble" && j.waiting_for ? _t("studio.waits_for", { what: j.waiting_for }) : state(j, q)),
                            h("button", { class: "small danger", title: _t("studio.also_cancels_what_depends_on_it"),
                                onclick: () => cancelJob(j) }, _t("studio.cancel_2"))));
                        if (!g.label || lines.length <= 5) return lines;
                        const key = `lot:${g.id}`;
                        const det = h("details", { open: openLots.has(key) || null, ontoggle: (e) => { if (e.target.open) openLots.add(key); else openLots.delete(key); } },
                            h("summary", { class: "hint" }, _t("studio.see_the_jobs", { length: lines.length })), ...lines);
                        return [det];
                    })());
                // vertical drag only, stopped at the top and bottom of the list; the other groups make room live
                box.addEventListener("pointerdown", (e) => {
                    if (e.button !== 0 || e.target.closest("button")) return;
                    e.preventDefault();
                    const list = box.parentElement, boxes = [...list.children];
                    const from = boxes.indexOf(box), startY = e.clientY;
                    const rects = boxes.map((el) => el.getBoundingClientRect());
                    const listRect = list.getBoundingClientRect();
                    const gap = boxes.length > 1 ? rects[1].top - rects[0].bottom : 6;
                    const step = rects[from].height + gap;
                    let to = from, moved = false;
                    dragging = g.id;
                    box.setPointerCapture(e.pointerId);
                    const move = (ev) => {
                        let dy = ev.clientY - startY;
                        dy = Math.max(listRect.top - rects[from].top, Math.min(listRect.bottom - rects[from].bottom, dy));
                        if (Math.abs(dy) > 3) moved = true;
                        box.style.transform = `translateY(${dy}px)`;
                        box.classList.add("dragged");
                        const centre = (rects[from].top + rects[from].bottom) / 2 + dy;
                        to = from;
                        rects.forEach((r, k) => {
                            const mid = (r.top + r.bottom) / 2;
                            if (k < from && centre < mid) to = Math.min(to, k);
                            if (k > from && centre > mid) to = Math.max(to, k);
                        });
                        boxes.forEach((el, k) => {
                            if (k === from) return;
                            el.style.transform = k >= Math.min(from, to) && k <= Math.max(from, to) ? `translateY(${k < from ? step : -step}px)` : "";
                        });
                    };
                    const up = () => {
                        box.removeEventListener("pointermove", move);
                        box.removeEventListener("pointerup", up);
                        box.removeEventListener("pointercancel", up);
                        boxes.forEach((el) => { el.style.transform = ""; });
                        box.classList.remove("dragged");
                        dragging = null;
                        if (!moved || to === from) return;
                        const others = q.groups.filter((x) => x.id !== g.id);
                        act("move", { group: g.id, before: others[to] ? others[to].id : null });
                    };
                    box.addEventListener("pointermove", move);
                    box.addEventListener("pointerup", up);
                    box.addEventListener("pointercancel", up);
                });
                return box;
            });
            fill(body, 
                h("div", { class: "studio-q-bar" },
                    h("b", {}, q.paused ? _t("studio.queue_paused_2") : _t("studio.queue_active")),
                    h("span", { class: "hint" }, _t("studio.running_waiting_one_job_at_a", { length: q.sent.length, waiting: q.waiting })),
                    h("span", { style: "flex:1" }),
                    q.paused ? h("button", { class: "primary", onclick: () => act("resume") }, _t("studio.resume")) : null,
                    q.paused ? null : h("button", { title: _t("studio.the_running_job_finishes_nothing_else"), onclick: () => act("pause", { mode: "after" }) }, _t("studio.pause_after_the_running_job")),
                    h("button", { class: "danger", title: _t("studio.interrupts_the_running_job_it_goes"),
                        disabled: !q.sent.some((j) => j.status !== "harvest") || null,
                        onclick: () => act("pause", { mode: "now" }, _t("studio.interrupt_the_running_job_it_goes")) }, _t("studio.pause_now"))),
                h("h3", {}, _t("studio.running")),
                sent.length ? h("div", {}, ...sent) : h("p", { class: "hint" }, _t("studio.nothing_running")),
                h("h3", {}, _t("studio.waiting_2")),
                groups.length ? h("div", { class: "studio-q-groups" }, ...groups) : h("p", { class: "hint" }, _t("studio.empty_queue_2")),
                h("p", { class: "hint" }, _t("studio.each_job_goes_as_it_was")
                    + _t("studio.drag_a_group_or_use_to")));
        };
        const tick = async () => {
            if (closed) return;
            const q = await refreshQueueBadge();
            if (q) for (const e of q.errors || []) seenErrors.add(e.id);     // seen: the indicator stops showing them
            draw(q);
            queueTimer = setTimeout(tick, 1000);
        };
        modal(_t("studio.generation_queue"), body, { wide: true, onClose: () => { closed = true; clearTimeout(queueTimer); } });
        tick();
    }

    // ------------------------------------------------------------------ latent upscale of a branch
    // first pass at a smaller size, latent upscale, second pass at the branch size (a generation setting:
    // changing it never invalidates a take; each take records whether it was made with it)
    const UPSCALERS = [["lbh3d", "LBH 3D (MinimaxH3LatentUpscaler3D)", "MinimaxH3LatentUpscaler3D"],
        ["lbh2d", "LBH 2D (MinimaxH3LatentUpscalerNode2D)", "MinimaxH3LatentUpscalerNode2D"],
        ["builtin", "ComfyUI (MiniMax H3 Latent Upscale With Model)", "LatentUpscaleModelLoader"]];
    const UP_DEFAULT = { enabled: false, start_mp: 0.2, pass1_mode: "split", pass1_steps: 4, pass1_sigmas: "0.9231, 0.8780, 0.8000, 0.6316",
        pass2_mode: "manual", pass2_sigmas: "0.9035, 0.8000, 0.6316, 0.3158, 0", upscaler: "lbh3d", model: "", sharpness: 1,
        pass2_loras: null, pass2_sampler: "" };
    function parseSigmas(text) {
        const v = String(text || "").replace(/;/g, ",").split(",").map((x) => x.trim()).filter(Boolean).map(Number);
        if (v.length < 2 || v.some((x) => !Number.isFinite(x)) || v.some((x, i) => i && x >= v[i - 1]) || v[v.length - 1] < 0) return null;
        return v;
    }
    function startSize(mp, w, hh) {
        const r = w / hh, px = mp * 1024 * 1024, r32 = (x) => Math.max(64, Math.round(x / 32) * 32);
        return [r32(Math.sqrt(px * r)), r32(Math.sqrt(px / r))];
    }
    // the same checks as the server (engine.upscale_plan): a summary, or the reason it cannot run
    function upscaleSummary(up, w, hh, steps) {
        if (!up.model) return { error: _t("studio.choose_the_upscale_model_file") };
        const [w0, h0] = startSize(up.start_mp || 0.2, w, hh);
        if (w0 >= w || h0 >= hh) return { error: _t("studio.the_start_size_is_not_smaller", { w0, h0, w, hh }) };
        const factor = (w / w0 + hh / h0) / 2;
        if (up.upscaler !== "builtin" && factor > 4) return { error: _t("studio.factor_too_large_4_at_most", { v0: factor.toFixed(2) }) };
        let p1, p2;
        if (up.pass1_mode === "manual") {
            const v = parseSigmas(up.pass1_sigmas);
            if (!v) return { error: _t("studio.pass_1_invalid_list_of_noise") };
            p1 = v.length - 1;
        } else {
            p1 = Number(up.pass1_steps);
            if (!(p1 >= 1 && p1 < steps)) return { error: _t("studio.pass_1_must_have_1_to", { v0: steps - 1, steps }) };
        }
        if (up.pass2_mode === "rest") {
            if (up.pass1_mode === "manual") return { error: _t("studio.rest_of_the_schedule_in_pass") };
            p2 = steps - p1;
        } else {
            const v = parseSigmas(up.pass2_sigmas);
            if (!v) return { error: _t("studio.pass_2_invalid_list_of_noise") };
            p2 = v.length - 1;
        }
        const label = { lbh3d: "LBH 3D", lbh2d: "LBH 2D", builtin: "ComfyUI" }[up.upscaler];
        const warn = up.upscaler !== "builtin" && factor < 1.5 ? _t("studio.factor_below_1_5_the_range") : "";
        return { text: _t("studio.mp_step_s_step_s", { v0: fmtMp(Number(up.start_mp)), w0, h0, p1, v4: factor.toFixed(2).replace(".", H3I18n.decimal()), label, w, hh, p2, warn }) };
    }
    // the form of the upscale settings (branch, clip or take): edits up in place, calls save after each change.
    // size: the end size the summary is computed for; enabled: show the « enabled » row; take: the form of the ▾
    // dialog (settings for one take: no branch hints).
    function upscaleEditor(up, size, save, { enabled = false, take = false } = {}) {
        const steps = Number(P.settings.steps) || 8;
        const body = h("div", { class: "studio-upscale" });
        const set = (k, v, redraw = true) => { up[k] = v; save(); if (redraw) draw(); };
        const row = (label, input, hint) => h("div", { class: "tk-row" }, h("label", {}, label), input, hint ? h("span", { class: "hint" }, hint) : h("span"));
        const select = (value, options, onchange) => h("select", { onchange: (e) => onchange(e.target.value) },
            options.map(([v, l, dis]) => h("option", { value: v, selected: String(v) === String(value) || null, disabled: dis || null }, l)));
        const draw = () => {
            const [w, hh] = size;
            const installed = (cls) => !P.info || !!P.info[cls];
            const node = UPSCALERS.find((u) => u[0] === up.upscaler) || UPSCALERS[0];
            const modelNode = up.upscaler === "builtin" ? ["LatentUpscaleModelLoader", "model_name"] : [node[2], "model_name"];
            const models = P.info ? (comboValues(P.info, ...modelNode) || []) : [];
            const modelInput = models.length
                ? select(up.model, [["", _t("studio.choose_a_file")], ...[...new Set([...(up.model ? [up.model] : []), ...models])].map((m) => [m, m])], (v) => set("model", v))
                : h("input", { value: up.model, placeholder: _t("studio.file_name"), onchange: (e) => set("model", e.target.value.trim()) });
            const mps = [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0].filter((mp) => { const [a, b] = startSize(mp, w, hh); return a < w && b < hh; });
            if (!mps.includes(Number(up.start_mp))) mps.unshift(Number(up.start_mp));
            const samplers = P.info ? (comboValues(P.info, "KSamplerSelect", "sampler_name") || []) : [];
            const sum = upscaleSummary(up, w, hh, steps);
            const loraBox = h("div", {});
            if (Array.isArray(up.pass2_loras)) {
                const values = P.info ? (comboValues(P.info, ...COMBOS.lora_name) || []) : [];
                loraBox.append(...up.pass2_loras.map((l, i) => {
                    const list = [...new Set([...(l.name ? [l.name] : []), ...values])];
                    return h("div", { class: `studio-lora${l.enabled ? "" : " off"}` },
                        h("input", { type: "checkbox", title: _t("studio.active"), checked: l.enabled || null, onchange: (e) => { l.enabled = e.target.checked; save(); draw(); } }),
                        list.length ? select(l.name, [["", _t("studio.choose_a_file")], ...list.map((v) => [v, v])], (v) => { l.name = v; save(); })
                            : h("input", { value: l.name, placeholder: _t("studio.file_name"), onchange: (e) => { l.name = e.target.value.trim(); save(); } }),
                        h("label", { class: "hint" }, _t("studio.strength")),
                        h("input", { type: "number", step: 0.05, value: l.strength, style: "width:70px", onchange: (e) => { l.strength = Number(e.target.value); save(); } }),
                        h("button", { class: "small danger", onclick: () => { up.pass2_loras.splice(i, 1); save(); draw(); } }, "✕"));
                }), h("button", { class: "small", onclick: () => { up.pass2_loras.push({ name: "", strength: 1.0, enabled: true }); save(); draw(); } }, _t("studio.add_a_lora")));
            }
            fill(body, ...[
                take ? null : h("p", { class: "hint" }, _t("studio.first_pass_at_a_reduced_size")
                    + _t("studio.changing_these_settings_invalidates_no_take")),
                !enabled ? null : row(_t("studio.enabled"), h("label", { class: "tk-check" }, h("input", { type: "checkbox", checked: up.enabled || null, onchange: (e) => set("enabled", e.target.checked) }), take ? _t("studio.for_this_take") : _t("studio.for_the_generations_of_this_branch")),
                    take ? null : _t("studio.off_by_default_quality_may_drop")),
                h("div", { class: `studio-up-sum ${sum.error ? "err" : ""}` }, sum.error ? `⚠ ${sum.error}` : sum.text),
                h("h3", {}, _t("studio.sizes")),
                row(_t("studio.start"), select(up.start_mp, mps.map((mp) => { const [a, b] = startSize(mp, w, hh); return [mp, _t("studio.mp", { v0: fmtMp(mp), a, b })]; }), (v) => set("start_mp", Number(v))),
                    _t("studio.end_branch_size", { w, hh })),
                h("h3", {}, _t("studio.upscaler")),
                row(_t("studio.node"), select(up.upscaler, UPSCALERS.map(([v, l, cls]) => [v, l + (installed(cls) ? "" : _t("studio.not_installed")), !installed(cls) && v !== up.upscaler]), (v) => { up.model = ""; set("upscaler", v); }),
                    up.upscaler === "builtin" ? _t("studio.comfyui_nodes") : _t("studio.lbh_123_ai_comfyui_minimax_h3")),
                row(_t("studio.model"), modelInput, up.upscaler === "lbh3d" ? downloadHint("upscale_model", models) : _t("studio.in_comfyui_s_models_latent_upscale")),
                up.upscaler === "lbh2d" ? row(_t("studio.sharpness"), h("input", { type: "number", min: 1, max: 6, value: up.sharpness, style: "width:70px", onchange: (e) => set("sharpness", Math.max(1, Math.min(6, Math.trunc(Number(e.target.value)) || 1))) }),
                    _t("studio.1_most_faithful_6_sharpest")) : null,
                h("h3", {}, _t("studio.pass_1_start_size")),
                row(_t("studio.steps"), select(up.pass1_mode, [["split", _t("studio.start_of_the_normal_schedule")], ["manual", _t("studio.manual_list")]], (v) => set("pass1_mode", v)),
                    up.pass1_mode === "split" ? _t("studio.settings_schedule_steps_with_the_sigmashift", { scheduler: P.settings.scheduler, steps }) : _t("studio.decreasing_noise_levels_without_the_sigmashift")),
                up.pass1_mode === "split"
                    ? row(_t("studio.count"), h("input", { type: "number", min: 1, max: steps - 1, value: up.pass1_steps, style: "width:70px", onchange: (e) => set("pass1_steps", Math.trunc(Number(e.target.value)) || 1) }), _t("studio.first_steps_out_of", { steps }))
                    : row(_t("studio.levels"), h("input", { value: up.pass1_sigmas, style: "width:100%", onchange: (e) => set("pass1_sigmas", e.target.value) }), _t("studio.for_example_0_9231_0_8780")),
                h("h3", {}, _t("studio.pass_2_branch_size")),
                row(_t("studio.steps"), select(up.pass2_mode, [["manual", _t("studio.manual_list")], ["rest", _t("studio.rest_of_the_normal_schedule")]], (v) => set("pass2_mode", v)),
                    up.pass2_mode === "manual" ? _t("studio.re_noises_at_the_first_level") : _t("studio.the_steps_left_after_pass_1")),
                up.pass2_mode === "manual" ? row(_t("studio.levels"), h("input", { value: up.pass2_sigmas, style: "width:100%", onchange: (e) => set("pass2_sigmas", e.target.value) }),
                    _t("studio.4_steps_0_9035_0_8000")) : null,
                row(_t("studio.sampler"), select(up.pass2_sampler, [["", _t("studio.like_pass_1", { sampler_name: P.settings.sampler_name })], ...samplers.map((v) => [v, v])], (v) => set("pass2_sampler", v))),
                row(_t("studio.lora"), h("label", { class: "tk-check" }, h("input", { type: "checkbox", checked: Array.isArray(up.pass2_loras) || null,
                    onchange: (e) => set("pass2_loras", e.target.checked ? JSON.parse(JSON.stringify(P.settings.loras || [])) : null) }), _t("studio.different_lora_in_pass_2")),
                    Array.isArray(up.pass2_loras) ? _t("studio.replace_those_of_the_settings_for") : _t("studio.like_pass_1_project_settings")),
                loraBox,
                h("p", { class: "hint" }, _t("studio.the_seam_with_the_previous_clip")),
            ].filter(Boolean));
        };
        draw();
        return body;
    }

    async function openUpscale(id) {
        const br = branchById(id);
        if (!br) return;
        if (!P.info) { try { P.info = await api("/api/comfy/object_info"); } catch (e) { /* lists unknown: free text */ } }
        const up = Object.assign({}, UP_DEFAULT, JSON.parse(JSON.stringify(br.upscale || {})));
        let timer = null;
        const save = () => { clearTimeout(timer); timer = setTimeout(() => putBranch(id, { upscale: up }).catch((e) => toast(_t("studio.upscale_not_saved", { message: e.message }))), 250); };
        const body = upscaleEditor(up, [Number(br.width), Number(br.height)], save, { enabled: true });
        modal(_t("studio.latent_upscale_of", { name: br.name }), body, { wide: true, onClose: () => { clearTimeout(timer); putBranch(id, { upscale: up }).catch(() => {}).finally(() => { if (window.H3Takes) window.H3Takes.render(); }); } });
    }

    // ------------------------------------------------------------------ settings dialog
    // the settings of the open project, or ({ defaults: true }) the Studio's default settings for new projects
    async function openSettings({ defaults = false } = {}) {
        if (!defaults && !P.name) return showHome();
        if (defaults) {
            try { P.defaults = await api("/api/defaults"); } catch (e) { alert(e.message); return; }
        }
        let infoError = null;
        if (!P.info) {
            try { P.info = await api("/api/comfy/object_info"); } catch (e) { infoError = e.message; }
        }
        const s = defaults ? P.defaults : P.settings;
        let defTimer = null;
        const save = defaults
            ? () => { clearTimeout(defTimer); defTimer = setTimeout(() => put("/api/defaults", P.defaults).then((d) => { P.defaults.first_branch_size = d.first_branch_size; })
                .catch((e) => toast(_t("studio.default_settings_not_saved", { message: e.message }))), 300); }
            : saveSettings;
        const row = (label, input, hint) => h("div", { class: "tk-row" }, h("label", {}, label), input, hint ? h("span", { class: "hint" }, hint) : h("span"));
        const listOf = (key) => (P.info ? (comboValues(P.info, ...COMBOS[key]) || []) : []);
        const dl = (key) => downloadHint(key, listOf(key));
        const choice = (key, { none } = {}) => {
            const values = P.info ? (comboValues(P.info, ...COMBOS[key]) || []) : [];
            if (!values.length) return h("input", { value: s[key] ?? "", onchange: (e) => { s[key] = e.target.value; save(); } });
            const list = [...values];
            if (s[key] && !list.includes(s[key])) list.unshift(s[key]);
            return h("select", { onchange: (e) => { s[key] = e.target.value; save(); } },
                none ? h("option", { value: "", selected: !s[key] || null }, none) : null,
                list.map((v) => h("option", { value: v, selected: v === s[key] || null }, v)));
        };
        const num = (key, attrs = {}) => h("input", { type: "number", value: s[key], ...attrs, onchange: (e) => { s[key] = Number(e.target.value); save(); } });
        // live preview: ComfyUI's own, or KJNodes' Model Preview Override (TAE, animated, with sound)
        const livePreview = () => {
            const box = h("div", {});
            const kjInstalled = !!(P.info && P.info.ModelPreviewOverrideKJ);
            const draw = () => {
                const kj = s.preview_mode === "kj";
                const taes = P.info ? (comboValues(P.info, "ModelPreviewOverrideKJ", "tiny_vae") || []) : [];
                const tae = [...new Set([...(s.kj_tiny_vae ? [s.kj_tiny_vae] : []), ...(taes.length ? taes : ["none"])])];
                const set = (key, value) => { s[key] = value; save(); draw(); };
                fill(box, 
                    h("h3", {}, _t("studio.live_preview")),
                    row(_t("studio.source"), h("select", { onchange: (e) => set("preview_mode", e.target.value) },
                        h("option", { value: "comfy", selected: !kj || null }, _t("studio.comfyui_one_picture_per_step")),
                        h("option", { value: "kj", selected: kj || null, disabled: (!kjInstalled && !kj) || null }, _t("studio.kjnodes_model_preview_override") + (kjInstalled || !P.info ? "" : _t("studio.not_installed")))),
                        kj ? _t("studio.encore_adds_the_node_to_the") : _t("studio.comfyui_s_live_preview_method_setting")),
                    ...(kj ? [
                        row(_t("studio.decoder_tae"), h("select", { onchange: (e) => set("kj_tiny_vae", e.target.value) },
                            tae.map((v) => h("option", { value: v, selected: v === (s.kj_tiny_vae || "none") || null }, v === "none" ? _t("studio.none_approximate_colors") : v))),
                            _t("studio.in_comfyui_s_models_vae_approx")),
                        row(_t("studio.animated_frames"), h("input", { type: "number", min: -1, max: 1024, value: s.kj_frames ?? -1, onchange: (e) => set("kj_frames", Math.trunc(Number(e.target.value)) || -1) }),
                            _t("studio.1_the_whole_clip_length_1")),
                        row(_t("studio.frames_per_second"), h("input", { type: "number", min: 1, max: 60, value: s.kj_fps ?? 7, onchange: (e) => set("kj_fps", Number(e.target.value)) }),
                            _t("studio.without_sound_7_real_speed_with")),
                        row(_t("studio.sound"), h("label", { class: "tk-check" }, h("input", { type: "checkbox", checked: s.kj_audio || null, onchange: (e) => set("kj_audio", e.target.checked) }), _t("studio.add_the_generated_sound_to_the")),
                            _t("studio.audible_on_hover_if_sound_on")),
                        row(_t("studio.maximum_size"), h("input", { type: "number", min: 0, max: 8192, step: 8, value: s.kj_max_res ?? 512, onchange: (e) => set("kj_max_res", Number(e.target.value)) }), _t("studio.longest_side_in_pixels")),
                        row(_t("studio.jpeg_quality"), h("input", { type: "number", min: 30, max: 100, value: s.kj_quality ?? 80, onchange: (e) => set("kj_quality", Number(e.target.value)) })),
                    ] : []));
            };
            draw();
            return box;
        };
        // LoRA stack: applied one after the other, in this order
        const loraStack = () => {
            if (!Array.isArray(s.loras)) s.loras = [];
            const values = P.info ? (comboValues(P.info, ...COMBOS.lora_name) || []) : [];
            const box = h("div", { class: "studio-loras" });
            const draw = () => {
                fill(box, 
                    h("div", { class: "studio-loras-head" }, h("b", {}, _t("studio.lora")), h("span", { class: "hint" }, s.loras.length ? "" : _t("studio.none_2"))),
                    ...s.loras.map((l, i) => {
                        const list = [...values];
                        if (l.name && !list.includes(l.name)) list.unshift(l.name);
                        const file = list.length
                            ? h("select", { onchange: (e) => { l.name = e.target.value; save(); } },
                                h("option", { value: "", selected: !l.name || null }, _t("studio.choose_a_file")),
                                list.map((v) => h("option", { value: v, selected: v === l.name || null }, v)))
                            : h("input", { value: l.name, placeholder: _t("studio.file_name"), onchange: (e) => { l.name = e.target.value.trim(); save(); } });
                        return h("div", { class: `studio-lora${l.enabled ? "" : " off"}` },
                            h("input", { type: "checkbox", title: _t("studio.active"), checked: l.enabled || null, onchange: (e) => { l.enabled = e.target.checked; save(); draw(); } }),
                            file,
                            h("label", { class: "hint" }, _t("studio.strength")),
                            h("input", { type: "number", step: 0.05, value: l.strength, style: "width:70px", onchange: (e) => { l.strength = Number(e.target.value); save(); } }),
                            h("button", { class: "small danger", title: _t("studio.remove_this_lora"), onclick: () => { s.loras.splice(i, 1); save(); draw(); } }, "✕"));
                    }),
                    h("button", { class: "small", onclick: () => { s.loras.push({ name: "", strength: 1.0, enabled: true }); save(); draw(); } }, _t("studio.add_a_lora")),
                    h("div", { class: "hint" }, _t("studio.applied_one_after_the_other_uncheck")));
            };
            draw();
            return box;
        };
        const intro = defaults
            ? h("div", {},
                h("h3", {}, _t("studio.language")),
                h("div", { class: "tk-inline" },
                    h("select", { onchange: async (e) => {
                        try {
                            await put("/api/config", { language: e.target.value });
                            H3I18n.setLang(e.target.value);
                            location.reload();
                        } catch (err) { alert(err.message); }
                    } }, H3I18n.languages().map((l) => h("option", { value: l.code, selected: l.code === H3I18n.lang() || null }, l.name))),
                    h("span", { class: "hint" }, _t("studio.language_hint"))),
                h("h3", {}, _t("studio.theme")),
                h("div", { class: "tk-inline" },
                    h("select", { id: "studioThemeSelect", onchange: (e) => setTheme(e.target.value) },
                        [["dark", _t("studio.theme_dark")], ["light", _t("studio.theme_light")]].map(([v, l]) => h("option", { value: v, selected: v === H3Theme.get() || null }, l))),
                    h("span", { class: "hint" }, _t("studio.theme_hint"))),
                h("p", { class: "hint" }, _t("studio.settings_template_each_new_project_gets")),
                h("h3", {}, _t("studio.picture_size_of_the_first_branch")),
                sizePicker(Number(s.first_branch_size[0]), Number(s.first_branch_size[1]), (w, hh) => { s.first_branch_size = [w, hh]; save(); return true; }),
                h("h3", {}, _t("studio.reference_size_of_the_first_branch")),
                refSizePicker(s.first_branch_ref_size || "max", (v) => { s.first_branch_ref_size = v; save(); return true; }),
                h("p", { class: "hint" }, _t("studio.the_next_branches_copy_the_picture")))
            : h("div", { class: "tk-inline", style: "flex-wrap:wrap" },
                h("button", { onclick: async () => {
                    try {
                        const cur = await api("/api/defaults");
                        await put("/api/defaults", { ...JSON.parse(JSON.stringify(P.settings)), first_branch_size: cur.first_branch_size });
                        toast(_t("studio.project_settings_saved_as_default_settings"));
                    } catch (e) { alert(e.message); }
                } }, _t("studio.save_as_default_settings")),
                h("button", { onclick: async () => {
                    if (!await H3Dialog.confirm(_t("studio.replace_this_project_s_settings_with"))) return;
                    try {
                        const d = await api("/api/defaults");
                        delete d.first_branch_size;
                        delete d.first_branch_ref_size;
                        for (const k of Object.keys(P.settings)) delete P.settings[k];
                        Object.assign(P.settings, d);
                        await put(`/api/projects/${encodeURIComponent(P.name)}/settings`, P.settings);
                        dlg.close(); openSettings();
                        toast(_t("studio.default_settings_applied"));
                    } catch (e) { alert(e.message); }
                } }, _t("studio.apply_the_default_settings")));
        const body = h("div", {},
            intro,
            infoError ? h("div", { class: "msgs" }, h("div", { class: "warning" }, _t("studio.model_lists_unavailable_type_the_names", { infoError }))) : null,
            h("h3", {}, _t("studio.take_previews")),
            h("p", { class: "hint" }, _t("studio.the_picture_size_is_set_in")),
            row(_t("studio.preview_quality_crf"), num("crf", { min: 0, max: 51 }), _t("studio.lower_better_quality_bigger_files")),
            livePreview(),
            h("h3", {}, _t("studio.models")),
            row(_t("studio.diffusion_model"), choice("unet_name"), dl("unet_name")),
            row(_t("studio.precision"), choice("weight_dtype")),
            row(_t("studio.text_encoder"), choice("clip_name"), dl("clip_name")),
            row(_t("studio.encoder_type"), choice("clip_type")),
            row(_t("studio.video_vae"), choice("video_vae"), dl("video_vae")),
            row(_t("studio.audio_vae"), choice("audio_vae"), dl("audio_vae")),
            loraStack(),
            h("div", {}, downloadHint("lora", P.info ? (comboValues(P.info, ...COMBOS.lora_name) || []) : [])),
            h("details", {}, h("summary", {}, _t("studio.sampling_advanced")),
                row(_t("studio.attention"), choice("attention", { none: _t("studio.node_not_used") })),
                row(_t("studio.sampler_2"), choice("sampler_name")),
                row(_t("studio.scheduler"), choice("scheduler")),
                row(_t("studio.steps"), num("steps", { min: 1, max: 200 })),
                row(_t("studio.video_sigma_shift"), num("shift_video", { step: 0.1 })),
                row(_t("studio.audio_sigma_shift"), num("shift_audio", { step: 0.1 }))),
            h("p", { class: "hint" }, _t("studio.lists_read_from_comfyui", { v0: defaults ? _t("studio.saved_in_defaults_json") : _t("studio.saved_in_the_project_project_json"), v1: P.config?.comfy_url || "" })));
        const dlg = modal(defaults ? _t("studio.default_settings_for_new_projects") : _t("studio.settings_of_project", { name: P.name }), body);
    }

    // ------------------------------------------------------------------ installation: ComfyUI folder, custom nodes, models
    // Blocking on the first start (and whenever ComfyUI answers without the required nodes): Encore can only be used
    // once the required packs are loaded by ComfyUI, i.e. installed and ComfyUI restarted.
    let setupView = null;
    const fmtBytes = (n) => {
        if (n == null) return "?";
        const u = ["o", _t("studio.kb"), _t("studio.mb"), _t("studio.gb"), _t("studio.tb")]; let i = 0;
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return `${i >= 2 ? n.toFixed(1).replace(".", H3I18n.decimal()) : Math.round(n)} ${u[i]}`;
    };
    function onComfyBack() { if (setupView) setupView.refresh(); }
    async function needsSetup() {
        try {
            const st = await api("/api/setup");
            return !st.setup_done || (st.comfy_ok && !st.required_ok);
        } catch (_) { return false; }
    }
    function openSetup({ blocking = false, focus = null, startModel = null } = {}) {
        if (setupView) { setupView.close(); }
        let st = null, models = null, sizes = {}, closed = false, choice = null, timer = null;
        const overlay = h("div", { class: `studio-setup${blocking ? " blocking" : ""}`, style: `z-index:${nextZ()}` });
        const box = h("div", { class: "studio-setup-box" });
        overlay.append(box);
        document.body.append(overlay);
        const close = () => { closed = true; clearInterval(timer); overlay.remove(); setupView = null; };
        const dirIn = h("input", { style: "flex:1", placeholder: _t("studio.for_example_d_comfyui_windows_portable") });
        const pyIn = h("input", { style: "flex:1", placeholder: _t("studio.leave_empty_automatic_detection") });
        const urlIn = h("input", { style: "width:240px" });
        let dirty = false;
        for (const el of [dirIn, pyIn, urlIn]) el.addEventListener("input", () => { dirty = true; });
        const saveDir = async (checkPython) => {
            try {
                if (urlIn.value.trim() && urlIn.value.trim() !== P.config.comfy_url) P.config = await post("/api/config", { comfy_url: urlIn.value.trim() });
                st = await put("/api/setup/config", { comfy_dir: dirIn.value.trim(), comfy_python: pyIn.value.trim(), check_python: !!checkPython });
                dirty = false;
                await loadModels(true);
                draw();
            } catch (e) { alert(e.message); }
        };
        const loadModels = async (withSizes) => {
            try {
                const res = await api(`/api/models${withSizes ? "?sizes=1" : ""}`);
                for (const it of res.items) if (it.size) sizes[it.id] = it.size;
                models = res;
            } catch (_) { /* shown as unknown */ }
        };
        const install = async () => {
            const ids = st.packs.filter((p) => choice.has(p.id) && p.state === "missing").map((p) => p.id);
            if (!ids.length) return;
            try { st = await post("/api/setup/install", { packs: ids }); draw(); } catch (e) { alert(e.message); }
        };
        const download = async (id) => {
            try { await post("/api/models/download", { id }); await loadModels(false); draw(); } catch (e) { alert(e.message); }
        };
        const cancelDl = async (id) => { try { await post("/api/models/cancel", { id }); } catch (_) { /* ignore */ } };
        const stateLabel = {
            loaded: [_t("studio.loaded"), "ok"], installed: [_t("studio.installed_restart_comfyui"), "warn"], missing: [_t("studio.absent"), "bad"],
            outdated: [_t("studio.version_too_old"), "warn"], unknown: [_t("studio.unknown"), "muted"],
        };
        const refresh = async () => {
            try { st = await api("/api/setup"); } catch (_) { return; }
            if (!models || Object.values((models.items || [])).some((m) => m.job && m.job.status === "running")) await loadModels(false);
            if (!closed) draw();
        };
        function draw() {
            if (!st) return;
            if (!dirty) { dirIn.value = st.comfy_dir || ""; pyIn.value = P.config.comfy_python || ""; urlIn.value = P.config.comfy_url || ""; }
            // a pack already in ComfyUI (loaded, or its folder found) is checked and locked, like the required ones
            const detected = (p) => p.state === "loaded" || p.state === "installed" || p.state === "outdated";
            const locked = (p) => p.required || detected(p);
            if (!choice) choice = new Set(st.packs.filter((p) => p.required || p.state === "missing" || p.state === "unknown").map((p) => p.id));
            for (const p of st.packs) if (locked(p)) choice.add(p.id);
            const inst = st.install || {};
            const running = inst.running;
            const restartNeeded = !running && inst.finished && st.packs.some((p) => choice.has(p.id) && p.state === "installed");
            const toInstall = st.packs.filter((p) => choice.has(p.id) && p.state === "missing");
            const reqMissing = st.packs.filter((p) => p.required && p.state !== "loaded");
            const comfyLine = st.comfy_ok
                ? h("span", { class: "ok" }, _t("studio.comfyui_connected_2", { v0: st.comfy.version ? " (" + st.comfy.version + ")" : "" }))
                : h("span", { class: "bad" }, _t("studio.comfyui_does_not_answer_at", { comfy_url: st.comfy.url || P.config.comfy_url }));
            const pyLine = st.python
                ? h("span", {}, st.python_kind === "portable" ? _t("studio.portable_version") : st.python_kind === "venv" ? _t("studio.virtual_environment") : _t("studio.given"), h("code", {}, st.python),
                    st.python_check && st.python_check.python === st.python ? h("span", { class: st.python_check.ok ? "ok" : "bad" }, ` · ${st.python_check.text}`) : null)
                : h("span", { class: "bad" }, st.python_note || _t("studio.comfyui_s_python_not_found"));
            const packRows = st.packs.map((p) => {
                const [label, cls] = stateLabel[p.state] || [p.state, "muted"];
                const item = (inst.items || []).find((i) => i.id === p.id);
                const progress = item && item.status !== "done" ? ({ waiting: _t("studio.waiting"), cloning: _t("studio.git_clone"), pip: _t("studio.dependencies_pip"), error: _t("studio.error_2") })[item.status] : null;
                return h("tr", {},
                    h("td", {}, h("input", { type: "checkbox", checked: choice.has(p.id) || null, disabled: locked(p) || running || null,
                        title: detected(p) ? _t("studio.already_in_comfyui") : p.required ? _t("studio.required") : _t("studio.optional"),
                        onchange: (e) => { if (e.target.checked) choice.add(p.id); else choice.delete(p.id); draw(); } })),
                    h("td", {}, h("a", { class: "studio-pack-link", href: p.url.replace(/\.git$/, ""), target: "_blank", rel: "noopener",
                        title: _t("studio.open_the_repository", { v0: p.url.replace(/\.git$/, "") }) }, p.name), p.required ? h("span", { class: "studio-req" }, "obligatoire") : h("span", { class: "hint" }, " facultatif"),
                        h("div", { class: "hint" }, p.why), p.note ? h("div", { class: "hint warn" }, p.note) : null,
                        item && item.error ? h("div", { class: "bad" }, item.error) : null),
                    h("td", { class: `studio-pack-state ${progress ? (item.status === "error" ? "bad" : "warn") : cls}` }, progress || label));
            });
            const modelRows = (models && models.items ? models.items : []).map((m) => {
                const job = m.job;
                const size = m.size || sizes[m.id];
                let cell;
                if (m.present || (job && job.status === "done")) cell = h("span", { class: "ok" }, _t("studio.present"));
                else if (job && job.status === "running") {
                    const pct = job.size ? Math.floor(100 * job.done / job.size) : 0;
                    cell = h("div", { class: "studio-dl" }, h("div", { class: "studio-qs-bar" }, h("i", { style: `width:${pct}%` })),
                        h("span", { class: "hint" }, `${pct} % · ${fmtBytes(job.done)} / ${fmtBytes(job.size)} · ${fmtBytes(job.speed)}/s`),
                        h("button", { class: "small", onclick: () => cancelDl(m.id) }, _t("studio.cancel_2")));
                } else {
                    cell = h("div", { class: "studio-dl" },
                        h("button", { class: "small", disabled: !st.comfy_dir_ok || null, onclick: () => download(m.id) },
                            m.partial ? _t("studio.resume_already_there", { v0: fmtBytes(m.partial) }) : _t("studio.download")),
                        job && job.status === "error" ? h("span", { class: "bad" }, job.error) : null,
                        job && job.status === "cancelled" ? h("span", { class: "hint" }, _t("studio.cancelled_can_be_resumed")) : null,
                        m.error ? h("span", { class: "hint warn" }, m.error) : null);
                }
                return h("tr", {}, h("td", {}, h("b", {}, m.label), m.required ? null : h("span", { class: "hint" }, " facultatif"),
                    h("div", { class: "hint" }, `${m.folder}/${m.file}`)),
                    h("td", { class: "hint", style: "white-space:nowrap" }, size ? fmtBytes(size) : ""), h("td", {}, cell));
            });
            const free = models && models.items && models.items.find((m) => m.free != null);
            const canGo = st.required_ok;
            fill(box, ...[
                h("div", { class: "studio-setup-head" }, logo(56), h("h2", {}, blocking ? _t("studio.welcome_to_encore") : _t("studio.installation")),
                    h("span", { style: "flex:1" })),
                blocking ? h("p", { class: "hint" }, _t("studio.before_starting_encore_checks_that_comfyui")) : null,
                h("section", {}, h("h3", {}, "1. ComfyUI"),
                    h("div", { class: "tk-row" }, h("label", {}, _t("studio.address")), h("div", { class: "tk-inline" }, urlIn, comfyLine), h("span")),
                    h("div", { class: "tk-row" }, h("label", {}, _t("studio.folder")), h("div", { class: "tk-inline", style: "width:100%" }, dirIn,
                        h("button", { onclick: async () => { const path = await browseFolder(dirIn.value); if (path) { dirIn.value = path; dirty = true; } } }, _t("studio.browse")),
                        h("button", { class: "primary", onclick: () => saveDir(false) }, _t("studio.use"))), h("span")),
                    h("div", { class: "tk-row" }, h("label", {}, ""), st.comfy_dir_ok ? h("span", { class: "ok" }, `✓ ${st.comfy_root}`)
                        : h("span", { class: st.comfy_dir ? "bad" : "hint" }, st.comfy_dir ? _t("studio.this_folder_is_not_recognized") : _t("studio.the_folder_that_holds_custom_nodes")), h("span")),
                    h("div", { class: "tk-row" }, h("label", {}, _t("studio.comfyui_s_python")), h("div", {}, pyLine), h("span")),
                    h("div", { class: "tk-row" }, h("label", {}, ""), h("div", { class: "tk-inline", style: "width:100%" }, pyIn,
                        h("button", { onclick: () => saveDir(true), title: _t("studio.runs_this_python_and_checks_that") }, _t("studio.check"))), h("span")),
                    h("div", { class: "tk-row" }, h("label", {}, "git"), st.git ? h("span", { class: "ok" }, `✓ ${st.git}`)
                        : h("span", { class: "bad" }, _t("studio.not_found_install_git_for_windows")), h("span"))),
                h("section", {}, h("h3", {}, _t("studio.2_custom_nodes")),
                    h("p", { class: "hint" }, _t("studio.encore_can_install_the_checked_packs")
                        + _t("studio.you_can_also_install_them_yourself")
                        + _t("studio.after_comfyui_restarts_encore_detects_them")),
                    h("table", { class: "studio-packs" }, packRows),
                    st.core_missing.length ? h("div", { class: "bad" }, _t("studio.comfyui_is_too_old_missing_nodes", { v0: st.core_missing.join(", ") })) : null,
                    h("div", { class: "studio-dlg-actions", style: "justify-content:flex-start" },
                        h("button", { class: "primary", disabled: running || !toInstall.length || !st.comfy_dir_ok || !st.python || !st.git || null, onclick: install },
                            running ? _t("studio.installing") : toInstall.length ? _t("studio.install", { length: toInstall.length }) : _t("studio.nothing_to_install")),
                        inst.error ? h("span", { class: "bad" }, inst.error) : null),
                    restartNeeded || (st.comfy_ok && st.packs.some((p) => p.state === "installed"))
                        ? h("div", { class: "studio-restart" }, _t("studio.restart_comfyui_now_close_it_then")) : null,
                    (inst.log || []).length ? h("details", { open: running || null }, h("summary", {}, _t("studio.installation_log")),
                        h("pre", { class: "studio-log" }, inst.log.slice(-200).join("\n"))) : null),
                h("section", { id: "setupModels" }, h("h3", {}, _t("studio.3_default_models")),
                    h("p", { class: "hint" }, _t("studio.downloaded_from_hugging_face_into_comfyui", { v0: free ? _t("studio.left_on_this_disk", { v0: fmtBytes(free.free) }) : "" })),
                    !st.comfy_dir_ok ? h("p", { class: "hint warn" }, _t("studio.first_give_the_comfyui_folder")) : null,
                    h("table", { class: "studio-packs" }, modelRows)),
                h("div", { class: "studio-setup-foot" },
                    blocking ? h("span", { class: canGo ? "ok" : "hint" }, canGo ? _t("studio.everything_is_ready") :
                        !st.comfy_ok ? _t("studio.waiting_for_comfyui") : reqMissing.length ? _t("studio.missing", { v0: reqMissing.map((p) => p.name).join(", ") }) : _t("studio.waiting_3")) : null,
                    h("span", { style: "flex:1" }),
                    blocking ? h("button", { class: "primary", disabled: !canGo || null, onclick: async () => {
                        try { await post("/api/setup/done", {}); close(); afterSetup(); } catch (e) { alert(e.message); }
                    } }, _t("studio.continue")) : h("button", { onclick: close }, _t("studio.close")))].filter(Boolean));
            const log = box.querySelector(".studio-log");
            if (log) log.scrollTop = log.scrollHeight;
        }
        setupView = { refresh, close };
        (async () => {
            try { st = await api("/api/setup"); } catch (e) { alert(e.message); }
            await loadModels(true);
            draw();
            if (focus === "models") document.getElementById("setupModels")?.scrollIntoView({ block: "start" });
            if (startModel) {
                const m = models && models.items.find((x) => x.id === startModel);
                if (m && !m.present && !(m.job && m.job.status === "running")) download(startModel);
            }
        })();
        timer = setInterval(refresh, 2000);
    }
    let afterSetup = () => {};
    // ⬇ next to a model list: shown when the default file of that setting is not in ComfyUI's list
    function downloadHint(settingKey, currentList) {
        const box = h("span", { class: "studio-dlhint" });
        api("/api/models").then((res) => {
            const m = (res.items || []).find((x) => x.setting === settingKey);
            if (!m || m.present || (currentList || []).includes(m.file)) return;
            box.append(h("button", { class: "small", title: _t("studio.hugging_face_comfyui_models", { label: m.label, file: m.file, folder: m.folder }),
                onclick: () => openSetup({ focus: "models", startModel: m.id }) }, _t("studio.download_the_default_model")));
        }).catch(() => {});
        return box;
    }

    // ------------------------------------------------------------------ LoRA "en plus" and upscale, per branch / clip / take
    // Project stack always. Branch + clip add up (same file: the clip's strength wins) unless the clip says "sans les LoRA de
    // branche". A take launched with ▾ uses exactly the list of its dialog. Upscale: take > clip > branch.
    const fmtLoras = (list) => list.map((l) => `${l.name.replace(/\.safetensors$/i, "")} ${String(l.strength).replace(".", H3I18n.decimal())}`).join(" + ");
    function mergeLoras(...lists) {
        const out = [];
        for (const list of lists) for (const l of list || []) {
            if (!l || !l.name) continue;
            const same = out.find((x) => x.name === l.name);
            if (same) same.strength = Number(l.strength); else out.push({ name: l.name, strength: Number(l.strength) });
        }
        return out;
    }
    function clipDefault(index) {
        const clip = (plan().clips || [])[index - 1];
        const d = (clip && P.clipDefaults && P.clipDefaults[clip.name]) || {};
        return { loras: d.loras || [], no_branch_loras: !!d.no_branch_loras };
    }
    // what a plain click (no dialog) will use for this clip in this branch
    function effectiveTake(branchId, index) {
        const br = branchById(branchId) || {}, cd = clipDefault(index);
        const loras = mergeLoras(cd.no_branch_loras ? [] : br.loras || [], cd.loras);
        const upSettings = branchUpscale(br);
        const upscale = !!upSettings.enabled;
        return { loras, upscale, upSettings,
            text: _t("studio.extra_lora_upscale", { v0: loras.length ? fmtLoras(loras) : _t("studio.none"), v1: upscale ? _t("studio.yes") : _t("studio.no"), upFrom: _t("studio.branch") }) };
    }
    const branchUpscale = (br) => Object.assign({}, UP_DEFAULT, JSON.parse(JSON.stringify((br && br.upscale) || {})));
    // what a generation of this clip in this branch would use if launched now with a plain click (the « Generation »
    // block of the plan window of a « generate » box)
    function generationNow(branchId, index) {
        const br = branchById(branchId) || {};
        const eff = effectiveTake(branchId, index);
        const st = P.settings || {};
        const w = Number(br.width), hh = Number(br.height);
        const sum = eff.upscale ? upscaleSummary(eff.upSettings, w, hh, Number(st.steps) || 8) : null;
        return {
            models: { unet_name: st.unet_name, weight_dtype: st.weight_dtype, clip_name: st.clip_name, video_vae: st.video_vae, audio_vae: st.audio_vae,
                sampler_name: st.sampler_name, scheduler: st.scheduler, steps: st.steps, shift_video: st.shift_video, shift_audio: st.shift_audio,
                attention: st.attention, loras: (st.loras || []).filter((l) => l.enabled && l.name).map((l) => ({ name: l.name, strength: l.strength })) },
            extra_loras: eff.loras, size: [w, hh], ref_image_size: br.ref_image_size, song: br.song || null,
            upscale: sum ? { summary: sum.error ? "⚠ " + sum.error : sum.text, source: "branch" } : null, branch: br.name,
        };
    }
    async function loraValues() {
        if (!P.info) { try { P.info = await api("/api/comfy/object_info"); } catch (e) { /* lists unknown: free text */ } }
        return P.info ? (comboValues(P.info, ...COMBOS.lora_name) || []) : [];
    }
    // an editable list of {name, strength}; onchange(list) after each change
    function loraEditor(list, values, onchange) {
        const box = h("div", { class: "studio-loras" });
        const draw = () => {
            fill(box, ...list.map((l, i) => {
                const names = [...new Set([...(l.name ? [l.name] : []), ...values])];
                return h("div", { class: "studio-lora" },
                    names.length ? h("select", { onchange: (e) => { l.name = e.target.value; onchange(list); } },
                        [h("option", { value: "" }, _t("studio.choose_a_file")), ...names.map((v) => h("option", { value: v, selected: v === l.name || null }, v))])
                        : h("input", { value: l.name, placeholder: _t("studio.file_name"), onchange: (e) => { l.name = e.target.value.trim(); onchange(list); } }),
                    h("label", { class: "hint" }, _t("studio.strength")),
                    h("input", { type: "number", step: 0.05, value: l.strength, style: "width:70px", onchange: (e) => { l.strength = Number(e.target.value); onchange(list); } }),
                    h("button", { class: "small danger", title: _t("studio.remove"), onclick: () => { list.splice(i, 1); onchange(list); draw(); } }, "✕"));
            }), h("button", { class: "small", onclick: () => { list.push({ name: "", strength: 1.0 }); onchange(list); draw(); } }, _t("studio.add_a_lora")));
        };
        draw();
        return box;
    }
    const cleanList = (list) => mergeLoras(list.filter((l) => l.name).map((l) => ({ name: l.name, strength: Number(l.strength) || 0 })));
    function projectStackHint() {
        const stack = (P.settings.loras || []).filter((l) => l.enabled && l.name);
        return _t("studio.always_applied_first_project_settings", { v0: stack.length ? fmtLoras(stack) : _t("studio.none") });
    }
    async function openBranchLoras(id) {
        const br = branchById(id);
        if (!br) return;
        const values = await loraValues();
        const list = JSON.parse(JSON.stringify(br.loras || []));
        let timer = null;
        const save = () => { clearTimeout(timer); timer = setTimeout(() => putBranch(id, { loras: cleanList(list) }).catch((e) => toast(_t("studio.lora_not_saved", { message: e.message }))), 250); };
        modal(_t("studio.lora_of_branch", { name: br.name }), h("div", { class: "studio-upscale" },
            h("p", { class: "hint" }, _t("studio.added_to_each_take_of_this")
                + _t("studio.they_add_up_with_the_clip")),
            h("p", { class: "hint" }, projectStackHint()),
            loraEditor(list, values, save)));
    }
    async function openClipDefaults(index) {
        const clip = (plan().clips || [])[index - 1];
        if (!clip) return;
        const values = await loraValues();
        const cd = clipDefault(index);
        const value = { loras: JSON.parse(JSON.stringify(cd.loras)), no_branch_loras: cd.no_branch_loras };
        const send = () => put(`/api/projects/${encodeURIComponent(P.name)}/clip-defaults`, { clip: clip.name, value: { ...value, loras: cleanList(value.loras) } })
            .then((res) => { P.clipDefaults = res.clip_defaults || {}; if (window.H3Takes) window.H3Takes.recompute(); });
        let timer = null;
        const save = () => { clearTimeout(timer); timer = setTimeout(() => send().catch((e) => toast(_t("studio.clip_settings_not_saved", { message: e.message }))), 250); };
        modal(_t("studio.clip_lora_of", { index, name: clip.name }), h("div", { class: "studio-upscale" },
            h("p", { class: "hint" }, _t("studio.valid_for_this_clip_in_every")
                + _t("studio.the_arrow_of_these_buttons_tunes")),
            h("h3", {}, _t("studio.clip_lora")),
            h("p", { class: "hint" }, projectStackHint()),
            loraEditor(value.loras, values, save),
            h("label", { class: "tk-check", style: "margin-top:8px" }, h("input", { type: "checkbox", checked: value.no_branch_loras || null,
                onchange: (e) => { value.no_branch_loras = e.target.checked; save(); } }), _t("studio.without_the_branch_lora_for_this"))),
            { onClose: () => { clearTimeout(timer); send().catch(() => {}); } });
    }
    // "prise réglée": the dialog of the ▾ buttons. Resolves {loras, upscale, seed} or null.
    // preset: {loras, upscale: "on"|"off"} of the take the ▾ belongs to; without it, the branch + clip settings
    async function takeDialog({ clip: index, branch: branchId, title, preset }) {
        const values = await loraValues();
        if (!P.info) { try { P.info = await api("/api/comfy/object_info"); } catch (e) { /* lists unknown: free text */ } }
        const eff = effectiveTake(branchId, index);
        const br = branchById(branchId) || {};
        const list = JSON.parse(JSON.stringify(preset ? preset.loras : eff.loras));
        // upscale: the branch's settings, which this take may change (« enabled » included). From a take, its own
        // settings when it had some, else the branch's with its « with / without »
        const base = branchUpscale(br);
        const key = (u) => JSON.stringify(Object.keys(UP_DEFAULT).sort().map((k) => [k, u[k] ?? null]));
        let up = branchUpscale(br);
        if (preset && preset.upscale_settings) up = Object.assign({}, UP_DEFAULT, JSON.parse(JSON.stringify(preset.upscale_settings)), { enabled: true });
        else if (preset && preset.upscale) up.enabled = preset.upscale === "on";
        let open = false;
        return new Promise((resolve) => {
            let done = false;
            const finish = (v) => { if (done) return; done = true; resolve(v); dlg.close(); };
            const seed = h("input", { placeholder: _t("studio.automatic"), style: "width:200px", onkeydown: (e) => { if (e.key === "Enter") go(); } });
            const go = () => {
                const raw = seed.value.trim();
                const n = raw === "" ? null : Number(raw);
                if (raw !== "" && !(Number.isInteger(n) && n >= 0 && n <= 2 ** 48)) { alert(_t("studio.invalid_seed_an_integer_from_0", { v0: 2 ** 48 })); return; }
                const changed = key(up) !== key(base);
                finish({ loras: cleanList(list), upscale: null, seed: n, upscale_settings: changed ? JSON.parse(JSON.stringify(up)) : null });
            };
            // a summary line (« like the branch » / « changed for this take ») and the form, folded by default
            const line = h("div", {}), form = h("div", {});
            const upBox = h("div", {}, line, form);
            const drawLine = () => {
                const changed = key(up) !== key(base);
                const sum = up.enabled ? upscaleSummary(up, Number(br.width), Number(br.height), Number(P.settings.steps) || 8) : null;
                const text = !up.enabled ? _t("studio.upscale_off") : sum.error ? "⚠ " + sum.error : sum.text;
                line.className = `studio-up-line${changed ? " changed" : ""}`;
                fill(line, ...[
                    h("span", {}, (changed ? _t("studio.upscale_changed_for_this_take") : _t("studio.upscale_like_the_branch", { name: br.name || "?" })) + " — " + text),
                    h("button", { class: "small", onclick: () => { open = !open; drawForm(); drawLine(); } }, open ? _t("studio.fold") : _t("studio.modify")),
                    changed ? h("button", { class: "small", onclick: () => { up = branchUpscale(br); drawForm(); drawLine(); } }, _t("studio.reset_to_branch_settings")) : null,
                ].filter(Boolean));
            };
            const drawForm = () => fill(form, ...(open ? [upscaleEditor(up, [Number(br.width), Number(br.height)], drawLine, { enabled: true, take: true })] : []));
            drawLine();
            const dlg = modal(title || _t("studio.take_of_clip", { index }), h("div", { class: "studio-upscale" },
                h("p", { class: "hint" }, _t("studio.branch_these_settings_only_apply_to", { v0: br.name || "?" })),
                h("h3", {}, _t("studio.extra_lora")),
                h("p", { class: "hint" }, projectStackHint() + (preset ? _t("studio.list_pre_filled_with_those_of") : _t("studio.list_pre_filled_with_those_of_2"))),
                loraEditor(list, values, () => {}),
                h("h3", {}, _t("studio.latent_upscale")),
                upBox,
                h("h3", {}, _t("studio.seed")),
                seed,
                h("div", { class: "studio-dlg-actions" }, h("button", { onclick: () => finish(null) }, _t("studio.cancel")), h("button", { class: "primary", onclick: go }, _t("studio.start_2")))),
                { wide: true, onClose: () => finish(null) });
        });
    }

    // ------------------------------------------------------------------ takes tab: what it asks the Studio
    function takesApi() {
        const base = () => `/api/projects/${encodeURIComponent(P.name)}`;
        return {
            listTakes: () => api(`${base()}/takes`),
            saveSelection: (selection) => put(`${base()}/selection`, { selection }),
            deleteTakes: (takes) => post(`${base()}/delete-takes`, { takes }),
            assemble: (clip, take, allowInvalid) => post(`${base()}/assemble`, { clip, take, allow_invalid: !!allowInvalid }),
            assembleCheck: (clip, take) => post(`${base()}/assemble-check`, { clip, take }),
            takePlan: (clip, take) => api(`${base()}/takes/${clip}/${encodeURIComponent(take)}/plan`),
            exports: () => api(`${base()}/exports`),
            // the start video's segment, small (made once by ffmpeg): GET its state, POST to have it made
            segmentThumb: (file, start, end, method) => api(`${base()}/resources/thumb?path=${encodeURIComponent(file)}&start=${start}&end=${end}`, { method: method || "GET" }),
            restoreCheckpoint,
            generate: (clip, parent, random, seed, branch, upscale, loras, upscaleSettings) => post(`${base()}/generate`, { clip, parent, random: !!random, seed: seed ?? null, branch: branch || null, upscale: upscale || null, loras: loras ?? null, upscale_settings: upscaleSettings || null }),
            jobPlan: (id) => api(`${base()}/jobs/${encodeURIComponent(id)}/plan`),
            clipDefault, effectiveTake, generationNow, openBranchLoras, openClipDefaults, takeDialog, fmtLoras,
            fillBranch: (id, dryRun, assemble = true) => post(`${base()}/branches/${encodeURIComponent(id)}/fill`, { dry_run: !!dryRun, assemble: !!assemble }),
            assembleAfter: (job) => post(`${base()}/assemble`, { job }),
            jobs: () => (P.name ? api(`${base()}/jobs`) : Promise.resolve({ jobs: [] })),
            cancel: (ids) => post(`${base()}/cancel`, { ids }),
            removeJob: (id) => post(`${base()}/remove-job`, { id }),
            previewUrl: (id, seq) => `${base()}/jobs/${encodeURIComponent(id)}/preview?s=${seq}`,
            settings: () => P.settings,
            branches: () => P.branches,
            async createBranch() {
                const res = await post(`${base()}/branches`, {});
                P.branches = res.branches;
                return res;
            },
            openBranch, renameBranch, deleteBranch, openUpscale,
            legacyRefSize: () => P.legacyRefSize || "match",
            async songSha(path) {
                let it = (P.resources.songs || []).find((x) => x.path === path);
                if (!it) { await refreshResources(); it = (P.resources.songs || []).find((x) => x.path === path); }
                return it ? it.sha : null;
            },
            // what the takes are compared with: picture size and the SHA-256 of each reference file
            current() {
                const sha = (kind, path) => (path ? ((P.resources[kind] || []).find((it) => it.path === path) || {}).sha || null : null);
                const branches = {};
                for (const b of P.branches) {
                    const refs = {};
                    for (const [name, r] of Object.entries(b.refs || {})) refs[name] = { image: sha("images", r && r.image), voice: sha("voices", r && r.voice) };
                    const sv = plan().start_video || plan().edit_video;    // the project's video, the same for every branch
                    if (sv && sv.ref) refs[sv.ref] = { image: null, voice: null, video: sha("videos", P.startVideoFile) };
                    branches[b.id] = { refs, song: sha("songs", b.song), size: [Number(b.width), Number(b.height)], ref_image_size: b.ref_image_size || null };
                }
                return { branches, default_branch: P.branches.length ? P.branches[0].id : null, legacy_ref_image_size: P.legacyRefSize || "match" };
            },
            objectInfo: async () => (P.info = P.info || await api("/api/comfy/object_info")),
            viewUrl: (path) => `${fileUrl(path)}?t=1`,
            infosUrl: (path) => `${base()}/infos?file=${encodeURIComponent(path)}`,
            openSettings,
            async savePlan() {
                if (!ed().state.dirty) return "plan.json";
                await savePlan(ed().state.plan);
                ed().state.dirty = false;
                ed().render();
                return "plan.json";
            },
            async digests(images, voices) {
                const find = (kind, path) => (P.resources[kind] || []).find((it) => it.path === path);
                if ([...images.map((p) => find("images", p)), ...voices.map((p) => find("voices", p))].some((x) => !x)) await refreshResources();
                const out = { images: {}, voices: {} };
                for (const p of images) if (p) out.images[p] = find("images", p)?.sha || null;
                for (const p of voices) if (p) out.voices[p] = find("voices", p)?.sha || null;
                return out;
            },
        };
    }

    window.H3Studio = { state: P, presets, openProject, showHome };
    start();
})();
