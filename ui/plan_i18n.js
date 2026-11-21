// ---------------------------------------------------------------------------------------------
// Localisation. Texts live in locale files (encore/locales/<code>.json): { "id": "text with {name}" }.
// Encore puts the chosen language and every locale file of its folder in window.H3I18N when it
// serves the page; the build also embeds English and French (window.H3I18N_EMBED) as a fallback.
// _t(id, {name: value}) → the text in the current language, else in English, else the id.
// ---------------------------------------------------------------------------------------------
const H3I18n = (() => {
    const served = (typeof window !== "undefined" && window.H3I18N) || null;
    const embed = (typeof window !== "undefined" && window.H3I18N_EMBED) || { dicts: {} };
    const dicts = Object.assign({}, embed.dicts || {}, (served && served.dicts) || {});
    let stored = null;
    try { stored = localStorage.getItem("encore.lang"); } catch (_) { /* no storage */ }
    const browser = typeof navigator !== "undefined" ? String(navigator.language || "en").slice(0, 2) : "en";
    let lang = (served && served.lang) || stored || (dicts[browser] ? browser : "en");
    if (!dicts[lang]) lang = "en";
    const en = dicts.en || {};
    let cur = dicts[lang] || en;

    function t(id, vars) {
        let text = cur[id];
        if (text === undefined) text = en[id];
        if (text === undefined) return id;
        if (vars) text = text.replace(/\{([A-Za-z_$][\w$]*)\}/g, (m, k) => (k in vars ? String(vars[k] ?? "") : m));
        return text;
    }
    // static markup: data-t="id" (text), data-t-title / data-t-placeholder (attributes)
    function translateDom(root) {
        if (typeof document === "undefined") return;
        for (const el of (root || document).querySelectorAll("[data-t]")) el.textContent = t(el.dataset.t);
        for (const el of (root || document).querySelectorAll("[data-t-title]")) el.title = t(el.dataset.tTitle);
        for (const el of (root || document).querySelectorAll("[data-t-placeholder]")) el.placeholder = t(el.dataset.tPlaceholder);
    }
    // the languages offered: every locale file, by its own name ("_name" key)
    const languages = () => Object.keys(dicts).sort().map((code) => ({ code, name: (dicts[code] || {})._name || code }));
    function setLang(code) {
        try { localStorage.setItem("encore.lang", code); } catch (_) { /* ignore */ }
    }
    if (typeof document !== "undefined") {
        document.documentElement.lang = lang;
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => translateDom());
        else translateDom();
    }
    const decimal = () => t("_decimal") === "_decimal" ? "." : t("_decimal");
    return { t, lang: () => lang, languages, setLang, translateDom, decimal };
})();
const _t = H3I18n.t;
if (typeof module !== "undefined") module.exports = H3I18n;

// ---------------------------------------------------------------------------------------------
// Theme: "dark" (reference) or "light". The light style sheet is derived from the dark one at build
// time (encore/theme.py); H3Theme.c() gives the light counterpart of a color drawn by script.
// ---------------------------------------------------------------------------------------------
const H3Theme = (() => {
    const get = () => (typeof document !== "undefined" && document.documentElement.dataset.theme) || "dark";
    function parse(c) {
        if (c[0] === "#") {
            let x = c.slice(1);
            if (x.length <= 4) x = [...x].map((ch) => ch + ch).join("");
            return [parseInt(x.slice(0, 2), 16), parseInt(x.slice(2, 4), 16), parseInt(x.slice(4, 6), 16), x.length === 8 ? parseInt(x.slice(6, 8), 16) / 255 : 1];
        }
        const n = c.slice(c.indexOf("(") + 1, -1).split(",").map(Number);
        return [n[0], n[1], n[2], n.length > 3 ? n[3] : 1];
    }
    const hex = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
    function fmt(r, g, b, a) { return a >= 0.999 ? `#${hex(r)}${hex(g)}${hex(b)}` : `rgba(${Math.round(r)},${Math.round(g)},${Math.round(b)},${+a.toFixed(3)})`; }
    function flip(c) {
        const [r, g, b, a] = parse(c);
        if (a < 0.8 && r < 30 && g < 30 && b < 30) return fmt(0, 0, 0, a * 0.6);
        if (a < 0.8 && r > 225 && g > 225 && b > 225) return fmt(0, 0, 0, a);
        const R = r / 255, G = g / 255, B = b / 255, mx = Math.max(R, G, B), mn = Math.min(R, G, B);
        let h = 0, s = 0; const l = (mx + mn) / 2;
        if (mx !== mn) {
            const d = mx - mn;
            s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
            h = mx === R ? (G - B) / d + (G < B ? 6 : 0) : mx === G ? (B - R) / d + 2 : (R - G) / d + 4;
            h /= 6;
        }
        let l2 = 1 - l;
        if (s > 0.35 && l > 0.35 && l < 0.75) l2 = Math.min(l2, 0.45);
        const q = l2 < 0.5 ? l2 * (1 + s) : l2 + s - l2 * s, p = 2 * l2 - q;
        const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
        return s === 0 ? fmt(l2 * 255, l2 * 255, l2 * 255, a) : fmt(f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255, a);
    }
    const c = (color) => (get() === "light" ? flip(color) : color);
    function set(theme) {
        document.documentElement.dataset.theme = theme;
        try { localStorage.setItem("encore.theme", theme); } catch (_) { /* ignore */ }
        document.dispatchEvent(new CustomEvent("h3theme", { detail: theme }));
    }
    return { get, set, c, flip };
})();
