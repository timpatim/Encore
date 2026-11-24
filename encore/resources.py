"""Encore - deleting an imported file (picture, voice, song, video) of a project.

A file the project uses now (a branch's reference or song, the start video) cannot be deleted: it must be
replaced first. A file only takes were made with can be deleted after a warning (a take keeps its latent and
its preview; only its record names the file). The copy sent to ComfyUI
(its input folder) goes too, when Encore knows where ComfyUI is installed.
"""
from __future__ import annotations

import json
from pathlib import Path

from .i18n import t as _t
from . import comfy_setup, plans, previews, projects, takes
from .projects import StudioError

INPUT_DIR = "h3studio"      # same as engine.INPUT_DIR


def _resource(path: Path, rel: str) -> Path:
    if not rel or not rel.startswith("refs/") or rel.count("/") != 2 or rel.split("/")[1] not in projects.RESOURCE_KINDS:
        raise StudioError(_t("resources.not_a_resource", file=rel))
    file = projects.safe_join(path, rel)
    if not file.is_file():
        raise StudioError(_t("resources.not_found", file=rel))
    return file


def _uses(meta, plan, rel):
    """Where the current project state uses the file (texts to show)."""
    out = []
    for branch in meta.get("branches") or []:
        for ref, files in (branch.get("refs") or {}).items():
            for kind in ("image", "voice"):
                if (files or {}).get(kind) == rel:
                    out.append(_t(f"resources.used_{kind}", ref=ref, branch=branch.get("name") or branch.get("id")))
        if branch.get("song") == rel:
            out.append(_t("resources.used_song", branch=branch.get("name") or branch.get("id")))
    if meta.get("start_video_file") == rel and isinstance(plan.get("start_video"), dict):
        out.append(_t("resources.used_start_video"))
    if meta.get("start_video_file") == rel and isinstance(plan.get("edit_video"), dict):
        out.append(_t("resources.used_edit_video"))
    return out


def usage(root, name, rel):
    """{'current': [...], 'takes': number} for an imported file."""
    path = projects.project_dir(root, name)
    _resource(path, rel)
    meta = projects.read_meta(path)
    current = []
    for plan in plans.load(path)["masters"].values():
        current += [u for u in _uses(meta, plan or {}, rel) if u not in current]
    made = 0
    for folder in (path / "takes").glob("clip_*"):
        for record in folder.glob("*.json"):
            try:
                files = (json.loads(record.read_text(encoding="utf-8")).get("studio") or {}).get("files") or {}
            except (OSError, ValueError):
                continue
            if any(rel in (f or {}).values() for f in files.values()):
                made += 1
    return {"path": rel, "current": current, "takes": made}


def delete(root, name, rel, confirm=False, comfy_dir=None):
    """Delete an imported file; see the module notes. Returns the usage and what was removed."""
    path = projects.project_dir(root, name)
    file = _resource(path, rel)
    use = usage(root, name, rel)
    if use["current"]:
        raise StudioError(_t("resources.in_use", file=file.name, v1="; ".join(use["current"])), code="in_use")
    if use["takes"] and not confirm:
        return dict(use, needs_confirm=True)
    sha = takes.file_sha(file)
    file.unlink()
    previews.remove(path, rel)
    removed = []
    base = comfy_setup.comfy_root(comfy_dir)
    if base and (base / "input").is_dir():          # its copy in ComfyUI's input folder (named after its content)
        stem, ext = file.stem, file.suffix.lower()
        mark = f"{stem[:40]}_{sha[:10]}{ext}"
        candidates = list((base / "input" / INPUT_DIR / name).glob(f"*{mark}")) + list((base / "input").glob(f"{INPUT_DIR}_{name}_*{mark}"))
        for copy in candidates:
            try:
                copy.unlink()
                removed.append(copy.name)
            except OSError:
                pass
    return dict(use, deleted=rel, sha=sha, comfy_removed=removed)
