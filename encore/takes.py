"""Encore - the takes of a project, stored in the project folder.

    takes/clip_NNN/<take id>.pt     latent (H3 audio-video latent, as saved by the plugin)
    takes/clip_NNN/<take id>.json   signature written by the plugin, plus a "studio" part
    takes/clip_NNN/<take id>.mp4    preview
    selection.json                  the selected twig: the take chosen for clips 1..k, a chain of predecessors

The "studio" part of a signature records what Encore sent: the project files used for each reference (with
their SHA-256), the picture size, the models, the portion of plan the take was made with (studio.portion) and
the take before it in time (studio.predecessor). A take never changes once made: nothing makes it invalid.
"""
from __future__ import annotations

from .i18n import t as _t
import hashlib
import json
import os
import re
from pathlib import Path

TAKE_ID_RE = re.compile(r"^s\d+_[0-9a-f]{8}$")
_SHA_CACHE = {}


def file_sha(path: Path) -> str:
    """SHA-256 of a file (cached by path, size and date)."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _SHA_CACHE:
        sha = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
        _SHA_CACHE[key] = sha.hexdigest()
    return _SHA_CACHE[key]


def clip_dir(project: Path, index: int) -> Path:
    return project / "takes" / f"clip_{int(index):03d}"


def take_files(project: Path, index: int, take_id: str):
    base = clip_dir(project, index) / take_id
    return base.with_suffix(".pt"), base.with_suffix(".json"), base.with_suffix(".mp4")


def all_take_ids(project: Path):
    """[(clip index, take id)] of every take on disk."""
    out = []
    for folder in sorted((project / "takes").glob("clip_*")):
        if not folder.is_dir() or not folder.name[5:].isdigit():
            continue
        for meta in sorted(folder.glob("*.json")):
            if TAKE_ID_RE.match(meta.stem) and meta.with_suffix(".pt").is_file():
                out.append((int(folder.name[5:]), meta.stem))
    return out


def list_takes(project: Path, plan=None):
    """{clip index: [record with "id"]} of every take on disk. plan: ignored (kept for the callers of
    earlier versions)."""
    out = {}
    for folder in sorted((project / "takes").glob("clip_*")):
        if not folder.is_dir() or not folder.name[5:].isdigit():
            continue
        records = []
        for meta in sorted(folder.glob("*.json")):
            take_id = meta.stem
            if not TAKE_ID_RE.match(take_id) or not meta.with_suffix(".pt").is_file():
                continue
            try:
                record = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            record["id"] = take_id
            records.append(record)
        out[int(folder.name[5:])] = records
    return out


def read_selection(project: Path):
    """{clip index: take id, "branch": branch id (optional)}."""
    try:
        data = json.loads((project / "selection.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {int(k): v for k, v in data.items() if v and k != "branch" and str(k).isdigit()}
    if data.get("branch"):
        out["branch"] = str(data["branch"])
    return out


def write_selection(project: Path, selection):
    path = project / "selection.json"
    data = {str(k): v for k, v in sorted((int(a), b) for a, b in selection.items() if b and a != "branch")}
    if selection.get("branch"):
        data = {"branch": selection["branch"], **data}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _records_by_id(project: Path):
    return {r["id"]: (i, r) for i, records in list_takes(project).items() for r in records}


def predecessor(record):
    """The take before this one in time: the take it continues, or the one it was timed after (new scene)."""
    studio = (record or {}).get("studio") or {}
    return studio.get("predecessor") or (record or {}).get("parent")


def listing(project: Path, names=None):
    """What the Takes screen shows: every take (with its record and preview), by clip, and the selection.
    names: {clip index: name} for the column headers (from the selected twig's plan); the clips listed go
    up to the last clip with a take or a name."""
    by_clip = list_takes(project)
    selection = read_selection(project)
    names = names or {}
    last = max([0] + [i for i, records in by_clip.items() if records] + [int(i) for i in names])
    clips = []
    for index in range(1, last + 1):
        items = []
        for record in sorted(by_clip.get(index, []), key=lambda r: r.get("saved_at", 0)):
            _pt, _js, mp4 = take_files(project, index, record["id"])
            preview = {"subfolder": f"takes/clip_{index:03d}", "filename": mp4.name} if mp4.is_file() else None
            items.append({"id": record["id"], "record": record, "preview": preview,
                          "predecessor": predecessor(record), "branch": take_branch(record, None)})
        clips.append({"index": index, "name": names.get(index) or f"clip_{index:03d}", "takes": items,
                      "selected": selection.get(index)})
    return {"project": project.name, "clips": clips, "selection_branch": selection.get("branch")}


def follows(take_id, record, prev_id, fits=None):
    """True when a take can come right after prev_id in a twig: it was made after it, or it is a new scene that
    fits there (fits: {take id: [take ids]}, plans.fits_map)."""
    return predecessor(record) == prev_id or prev_id in ((fits or {}).get(take_id) or ())


def select_chain(project: Path, plan_raw, index: int, take_id: str, branch=None, fits=None):
    """Choose a take: the selection becomes the twig through it. Its predecessors are chosen (at a new scene that
    fits after the take already chosen before it, that one stays); the takes chosen after it stay chosen when they
    follow it, the others are dropped. A take of another branch switches the selection to that branch.
    plan_raw: ignored (kept for the callers of earlier versions). fits: plans.fits_map."""
    known = _records_by_id(project)
    if take_id not in known or known[take_id][0] != index:
        raise ValueError(_t("takes.clip_has_no_take", index=index, take_id=take_id))
    old = read_selection(project)
    branch = branch or take_branch(known[take_id][1], old.get("branch"))
    same = old.get("branch") in (None, branch)
    selection = {"branch": branch} if branch else {}
    # before: the predecessors
    cur, i = take_id, index
    while cur and cur in known:
        selection[i] = cur
        prev = predecessor(known[cur][1])
        alt = old.get(i - 1) if same else None
        if alt and alt != prev and alt in known and follows(cur, known[cur][1], alt, fits):
            prev = alt
        cur, i = prev, i - 1
    # after: kept while each one follows the one before
    i, prev = index + 1, take_id
    while same and old.get(i) in known and follows(old[i], known[old[i]][1], prev, fits):
        selection[i] = prev = old[i]
        i += 1
    write_selection(project, selection)
    return selection


def save_selection(project: Path, plan_raw, selection, fits=None, pending=None):
    """A selection given whole (the Takes screen): kept only as far as it is a chain from clip 1 (a new scene may
    follow any take it fits after: fits, plans.fits_map). pending: {take id: (clip, pseudo-record)} of the
    generations still waiting: the selection can go through a take not made yet."""
    known = dict(pending or {}, **_records_by_id(project))
    clean = {}
    if (selection or {}).get("branch"):
        clean["branch"] = str(selection["branch"])
    prev, index = None, 1
    while True:
        take_id = (selection or {}).get(index, (selection or {}).get(str(index)))
        if not take_id or take_id not in known or known[take_id][0] != index or (
                index > 1 and not follows(take_id, known[take_id][1], prev, fits)) or (index == 1 and predecessor(known[take_id][1])):
            break
        clean[index] = prev = take_id
        index += 1
    write_selection(project, clean)
    return clean


def leaf(selection):
    """(clip index, take id) of the last take of a selection, or (0, None)."""
    picked = sorted((k, v) for k, v in (selection or {}).items() if k != "branch" and v)
    return picked[-1] if picked else (0, None)


def ancestors(project: Path, plan_raw, index: int, take_id: str):
    """[(clip index, record)] from the given take up to the start of its scene (the takes it continues)."""
    known = _records_by_id(project)
    out = []
    while take_id:
        if take_id not in known:
            raise ValueError(_t("takes.take_of_clip_no_longer_exists", take_id=take_id, index=index))
        index, record = known[take_id]
        out.append((index, record))
        take_id = record.get("parent")
    return out


def take_branch(record, default):
    return (record.get("studio") or {}).get("branch") or default


def plan_video(plan):
    """The plan's video (start_video or edit_video, never both), or None. It is the project's video file."""
    for key in ("start_video", "edit_video"):
        if isinstance(plan.get(key), dict):
            return plan[key]
    return None
