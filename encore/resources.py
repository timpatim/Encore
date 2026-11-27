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


def _plan_uses(plan, rel, where):
    """The files of a plan (its own and the 'defs' of its clips) whose path is rel: texts to show."""
    out = []
    tables = [(plan or {}).get("files") or {}]
    tables += [((c.get("defs") or {}).get("files") or {}) for c in (plan or {}).get("clips") or [] if isinstance(c, dict)
               and isinstance(c.get("defs"), dict)]
    for table in tables:
        for ref, item in table.items():
            if isinstance(item, dict) and item.get("file") == rel and item.get("kind") in ("image", "voice"):
                text = _t(f"resources.used_{item['kind']}", ref=ref, branch=where)
                if text not in out:
                    out.append(text)
    return out


def _uses(meta, plan, rel):
    """Where the current project state uses the file outside of the plans' files (texts to show)."""
    out = []
    if meta.get("song") == rel:
        out.append(_t("resources.used_song", branch=meta.get("name") or ""))
    if meta.get("start_video_file") == rel and isinstance(plan.get("start_video"), dict):
        out.append(_t("resources.used_start_video"))
    if meta.get("start_video_file") == rel and isinstance(plan.get("edit_video"), dict):
        out.append(_t("resources.used_edit_video"))
    return out


def _scan(path: Path, busy=None):
    """What uses the project's files now: (current, made) where current(rel) lists the texts of where the current
    state uses it (plans, the project's song and video, generations waiting: `busy`, paths they need) and made(rel)
    counts the takes made with it."""
    meta = projects.read_meta(path)
    names = {b["id"]: b.get("name") or b["id"] for b in meta.get("branches") or []}
    data = plans.load(path)
    known = plans.records_by_id(path)
    places = [(plan or {}, names.get(branch_id, branch_id), True) for branch_id, plan in data["masters"].items()]
    for take_id, item in data["suites"].items():         # what comes after a take: still editable
        branch_id = plans.branch_of((known.get(take_id) or (None, {}))[1])
        places.append((item.get("plan") or {}, names.get(branch_id, branch_id or "?"), False))
    records = []
    for folder in (path / "takes").glob("clip_*"):
        for record in folder.glob("*.json"):
            try:
                files = (json.loads(record.read_text(encoding="utf-8")).get("studio") or {}).get("files") or {}
            except (OSError, ValueError):
                continue
            records.append({v for f in files.values() for v in (f or {}).values() if v})

    def current(rel):
        out = []
        for plan, where, master in places:
            found = (_uses(meta, plan, rel) if master else []) + _plan_uses(plan, rel, where)
            out += [u for u in found if u not in out]
        if busy and rel in busy:
            out.append(_t("resources.used_by_waiting"))
        return out

    def made(rel):
        return sum(1 for used in records if rel in used)
    return current, made


def usage(root, name, rel, busy=None):
    """{'current': [...], 'takes': number} for an imported file."""
    path = projects.project_dir(root, name)
    _resource(path, rel)
    current, made = _scan(path, busy)
    return {"path": rel, "current": current(rel), "takes": made(rel)}


def usages(root, name, busy=None):
    """{path: {"state": "used" | "takes" | "unused", "current": [...], "takes": n}} for every imported file: what the
    Resources window shows."""
    path = projects.project_dir(root, name)
    current, made = _scan(path, busy)
    out = {}
    for items in projects.list_resources(root, name).values():
        for item in items:
            rel = item["path"]
            now, count = current(rel), made(rel)
            out[rel] = {"state": "used" if now else "takes" if count else "unused", "current": now, "takes": count}
    return out


def delete_unused(root, name, paths, busy=None, comfy_dir=None):
    """Deletes the files of `paths` that nothing uses (no plan, no take, no generation waiting); the others are
    left. Returns {"deleted": [paths], "kept": [paths]}."""
    use = usages(root, name, busy)
    deleted, kept = [], []
    for rel in paths:
        if (use.get(rel) or {}).get("state") == "unused":
            delete(root, name, rel, comfy_dir=comfy_dir, busy=busy)
            deleted.append(rel)
        else:
            kept.append(rel)
    return {"deleted": deleted, "kept": kept}


def delete(root, name, rel, confirm=False, comfy_dir=None, busy=None):
    """Delete an imported file; see the module notes. Returns the usage and what was removed."""
    path = projects.project_dir(root, name)
    file = _resource(path, rel)
    use = usage(root, name, rel, busy)
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
