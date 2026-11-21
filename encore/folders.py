"""Encore - choosing a folder on this PC: what the folder browser of the page shows."""
from __future__ import annotations

from .i18n import t as _t
import os
import string
from pathlib import Path

from .projects import StudioError

def roots():
    if os.name == "nt":
        drives = [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
    else:
        drives = ["/"]
    home = Path.home()
    places = [{"label": _t("folders.home_folder"), "path": str(home)}]
    for name in ("Documents", "Desktop", "Bureau", "Videos", "Vidéos"):
        if (home / name).is_dir():
            places.append({"label": name, "path": str(home / name)})
    return [{"label": d, "path": d} for d in drives], places


def list_dirs(path: str = ""):
    drives, places = roots()
    if not path:
        return {"path": "", "parent": None, "dirs": [], "drives": drives, "places": places}
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise StudioError(_t("folders.folder_not_found", folder=folder))
    try:
        names = sorted((e.name for e in os.scandir(folder) if e.is_dir(follow_symlinks=True)
                        and not e.name.startswith((".", "$")) and e.name not in ("System Volume Information",)), key=str.lower)
    except PermissionError as exc:
        raise StudioError(_t("folders.access_denied", folder=folder)) from exc
    parent = folder.parent
    return {"path": str(folder), "parent": str(parent) if parent != folder else "", "dirs": names,
            "drives": drives, "places": places}


def make_dir(path: str, name: str):
    name = str(name or "").strip()
    if not name or any(c in name for c in '\\/:*?"<>|') or name in (".", ".."):
        raise StudioError(_t("folders.invalid_folder_name"))
    target = Path(path) / name
    try:
        target.mkdir(parents=False, exist_ok=True)
    except OSError as exc:
        raise StudioError(_t("folders.cannot_create", target=target, exc=exc)) from exc
    return list_dirs(str(target))
