"""Encore - light theme.

The dark style sheet stays the reference. The light one is derived from it: each rule that sets a
color gets a copy under html[data-theme="light"], where every color has its lightness turned over
(dark background -> light background, light text -> dark text, same hue), then text/background
pairs are checked for contrast. The few base colors (:root variables) are set by hand.
"""
from __future__ import annotations

import colorsys
import re

LIGHT_BASE = {
    "--bg": "#f3f4f7", "--panel": "#ffffff", "--panel2": "#eceef2", "--line": "#cfd4dc",
    "--text": "#1c2028", "--muted": "#5b6271", "--accent": "#2563c9", "--err": "#c62f2f",
    "--warn": "#9a6400", "--ok": "#1f7a43", "--field": "#ffffff",
}
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")
COLOR_PROPS = re.compile(r"^(--[\w-]+|color|background(-color|-image)?|border(-[a-z]+)*|outline(-color)?|box-shadow|text-shadow|fill|stroke|caret-color|text-decoration(-color)?|accent-color)$")


def parse(c):
    c = c.strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) in (3, 4):
            h = "".join(x * 2 for x in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return r, g, b, a
    nums = [x.strip() for x in c[c.index("(") + 1:-1].split(",")]
    r, g, b = (float(x) for x in nums[:3])
    a = float(nums[3]) if len(nums) > 3 else 1.0
    return r, g, b, a


def fmt(r, g, b, a):
    r, g, b = (max(0, min(255, round(v))) for v in (r, g, b))
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r},{g},{b},{round(a, 3)})"


def luminance(r, g, b):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(c1, c2):
    l1, l2 = luminance(*c1[:3]), luminance(*c2[:3])
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def flip(c, prop=""):
    """the light-theme counterpart of a color of the dark theme"""
    r, g, b, a = parse(c)
    if a < 0.8 and r < 30 and g < 30 and b < 30:           # black shades: shadows, veils
        return fmt(0, 0, 0, a * (0.35 if "shadow" in prop else 0.6))
    if a < 0.8 and r > 225 and g > 225 and b > 225:        # white veils become dark veils
        return fmt(0, 0, 0, a)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    l2 = 1 - l
    if s > 0.35 and 0.35 < l < 0.75:                       # bright accents: keep them strong, a bit darker
        l2 = min(l2, 0.45)
    r2, g2, b2 = colorsys.hls_to_rgb(h, l2, s)
    return fmt(r2 * 255, g2 * 255, b2 * 255, a)


def flip_value(value, prop=""):
    return COLOR_RE.sub(lambda m: flip(m.group(0), prop), value)


def _split_rules(css):
    """[(selector, body)] for the flat rules of a style sheet (@keyframes and @media bodies skipped)"""
    out, i, n = [], 0, len(css)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    n = len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        sel = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        body = css[j + 1:k - 1]
        if not sel.startswith("@"):
            out.append((sel, body))
        i = k
    return out


def _decls(body):
    out = []
    for part in re.split(r";(?![^(]*\))", body):
        if ":" in part:
            p, v = part.split(":", 1)
            out.append((p.strip(), v.strip()))
    return out


def _prefix(sel):
    parts = []
    for s in sel.split(","):
        s = s.strip()
        if not s:
            continue
        if s.startswith(":root"):
            parts.append('html[data-theme="light"]' + s[5:])
        elif s == "html" or s.startswith("html "):
            parts.append('html[data-theme="light"]' + s[4:])
        else:
            parts.append('html[data-theme="light"] ' + s)
    return ", ".join(parts)


# hand-made touches after the derived rules: filled buttons stay filled
TWEAKS = """
html[data-theme="light"] button.primary, html[data-theme="light"] button.on, html[data-theme="light"] .viewtabs button.on { background: var(--accent); border-color: var(--accent); color: #ffffff; }
html[data-theme="light"] button.primary:hover:not(:disabled), html[data-theme="light"] button.on:hover:not(:disabled) { background: #1d55b0; }
"""


def light_css(css, tweaks=True):
    """the light overrides of a dark style sheet"""
    out = ['html[data-theme="light"] {' + " ".join(f"{k}: {v};" for k, v in LIGHT_BASE.items()) + " color-scheme: light; }"]
    for sel, body in _split_rules(css):
        decls = [(p, v) for p, v in _decls(body) if COLOR_PROPS.match(p) and p not in LIGHT_BASE]
        if not decls:
            continue
        flipped = {p: flip_value(v, p) for p, v in decls}
        # text on its own background: keep it readable
        fg, bg = flipped.get("color"), flipped.get("background") or flipped.get("background-color")
        if fg and bg and COLOR_RE.fullmatch(fg.strip()) and COLOR_RE.fullmatch(bg.strip()):
            fgc, bgc = parse(fg), parse(bg)
            if bgc[3] > 0.9 and contrast(fgc, bgc) < 4.5:
                orig = parse(dict(decls)["color"])
                cands = [fg, fmt(*orig), "#111418", "#ffffff"]
                flipped["color"] = max(cands, key=lambda c: contrast(parse(c), bgc))
        out.append(_prefix(sel) + " { " + " ".join(f"{p}: {v};" for p, v in flipped.items()) + " }")
    if tweaks:
        out.append(TWEAKS)
    return "\n".join(out)
