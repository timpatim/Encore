// In-app dialogs replacing the browser's alert / confirm / prompt (same look as the rest of the app).
// H3Dialog.alert(text) -> Promise<void> ; H3Dialog.confirm(text, opts) -> Promise<boolean> ;
// H3Dialog.prompt(text, value, opts) -> Promise<string|null>. window.alert is redirected here
// (alerts never needed to block); confirm and prompt are awaited at their call sites.
const H3Dialog = (() => {
    const DANGER = /supprim|restaur|écraser|arrêter|annuler|interrompre|remplacer|perdues|invalidées|retirer/i;
    function open(text, { input = null, cancel = true, ok = "OK", no: noLabel = _t("dialog.cancel"), danger = false, check = null } = {}) {
        return new Promise((resolve) => {
            const prev = document.activeElement;
            const overlay = document.createElement("div");
            overlay.className = "h3-dlg";
            const box = document.createElement("div");
            box.className = "h3-dlg-box";
            box.setAttribute("role", "dialog");
            const msg = document.createElement("div");
            msg.className = "h3-dlg-text";
            msg.textContent = String(text ?? "");
            box.append(msg);
            let field = null;
            if (input !== null) {
                field = document.createElement("input");
                field.className = "h3-dlg-input";
                field.value = input;
                box.append(field);
            }
            let box2 = null;
            if (check) {
                const label = document.createElement("label");
                label.className = "h3-dlg-check";
                box2 = document.createElement("input");
                box2.type = "checkbox";
                box2.checked = !!check.checked;
                label.append(box2, document.createTextNode(" " + check.label));
                box.append(label);
            }
            const row = document.createElement("div");
            row.className = "h3-dlg-buttons";
            const okBtn = document.createElement("button");
            okBtn.textContent = ok;
            okBtn.className = danger ? "danger-fill" : "primary";
            let cancelBtn = null;
            if (cancel) {
                cancelBtn = document.createElement("button");
                cancelBtn.textContent = noLabel;
                row.append(cancelBtn);
            }
            row.append(okBtn);
            box.append(row);
            overlay.append(box);
            const done = (value) => {
                document.removeEventListener("keydown", onKey, true);
                overlay.remove();
                try { prev && prev.focus && prev.focus(); } catch (_) { /* ignore */ }
                resolve(value);
            };
            const yes = () => done(field ? field.value : box2 ? { checked: box2.checked } : true);
            const no = () => done(field ? null : (cancel ? false : undefined));
            const onKey = (e) => {
                if (!document.body.contains(overlay) || overlay !== [...document.querySelectorAll(".h3-dlg")].pop()) return;
                if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); no(); }
                else if (e.key === "Enter" && !(e.target && e.target.tagName === "BUTTON" && e.target !== okBtn)) { e.preventDefault(); e.stopPropagation(); yes(); }
            };
            okBtn.onclick = yes;
            if (cancelBtn) cancelBtn.onclick = no;
            overlay.addEventListener("mousedown", (e) => { if (e.target === overlay && cancel) no(); });
            document.addEventListener("keydown", onKey, true);
            document.body.append(overlay);
            if (field) { field.focus(); field.select(); } else (danger && cancelBtn ? cancelBtn : okBtn).focus();
        });
    }
    return {
        alert: (text) => open(text, { cancel: false }),
        confirm: (text, opts = {}) => open(text, { ok: opts.ok || _t("dialog.yes"), no: opts.no || _t("dialog.no"), danger: opts.danger ?? DANGER.test(String(text)), check: opts.check || null }),
        prompt: (text, value = "", opts = {}) => open(text, { input: value ?? "", ok: opts.ok || "OK" }),
    };
})();
window.H3Dialog = H3Dialog;
window.alert = (text) => { H3Dialog.alert(text); };
