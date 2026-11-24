// ---------------------------------------------------------------------------------------------
// Encore - deleting a take (with what follows it) and the trash (chantier A, lot A3).
// Nothing is erased when something is deleted: it goes to the trash, from which it is restored or erased.
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
            else node.setAttribute(k, v === true ? "" : v);
        }
        for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) node.append(kid instanceof Node ? kid : String(kid));
        return node;
    }
    const _t = (k, v) => H3I18n.t(k, v);
    const K = () => window.H3Studio.kit;
    const tk = () => window.H3Takes;
    const short = (id) => String(id || "").split("_").pop().slice(0, 4);
    const after = (res) => { if (res && res.project) K().applyProject(res.project); if (tk()) tk().rescan(); };

    // 🗑 on a take: says what goes with it, then moves it to the trash
    async function deleteTake(index, takeId) {
        try {
            const url = `${K().base()}/takes/delete`;
            const plan = await K().post(url, { take: takeId });
            const byClip = {};
            for (const [i, id] of plan.takes || []) if (id !== takeId) (byClip[i] = byClip[i] || []).push(short(id));
            const others = Object.entries(byClip).map(([i, ids]) => _t("trash.clip_takes", { index: i, takes: ids.join(", ") }));
            const bases = Object.entries(plan.bases || {}).map(([name, k]) => k ? _t("trash.base_kept", { name, k }) : _t("trash.base_none", { name }));
            const msg = [_t("trash.delete_take", { index, take: short(takeId) }),
                others.length ? _t("trash.with") + "\n• " + others.join("\n• ") : _t("trash.alone"),
                bases.length ? bases.join("\n") : null, _t("trash.to_trash")].filter(Boolean).join("\n\n");
            if (!await H3Dialog.confirm(msg)) return;
            await K().saveIfDirty();
            after(await K().post(url, { take: takeId, confirm: true }));
            K().toast(_t("trash.moved", { count: plan.count }));
        } catch (e) { alert(e.message); }
    }

    // the trash: restore an entry (with what it holds), erase it, or empty the trash
    async function open() {
        const body = h("div", { class: "trash-list" });
        const when = (t) => new Date(t * 1000).toLocaleString(H3I18n.lang() === "fr" ? "fr-FR" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
        const draw = async () => {
            let data;
            try { data = await K().api(`${K().base()}/trash`); } catch (e) { K().fill(body, h("p", { class: "hint" }, e.message)); return; }
            const entries = data.entries || [];
            K().fill(body,
                h("p", { class: "hint" }, _t("trash.hint")),
                entries.length ? entries.map((e) => h("div", { class: "trash-row" },
                    h("span", { class: "trash-kind" }, e.kind === "branch" ? "⎇" : "▭"),
                    h("div", { class: "trash-what" }, h("b", {}, e.label), h("div", { class: "hint" }, when(e.when)
                        + (e.videos ? " · " + _t("trash.videos", { count: e.videos }) : ""))),
                    h("button", { class: "small primary", onclick: async () => {
                        try { after(await K().post(`${K().base()}/trash/${encodeURIComponent(e.id)}/restore`, {})); K().toast(_t("trash.restored")); } catch (err) { alert(err.message); }
                        draw();
                    } }, _t("trash.restore")),
                    h("button", { class: "small danger", onclick: async () => {
                        if (!await H3Dialog.confirm(_t("trash.erase_confirm", { label: e.label }))) return;
                        try { await K().api(`${K().base()}/trash/${encodeURIComponent(e.id)}`, { method: "DELETE" }); } catch (err) { alert(err.message); }
                        draw();
                    } }, _t("trash.erase"))))
                    : h("p", { class: "hint" }, _t("trash.empty")),
                entries.length ? h("div", { class: "tk-inline", style: "justify-content:flex-end;margin-top:10px" },
                    h("button", { class: "danger", onclick: async () => {
                        if (!await H3Dialog.confirm(_t("trash.empty_confirm", { count: entries.length }))) return;
                        try { await K().api(`${K().base()}/trash`, { method: "DELETE" }); } catch (err) { alert(err.message); }
                        draw();
                    } }, _t("trash.empty_all"))) : null);
        };
        draw();
        K().modal(_t("trash.title"), body, { wide: true });
    }

    window.H3Trash = { deleteTake, open };
})();
