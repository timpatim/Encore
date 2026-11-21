"""Encore - localisation of the server's messages.

Texts live in encore/locales/<code>.json: {"id": "text with {name}"}. English (en.json) is the
reference; a text missing from another language is shown in English. Dropping a new <code>.json
in the folder adds a language (its "_name" key is the name shown in the settings).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
_dicts: dict = {}
_lang = "en"


def _load():
    if _dicts:
        return _dicts
    for path in sorted(LOCALES_DIR.glob("*.json")):
        try:
            _dicts[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:     # a broken file must not stop the app
            print(f"[Encore] locale {path.name} ignored: {exc}")
    return _dicts


def languages():
    """[{code, name}] for every locale file."""
    return [{"code": code, "name": d.get("_name", code)} for code, d in sorted(_load().items())]


def set_language(code):
    global _lang
    _lang = code if code in _load() else "en"
    return _lang


def language():
    return _lang


_VAR = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def t(key, default=None, **values):
    """The text of `key` in the current language (else English, else `default`, else the key)."""
    d = _load()
    text = d.get(_lang, {}).get(key)
    if text is None:
        text = d.get("en", {}).get(key)
    if text is None:
        text = default if default is not None else key
    if values:
        text = _VAR.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)
    return text


def page_script():
    """The <script> Encore puts in the page: the chosen language and every locale file."""
    data = {"lang": _lang, "dicts": _load()}
    return "<script>window.H3I18N = " + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";</script>"
