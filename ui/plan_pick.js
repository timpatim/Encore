// ---------------------------------------------------------------------------------------------
// H3Pick: every long drop-down list of the app (LoRA, models…) opens with a filter field.
// The native <select> stays where it is (layout, value, onchange unchanged): a click or a key on it
// opens a filtered list under it instead of the browser's own list.
// ---------------------------------------------------------------------------------------------
const H3Pick = (() => {
    const MIN_OPTIONS = 8;          // shorter lists keep the browser's list
    let pop = null;

    const eligible = (sel) => sel && sel.tagName === "SELECT" && !sel.multiple && !sel.disabled
        && sel.dataset.nopick === undefined && sel.options.length >= MIN_OPTIONS;

    function close() {
        if (!pop) return;
        const { sel, node } = pop;
        pop = null;
        node.remove();
        window.removeEventListener("resize", close);
        document.removeEventListener("scroll", onScroll, true);
        if (sel.isConnected) sel.focus();
    }
    function onScroll(e) { if (pop && !pop.node.contains(e.target)) close(); }

    function choose(sel, option) {
        if (option.disabled) return;
        const changedValue = sel.value !== option.value;
        sel.value = option.value;
        close();
        if (changedValue) {
            sel.dispatchEvent(new Event("input", { bubbles: true }));
            sel.dispatchEvent(new Event("change", { bubbles: true }));
        }
    }

    function open(sel, typed = "") {
        close();
        const node = document.createElement("div");
        node.className = "h3-pick-pop";
        const input = document.createElement("input");
        input.className = "h3-pick-filter";
        input.placeholder = "filtrer…";
        input.value = typed;
        const count = document.createElement("span");
        count.className = "h3-pick-count";
        const head = document.createElement("div");
        head.className = "h3-pick-head";
        head.append(input, count);
        const list = document.createElement("div");
        list.className = "h3-pick-list";
        list.setAttribute("role", "listbox");
        node.append(head, list);
        document.body.append(node);

        const all = [...sel.options].map((o) => ({ o, text: o.textContent, group: o.parentElement.tagName === "OPTGROUP" ? o.parentElement.label : "" }));
        let shown = [], active = 0;
        const draw = () => {
            const terms = input.value.toLowerCase().split(/\s+/).filter(Boolean);
            shown = all.filter((x) => !terms.length || terms.every((t) => (x.text + " " + x.o.value).toLowerCase().includes(t)));
            const current = shown.findIndex((x) => x.o.selected);
            active = Math.max(0, Math.min(active, shown.length - 1));
            if (!input.dataset.moved) active = current >= 0 && !terms.length ? current : 0;
            list.replaceChildren();
            let lastGroup = null;
            shown.forEach((x, i) => {
                if (x.group && x.group !== lastGroup) {
                    const g = document.createElement("div");
                    g.className = "h3-pick-group";
                    g.textContent = x.group;
                    list.append(g);
                }
                lastGroup = x.group;
                const item = document.createElement("div");
                item.className = "h3-pick-item" + (i === active ? " on" : "") + (x.o.selected ? " sel" : "") + (x.o.disabled ? " off" : "");
                item.setAttribute("role", "option");
                item.textContent = x.text || " ";
                item.title = x.text;
                item.addEventListener("mousedown", (e) => { e.preventDefault(); choose(sel, x.o); });
                item.addEventListener("mousemove", () => { if (active !== i) { active = i; input.dataset.moved = "1"; mark(); } });
                list.append(item);
            });
            count.textContent = terms.length ? `${shown.length} / ${all.length}` : `${all.length}`;
            if (!shown.length) {
                const none = document.createElement("div");
                none.className = "h3-pick-none";
                none.textContent = _t("pick.no_results");
                list.append(none);
            }
            mark(true);
        };
        const mark = (scroll) => {
            const items = list.querySelectorAll(".h3-pick-item");
            items.forEach((el, i) => el.classList.toggle("on", i === active));
            if (scroll && items[active]) items[active].scrollIntoView({ block: "nearest" });
        };
        input.addEventListener("input", () => { delete input.dataset.moved; active = 0; draw(); });
        input.addEventListener("keydown", (e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); input.dataset.moved = "1"; active = Math.min(active + 1, shown.length - 1); mark(true); }
            else if (e.key === "ArrowUp") { e.preventDefault(); input.dataset.moved = "1"; active = Math.max(active - 1, 0); mark(true); }
            else if (e.key === "PageDown") { e.preventDefault(); input.dataset.moved = "1"; active = Math.min(active + 10, shown.length - 1); mark(true); }
            else if (e.key === "PageUp") { e.preventDefault(); input.dataset.moved = "1"; active = Math.max(active - 10, 0); mark(true); }
            else if (e.key === "Enter") { e.preventDefault(); if (shown[active]) choose(sel, shown[active].o); }
            else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); close(); }
        });

        // place it under the select (or above it when there is no room below)
        const r = sel.getBoundingClientRect();
        const width = Math.min(Math.max(r.width, 280), 560, window.innerWidth - 16);
        node.style.width = width + "px";
        node.style.left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8)) + "px";
        const below = window.innerHeight - r.bottom - 10, above = r.top - 10;
        const maxH = Math.max(160, Math.min(380, Math.max(below, above)));
        list.style.maxHeight = (maxH - 40) + "px";
        if (below >= Math.min(maxH, 260) || below >= above) node.style.top = (r.bottom + 2) + "px";
        else node.style.bottom = (window.innerHeight - r.top + 2) + "px";

        pop = { sel, node };
        draw();
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        window.addEventListener("resize", close);
        document.addEventListener("scroll", onScroll, true);
    }

    document.addEventListener("mousedown", (e) => {
        if (pop && !pop.node.contains(e.target)) {
            const same = e.target === pop.sel;
            close();
            if (same) { e.preventDefault(); return; }
        }
        const sel = e.target.closest && e.target.closest("select");
        if (!eligible(sel) || e.button !== 0) return;
        e.preventDefault();
        sel.focus();
        open(sel);
    }, true);
    document.addEventListener("keydown", (e) => {
        const sel = e.target;
        if (pop || !eligible(sel) || e.ctrlKey || e.metaKey) return;
        const opener = e.key === "Enter" || e.key === " " || e.key === "F4" || (e.altKey && e.key === "ArrowDown");
        const printable = e.key.length === 1 && e.key !== " " && !e.altKey;
        if (!opener && !printable) return;
        e.preventDefault();
        open(sel, printable ? e.key : "");
    }, true);

    return { open, close, MIN_OPTIONS };
})();
