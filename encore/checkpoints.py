"""Encore - checkpoints: the state of a project, to come back to it later.

A checkpoint is a small file, checkpoints/<id>.json. Files that change (plan, settings, branches,
selection) are copied into it; takes and imported files never change and are never deleted, so the
checkpoint only lists the takes that were visible. Restoring a checkpoint puts the plan, settings,
branches and selection back, and hides the takes made since (they stay on disk: the checkpoint
created automatically before the restoration shows them again).
"""
from __future__ import annotations

from .i18n import t as _t
import json
import os
import time
import uuid
from pathlib import Path

from . import projects, takes
from .projects import StudioError

KEPT_KEYS = ("settings", "branches", "start_video_file")


def _dir(path: Path) -> Path:
    folder = path / "checkpoints"
    folder.mkdir(exist_ok=True)
    return folder


def _write(file: Path, data):
    tmp = file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, file)


def _summary(cp):
    state = cp.get("state") or {}
    clips = len((state.get("plan") or {}).get("clips") or [])
    return {k: cp.get(k) for k in ("id", "name", "created", "kind", "reason")} | {
        "takes": len(state.get("takes") or []), "branches": len((state.get("meta") or {}).get("branches") or []), "clips": clips}


def list_checkpoints(root, name):
    path = projects.project_dir(root, name)
    out = []
    for file in _dir(path).glob("cp_*.json"):
        try:
            out.append(_summary(json.loads(file.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    out.sort(key=lambda c: c.get("created") or 0, reverse=True)
    return {"checkpoints": out}


def create(root, name, label="", kind="manual", reason="", limit=0, selection=None):
    path = projects.project_dir(root, name)
    meta = projects.read_meta(path)
    plan = json.loads((path / "plan.json").read_text(encoding="utf-8-sig"))
    hidden = takes.hidden_takes(path)
    visible = [[i, t] for i, t in takes.all_take_ids(path) if t not in hidden]
    now = time.time()
    cp = {"id": time.strftime("cp_%Y%m%d_%H%M%S_", time.localtime(now)) + uuid.uuid4().hex[:4], "created": now,
          "name": (str(label or "").strip() or time.strftime(_t("checkpoints.checkpoint_m_d_h_m"), time.localtime(now)))[:80],
          "kind": kind, "reason": reason, "studio_version": projects.STUDIO_VERSION,
          "state": {"plan": plan, "meta": {k: meta.get(k) for k in KEPT_KEYS},
                    "selection": takes.read_selection(path) if selection is None else selection, "takes": visible}}
    cp["state"]["selection"] = {str(k): v for k, v in cp["state"]["selection"].items()}
    _write(_dir(path) / f"{cp['id']}.json", cp)
    if kind == "auto" and limit and int(limit) > 0:
        autos = [c for c in list_checkpoints(root, name)["checkpoints"] if c["kind"] == "auto"]
        for old in autos[int(limit):]:          # newest first: the oldest automatic ones go
            try:
                (_dir(path) / f"{old['id']}.json").unlink()
            except OSError:
                pass
        collect_garbage(path)
    return _summary(cp)


def referenced_takes(path: Path):
    """Ids of the takes listed by at least one checkpoint."""
    out = set()
    for file in _dir(path).glob("cp_*.json"):
        try:
            cp = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None          # a checkpoint that cannot be read: delete nothing
        out.update(t for _i, t in (cp.get("state") or {}).get("takes") or [])
    return out


def branches_in_checkpoints(path: Path):
    """{branch id: number of checkpoints holding it}."""
    out = {}
    for file in _dir(path).glob("cp_*.json"):
        try:
            cp = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for b in ((cp.get("state") or {}).get("meta") or {}).get("branches") or []:
            out[b.get("id")] = out.get(b.get("id"), 0) + 1
    return out


def delete_take_files(path: Path, index: int, take_id: str):
    folder = takes.clip_dir(path, index)
    for file in folder.glob(f"{take_id}.*"):
        try:
            file.unlink()
        except OSError:
            pass


def _branch_exports(path: Path, branch_id):
    out = []
    for meta in (path / "exports").glob("*.json"):
        if meta.name.endswith(".infos.json"):
            continue
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("branch") == branch_id:
                out.append(meta)
        except (OSError, ValueError):
            continue
    return out


def _delete_export(meta: Path):
    stem = meta.with_suffix("")
    for file in (meta, meta.with_suffix(".mp4"), Path(f"{stem}.infos.json"), Path(f"{stem}.infos.md")):
        try:
            file.unlink()
        except OSError:
            pass


def collect_garbage(path: Path):
    """Hidden takes that no checkpoint lists any more can never come back: their files are deleted;
    so are the assembled videos of a deleted branch that no checkpoint holds any more."""
    current = {b["id"] for b in projects.read_meta(path)["branches"]}
    held = branches_in_checkpoints(path)
    for meta in (path / "exports").glob("*.json"):
        if meta.name.endswith(".infos.json"):
            continue
        try:
            branch = json.loads(meta.read_text(encoding="utf-8")).get("branch")
        except (OSError, ValueError):
            continue
        if branch and branch not in current and not held.get(branch):
            _delete_export(meta)
    hidden = takes.hidden_takes(path)
    if not hidden:
        return 0
    referenced = referenced_takes(path)
    if referenced is None:
        return 0
    dead = [(i, t) for i, t in takes.all_take_ids(path) if t in hidden and t not in referenced]
    for i, t in dead:
        delete_take_files(path, i, t)
    if dead:
        takes.write_hidden_takes(path, hidden - {t for _i, t in dead})
    return len(dead)


def delete_branch(root, name, branch_id, confirm=False):
    """Remove a branch. Its takes listed by a checkpoint stay on disk (hidden: restoring the checkpoint
    brings them back); the others are deleted, after confirmation."""
    path = projects.project_dir(root, name)
    meta = projects.read_meta(path)
    branch = projects.find_branch(meta["branches"], branch_id)
    default = meta["branches"][0]["id"]
    referenced = referenced_takes(path)
    if referenced is None:
        raise StudioError(_t("checkpoints.a_checkpoint_is_unreadable_cannot_delete"))
    mine, unmarked = [], []
    for index, take_id in takes.all_take_ids(path):
        file = takes.clip_dir(path, index) / f"{take_id}.json"
        try:
            record = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (record.get("studio") or {}).get("branch"):
            unmarked.append((file, record))
        if takes.take_branch(record, default) == branch_id:
            mine.append((index, take_id))
    doomed = [(i, t) for i, t in mine if t not in referenced]
    kept = [(i, t) for i, t in mine if t in referenced]
    checkpoints = branches_in_checkpoints(path).get(branch_id, 0)
    videos = _branch_exports(path, branch_id)
    doomed_videos = videos if not checkpoints else []      # kept (hidden) while a checkpoint holds the branch
    info = {"branch": branch, "delete": len(doomed), "keep": len(kept), "checkpoints": checkpoints,
            "videos": len(videos), "delete_videos": len(doomed_videos)}
    if (doomed or doomed_videos) and not confirm:
        return {"needs_confirm": True, **info}
    # takes made before branches had ids belong to the first branch: write it down before it changes
    for file, record in unmarked:
        record.setdefault("studio", {})["branch"] = default
        tmp = file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, file)
    for i, t in doomed:
        delete_take_files(path, i, t)
    for video in doomed_videos:
        _delete_export(video)
    hidden = takes.hidden_takes(path) - {t for _i, t in doomed}
    takes.write_hidden_takes(path, hidden | {t for _i, t in kept})
    meta["branch_seq"] = max(int(meta.get("branch_seq") or 0), projects.next_branch_number(path, meta) - 1)
    meta["branches"] = [b for b in meta["branches"] if b["id"] != branch_id]
    projects._write_json(path / "project.json", meta)
    selection = takes.read_selection(path)
    if selection.get("branch") == branch_id or any(t in {x for _i, x in mine} for k, t in selection.items() if k != "branch"):
        takes.write_selection(path, {})
    return {"deleted": True, **info, "project": projects.read_project(root, name)}


def _read(path: Path, cp_id):
    file = _dir(path) / f"{cp_id}.json"
    if not cp_id.startswith("cp_") or "/" in cp_id or "\\" in cp_id or not file.is_file():
        raise StudioError(_t("checkpoints.checkpoint_not_found"))
    return file, json.loads(file.read_text(encoding="utf-8"))


def rename(root, name, cp_id, label):
    path = projects.project_dir(root, name)
    file, cp = _read(path, cp_id)
    label = str(label or "").strip()
    if not label:
        raise StudioError(_t("checkpoints.empty_name"))
    cp["name"] = label[:80]
    _write(file, cp)
    return _summary(cp)


def restore(root, name, cp_id, limit=0):
    """Back to a checkpoint; the current state is saved first as an automatic checkpoint."""
    path = projects.project_dir(root, name)
    _file, cp = _read(path, cp_id)
    before = create(root, name, kind="auto", reason=_t("checkpoints.before_restoring", v0=cp['name']), limit=limit)
    state = cp["state"]
    # plan, settings and branches
    plan = {k: v for k, v in state["plan"].items() if k != "ref_image_size"}   # a branch setting since 0.7
    (path / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meta = projects.read_meta(path)
    for key in KEPT_KEYS:
        if key in state["meta"]:
            meta[key] = state["meta"][key]
    projects._write_json(path / "project.json", meta)
    # takes: those of the checkpoint visible, every other one hidden
    visible = {t for _i, t in state["takes"]}
    takes.write_hidden_takes(path, [t for _i, t in takes.all_take_ids(path) if t not in visible])
    selection = {("branch" if k == "branch" else int(k)): v for k, v in (state.get("selection") or {}).items()}
    takes.write_selection(path, selection)
    return {"restored": _summary(cp), "saved_before": before}
