"""Builds Encore's page, web/index.html, from the sources of this folder.

    python ui/build.py          (from the Encore folder, or from anywhere)

The page is one self-contained file: the shell (editor_shell.html) with the scripts, the translations
(encore/locales) and the light theme (derived from the dark CSS by encore/theme.py) put in its placeholders.
Encore's server only adds the current language and theme when it serves it.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                        # the Encore folder
sys.path.insert(0, ROOT)
from encore import theme  # noqa: E402

# placeholder in editor_shell.html -> script (the "module.exports" line only serves the node tests)
SCRIPTS = [
    ("/*__I18N__*/", "plan_i18n.js"), ("/*__PLAN_CORE__*/", "plan_core.js"), ("/*__DIALOG__*/", "plan_dialog.js"),
    ("/*__PICK__*/", "plan_pick.js"), ("/*__SECTIONS__*/", "plan_sections.js"), ("/*__PLAN_UI__*/", "plan_ui.js"),
    ("/*__TAKES_UI__*/", "plan_takes_ui.js"), ("/*__LAUNCH__*/", "plan_launch.js"), ("/*__STUDIO__*/", "plan_studio.js"),
    ("/*__BRANCH__*/", "plan_branch.js"), ("/*__TRASH__*/", "plan_trash.js"),
]


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as handle:
        return handle.read()


def build():
    shell = read("editor_shell.html")
    css = shell[shell.index("<style>") + 7:shell.index("</style>")]
    shell = shell.replace("/*__LIGHT_CSS__*/", theme.light_css(css))
    locales = os.path.join(ROOT, "encore", "locales")
    dicts = {os.path.basename(f)[:-5]: json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(os.path.join(locales, "*.json")))}
    from encore.projects import STUDIO_VERSION
    # the version the page was built for: the page tells when the server running is another one
    shell = shell.replace("/*__I18N_EMBED__*/", "window.ENCORE_BUILD = " + json.dumps(STUDIO_VERSION) + ";\n"
                          + "window.H3I18N_EMBED = " + json.dumps({"dicts": dicts}, ensure_ascii=False) + ";")
    for placeholder, name in SCRIPTS:
        code = "\n".join(line for line in read(name).split("\n") if not line.startswith('if (typeof module !== "undefined") module.exports'))
        assert shell.count(placeholder) == 1, placeholder
        shell = shell.replace(placeholder, code)
    target = os.path.join(ROOT, "web", "index.html")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(shell)
    return target, len(shell)


if __name__ == "__main__":
    path, size = build()
    print(f"{path}: {size // 1024} KB")
