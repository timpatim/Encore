"""Encore - deleting takes and branches, and the trash of a project (chantier A, lot A3).

Nothing is erased from the disk when something is deleted: its files move into trash/<entry>/ with what is needed
to put them back (records, suites, master plan, branch settings, the clips other branches took over). An entry
is restored whole, or erased for good (one entry, or the whole trash).

    trash/<entry id>/entry.json      {"id", "kind": "take"|"branch", "label", "when", "takes": [[clip, id]],
                                      "branch": settings of a deleted branch, "master": its master plan,
                                      "suites": {take id: suite}, "exports": [file names],
                                      "bases": {branch id: [take ids taken over before]}, "kept": [take ids]}
    trash/<entry id>/takes/clip_NNN/ the files of the takes
    trash/<entry id>/exports/        the assembled videos of a deleted branch

A take is deleted with every take made after it (its predecessor chain), in any branch; a branch that took it
over (duplicated with clips) keeps the clips before it. A branch is deleted without the takes another branch
takes over: they stay, shown in that branch.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .i18n import t as _t
from . import plans, projects, takes
from .projects import StudioError

DIR = "trash"


# --------------------------------------------------------------------------- what a deletion takes away
def _known(path: Path):
    return plans.records_by_id(path)


def dependents(path: Path, take_ids, known=None):
    """The takes made after these ones (following the predecessors), these ones included: [take ids]."""
    known = _known(path) if known is None else known
    out, todo = [], list(take_ids)
    seen = set()
    children = {}
    for tid, (_i, record) in known.items():
        children.setdefault(takes.predecessor(record), []).append(tid)
    while todo:
        tid = todo.pop()
        if tid in seen or tid not in known:
            continue
        seen.add(tid)
        out.append(tid)
        todo.extend(children.get(tid, []))
    return out


def take_deletion(path: Path, take_id, known=None, meta=None):
    """What deleting a take does: {"takes": [[clip, id, branch]], "bases": {branch id: k (clips kept)}}."""
    known = _known(path) if known is None else known
    meta = meta or projects.read_meta(path)
    if take_id not in known:
        raise StudioError(_t("trash.take_missing", take_id=take_id))
    gone = dependents(path, [take_id], known)
    bases = {}
    for branch in meta["branches"]:
        base = projects.branch_base(branch)
        hit = [k for k, t in enumerate(base) if t in gone]
        if hit:
            bases[branch["id"]] = hit[0]
    items = sorted(([known[t][0], t, takes.take_branch(known[t][1], None)] for t in gone), key=lambda x: (x[0], x[1]))
    return {"takes": items, "bases": bases}


def _move_take(path: Path, entry_dir: Path, index, take_id):
    src = takes.clip_dir(path, index)
    dst = entry_dir / "takes" / f"clip_{int(index):03d}"
    dst.mkdir(parents=True, exist_ok=True)
    for file in list(src.glob(f"{take_id}.*")):
        if file.stem == take_id:
            shutil.move(str(file), str(dst / file.name))


def _new_entry(path: Path, kind, label):
    entry_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    folder = path / DIR / entry_id
    folder.mkdir(parents=True, exist_ok=True)
    return entry_id, folder, {"id": entry_id, "kind": kind, "label": label, "when": time.time(), "takes": [],
                              "suites": {}, "exports": [], "bases": {}, "kept": []}


def _write_entry(folder: Path, entry):
    (folder / "entry.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")


def _clean_selection(path: Path, gone):
    sel = takes.read_selection(path)
    if not any(v in gone for k, v in sel.items() if k != "branch"):
        return
    clean = {"branch": sel.get("branch")} if sel.get("branch") else {}
    for k in sorted(k for k in sel if k != "branch"):
        if sel[k] in gone:
            break
        clean[k] = sel[k]
    takes.write_selection(path, clean)


def delete_take(root, name, take_id, confirm=False, busy=()):
    """Deletes a take with the takes made after it (into the trash). Without confirm: what it would delete.
    busy: take ids of generations still queued or running (their take, or the one they follow)."""
    path = projects.project_dir(root, name)
    meta = projects.read_meta(path)
    known = _known(path)
    plan = take_deletion(path, take_id, known, meta)
    ids = {t for _i, t, _b in plan["takes"]}
    names = {b["id"]: b["name"] for b in meta["branches"]}
    info = {"takes": plan["takes"], "bases": {names.get(b, b): k for b, k in plan["bases"].items()},
            "count": len(ids)}
    if ids & set(busy):
        raise StudioError(_t("trash.busy"), code="busy")
    if not confirm:
        return {"needs_confirm": True, **info}
    index = known[take_id][0]
    entry_id, folder, entry = _new_entry(path, "take", _t("trash.label_take", index=index, take=take_id.split("_")[-1][:4], count=len(ids)))
    data = plans.load(path)
    for i, tid, _b in plan["takes"]:
        _move_take(path, folder, i, tid)
        entry["takes"].append([i, tid])
        if tid in data["suites"]:
            entry["suites"][tid] = data["suites"].pop(tid)
    plans.save(path, data)
    for branch in meta["branches"]:
        if branch["id"] in plan["bases"]:
            old = projects.branch_base(branch)
            entry["bases"][branch["id"]] = json.loads(json.dumps(branch["base"]))
            k = plan["bases"][branch["id"]]
            if k:
                branch["base"] = dict(branch["base"], takes=old[:k])
            else:
                branch.pop("base", None)
    projects._write_json(path / "project.json", meta)
    _write_entry(folder, entry)
    _clean_selection(path, ids)
    return {"deleted": True, "entry": entry_id, **info}


def delete_branch(root, name, branch_id, confirm=False):
    """Deletes a branch (into the trash): its takes but those another branch takes over, its master plan and its
    assembled videos."""
    path = projects.project_dir(root, name)
    meta = projects.read_meta(path)
    branch = projects.find_branch(meta["branches"], branch_id)
    taken = {t for b in meta["branches"] if b["id"] != branch_id for t in projects.branch_base(b)}
    known = _known(path)
    mine = sorted([i, tid] for tid, (i, r) in known.items() if takes.take_branch(r, None) == branch_id)
    moved = [[i, t] for i, t in mine if t not in taken]
    kept = [t for _i, t in mine if t in taken]
    videos = projects._branch_exports(path, branch_id)
    info = {"branch": branch, "delete": len(moved), "kept": len(kept), "videos": len(videos)}
    if (mine or videos) and not confirm:
        return {"needs_confirm": True, **info}
    entry_id, folder, entry = _new_entry(path, "branch", _t("trash.label_branch", name=branch["name"], count=len(moved)))
    data = plans.load(path)
    for i, tid in moved:
        _move_take(path, folder, i, tid)
        entry["takes"].append([i, tid])
        if tid in data["suites"]:
            entry["suites"][tid] = data["suites"].pop(tid)
    entry["master"] = data["masters"].pop(branch_id, None)
    plans.save(path, data)
    (folder / "exports").mkdir(exist_ok=True)
    for video in videos:
        stem = video.with_suffix("")
        for file in (video, video.with_suffix(".mp4"), Path(f"{stem}.infos.json"), Path(f"{stem}.infos.md")):
            if file.is_file():
                shutil.move(str(file), str(folder / "exports" / file.name))
                entry["exports"].append(file.name)
    entry["branch"] = {k: v for k, v in branch.items() if k != "song"}
    entry["kept"] = kept
    meta["branch_seq"] = max(int(meta.get("branch_seq") or 0), projects.next_branch_number(path, meta) - 1)
    meta["branches"] = [b for b in meta["branches"] if b["id"] != branch_id]
    projects._write_json(path / "project.json", meta)
    _write_entry(folder, entry)
    if takes.read_selection(path).get("branch") == branch_id:
        takes.write_selection(path, {})
    _clean_selection(path, {t for _i, t in moved})
    return {"deleted": True, "entry": entry_id, **info}


def replace_master(path: Path, branch_id, plan, label):
    """A branch gets another master plan; the one it had goes to the trash (restoring it swaps them back)."""
    data = plans.load(path)
    entry_id, folder, entry = _new_entry(path, "master", label)
    entry["master"] = data["masters"].get(branch_id)
    entry["master_of"] = branch_id
    data["masters"][branch_id] = plan
    plans.save(path, data)
    _write_entry(folder, entry)
    return entry_id


# --------------------------------------------------------------------------- the trash
def _entries(path: Path):
    out = []
    for folder in sorted((path / DIR).glob("*"), reverse=True):
        try:
            out.append((folder, json.loads((folder / "entry.json").read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def listing(root, name):
    path = projects.project_dir(root, name)
    return {"entries": [{k: e.get(k) for k in ("id", "kind", "label", "when")}
                        | {"takes": len(e.get("takes") or []), "videos": len(e.get("exports") or []),
                           "branch": (e.get("branch") or {}).get("name")}
                        for _f, e in _entries(path)]}


def _entry(path: Path, entry_id):
    for folder, e in _entries(path):
        if e.get("id") == entry_id:
            return folder, e
    raise StudioError(_t("trash.entry_missing"))


def restore(root, name, entry_id):
    """Puts an entry back: its takes (with their suites), a branch with its master plan and videos, the clips other
    branches took over. Refused when a take it needs is not there (restore the entry holding it first)."""
    path = projects.project_dir(root, name)
    folder, entry = _entry(path, entry_id)
    meta = projects.read_meta(path)
    if entry.get("kind") == "master":
        # a master plan replaced: it comes back, the one in its place goes to the trash
        branch = next((b for b in meta["branches"] if b["id"] == entry.get("master_of")), None)
        if not branch:
            raise StudioError(_t("trash.branch_first"))
        shutil.rmtree(folder, ignore_errors=True)
        replace_master(path, branch["id"], entry.get("master"), _t("trash.label_master", name=branch["name"]))
        return {"restored": entry_id, "project": projects.read_project(root, name)}
    known = _known(path)
    restored = {t for _i, t in entry.get("takes") or []}
    # every take put back follows a take that is there (or put back with it)
    for index, tid in entry.get("takes") or []:
        try:
            record = json.loads((folder / "takes" / f"clip_{int(index):03d}" / f"{tid}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pred = takes.predecessor(record)
        if pred and pred not in known and pred not in restored:
            raise StudioError(_t("trash.needs_first", take=pred.split("_")[-1][:4], index=int(index) - 1))
        owner = takes.take_branch(record, None)
        alive = {b["id"] for b in meta["branches"]} | ({entry["branch"]["id"]} if entry.get("kind") == "branch" and entry.get("branch") else set())
        if entry.get("kind") == "take" and owner not in alive:
            raise StudioError(_t("trash.branch_first"))
    if entry.get("kind") == "branch" and entry.get("branch"):
        if any(b["id"] == entry["branch"]["id"] for b in meta["branches"]):
            raise StudioError(_t("trash.branch_exists"))
    for index, tid in entry.get("takes") or []:
        src = folder / "takes" / f"clip_{int(index):03d}"
        dst = takes.clip_dir(path, index)
        dst.mkdir(parents=True, exist_ok=True)
        for file in list(src.glob(f"{tid}.*")):
            if file.stem == tid:
                shutil.move(str(file), str(dst / file.name))
    data = plans.load(path)
    data["suites"].update(entry.get("suites") or {})
    if entry.get("kind") == "branch" and entry.get("branch"):
        branch = entry["branch"]
        meta["branches"].append(branch)
        if entry.get("master"):
            data["masters"][branch["id"]] = entry["master"]
        for file in entry.get("exports") or []:
            src = folder / "exports" / file
            if src.is_file():
                shutil.move(str(src), str(path / "exports" / file))
    plans.save(path, data)
    for branch in meta["branches"]:
        if branch["id"] in (entry.get("bases") or {}):
            branch["base"] = entry["bases"][branch["id"]]
    projects._write_json(path / "project.json", meta)
    shutil.rmtree(folder, ignore_errors=True)
    return {"restored": entry_id, "project": projects.read_project(root, name)}


def erase(root, name, entry_id=None):
    """Erases one entry for good, or the whole trash (entry_id None)."""
    path = projects.project_dir(root, name)
    if entry_id:
        folder, _e = _entry(path, entry_id)
        shutil.rmtree(folder, ignore_errors=True)
    else:
        for folder, _e in _entries(path):
            shutil.rmtree(folder, ignore_errors=True)
    return listing(root, name)
