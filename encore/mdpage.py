"""A small Markdown to HTML page converter for the video information files (.infos.md).

It covers what the Studio writes: headings, bullet lists, tables, fenced code blocks, paragraphs,
`code` and **bold**. The page looks like a README on GitHub and follows the light / dark setting."""
import html
import re

from . import i18n, theme
from .i18n import t as _t

CSS = """
:root { --bg:#15171c; --panel:#1d2027; --panel2:#252932; --line:#333845; --text:#e4e6eb; --muted:#969cab;
        --accent:#6aa7ff; --field:#12141a; --mono: ui-monospace, "Cascadia Mono", Consolas, monospace; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 13.5px/1.55 system-ui, "Segoe UI", sans-serif; }
.top { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 10px; padding: 7px 16px;
       background: #101216; border-bottom: 1px solid var(--line); }
.top .app { font-weight: 700; letter-spacing: .02em; }
.top .what { color: var(--muted); }
.top .spacer { flex: 1; }
.top a { color: var(--text); text-decoration: none; background: var(--panel2); border: 1px solid var(--line); border-radius: 5px; padding: 3px 9px; font-size: 12.5px; }
.top a:hover { border-color: var(--accent); }
main { max-width: 1320px; margin: 0 auto; padding: 18px 20px 48px; }
h1 { font-size: 20px; margin: 4px 0 12px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 22px 0 10px; font-weight: 600; }
h3 { font-size: 14.5px; margin: 0 0 8px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex: none; }
p, ul, pre { margin: 0 0 10px; }
ul { padding-left: 1.3em; }
li { margin: 2px 0; }
li::marker { color: var(--muted); }
.summary { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px 4px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px 4px; margin-bottom: 12px; }
code { font-family: var(--mono); font-size: 12px; background: var(--field); border: 1px solid var(--line); padding: 0 5px; border-radius: 4px; }
pre { background: var(--field); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; overflow: auto; max-height: 420px; }
pre code { background: none; border: none; padding: 0; font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; color: #cfd5e0; }
.table { overflow: auto; margin-bottom: 10px; border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: 6px 10px; vertical-align: top; white-space: nowrap; text-align: left; }
th { font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; background: var(--panel2); position: sticky; top: 0; }
td { background: var(--panel); }
tr:nth-child(2n) td { background: #212530; }
tr:hover td { background: #2a3040; }
tr:last-child td { border-bottom: none; }
"""


def _inline(text):
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, current, escaped = [], "", False
    for ch in line:
        if escaped:
            current += ch
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += ch
    cells.append(current.strip())
    return cells


def to_html(markdown):
    lines = markdown.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            body = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(body), quote=False)}</code></pre>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[i + 1]):
            head = _cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append('<div class="table"><table><thead><tr>' + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(t)}</li>" for t in items) + "</ul>")
            continue
        if not line.strip():
            i += 1
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|```|\||\s*[-*]\s)", lines[i]):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def _cards(body, color):
    """The list under the title becomes a summary panel; each clip (### section) a card."""
    dot = f'<i class="dot" style="background:{html.escape(color)}"></i>' if color else ""
    body = re.sub(r"<h1>(.*?)</h1>\n<ul>(.*?)</ul>", lambda m: f"<h1>{dot}{m.group(1)}</h1>\n<div class=\"summary\"><ul>{m.group(2)}</ul></div>",
                  body, count=1, flags=re.S)
    parts = re.split(r"(?=<h[23]>)", body)
    out = []
    for part in parts:
        if part.startswith("<h3>"):
            out.append('<section class="card">' + part.replace("<h3>", "<h3>" + dot, 1) + "</section>")
        else:
            out.append(part)
    return "".join(out)


LIGHT_CSS = theme.light_css(CSS, tweaks=False)
THEME = ["dark"]      # set by the server from config.json


def page(markdown, title, source_url=None, json_url=None, color=None):
    links = "".join(f'<a href="{html.escape(u)}" target="_blank">{label}</a>'
                    for label, u in (("source .md", source_url), (_t("mdpage.json_details"), json_url)) if u)
    return (f"<!DOCTYPE html><html lang=\"{i18n.language()}\" data-theme=\"{THEME[0]}\"><head><meta charset=\"utf-8\"><title>{html.escape(title)} · infos</title>"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><style>{CSS}\n{LIGHT_CSS}</style></head>"
            f"<body><div class=\"top\"><span class=\"app\">Encore</span><span class=\"what\">{_t('mdpage.video_info')}</span>"
            f"<span class=\"spacer\"></span>{links}</div><main>{_cards(to_html(markdown), color)}</main></body></html>")
