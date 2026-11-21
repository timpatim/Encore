"""Encore - the takes of a project, stored in the project folder.

    takes/clip_NNN/<take id>.pt     latent (H3 audio-video latent, as saved by the plugin)
    takes/clip_NNN/<take id>.json   signature written by the plugin, plus a "studio" part
    takes/clip_NNN/<take id>.mp4    preview
    selection.json                  take chosen for each clip

The "studio" part of a signature records what the Studio sent: the project files used for each
reference (with their SHA-256), the picture size and the models.
"""
from __future__ import annotations

from .i18n import t as _t
import hashlib
import json
import os
import re
from pathlib import Path

from . import plan_core


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


def hidden_takes(project: Path):
    """Takes masked by the restoration of a checkpoint (made after it): kept on disk, never shown."""
    try:
        return set(json.loads((project / "hidden_takes.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def write_hidden_takes(project: Path, ids):
    path = project / "hidden_takes.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(ids), indent=0), encoding="utf-8")
    os.replace(tmp, path)


def all_take_ids(project: Path):
    """[(clip index, take id)] of every take on disk, hidden or not."""
    out = []
    for folder in sorted((project / "takes").glob("clip_*")):
        if not folder.is_dir() or not folder.name[5:].isdigit():
            continue
        for meta in sorted(folder.glob("*.json")):
            if TAKE_ID_RE.match(meta.stem) and meta.with_suffix(".pt").is_file():
                out.append((int(folder.name[5:]), meta.stem))
    return out


def list_takes(project: Path, plan):
    """{clip index: [record with "id"]} for the clips of the plan (hidden takes left out)."""
    hidden = hidden_takes(project)
    out = {}
    for index, _name, _cont in _clips(plan):
        folder = clip_dir(project, index)
        records = []
        if folder.is_dir():
            for meta in sorted(folder.glob("*.json")):
                take_id = meta.stem
                if not TAKE_ID_RE.match(take_id) or take_id in hidden or not meta.with_suffix(".pt").is_file():
                    continue
                try:
                    record = json.loads(meta.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                record["id"] = take_id
                records.append(record)
        out[index] = records
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


def _clips(plan):
    """[(index, name, continue)] read leniently, so that a plan with errors can still be listed."""
    return [(k, (c.get("name") or f"clip_{k:03d}"), bool(c.get("continue")) and k > 1)
            for k, c in enumerate(plan.get("clips") or [], start=1)]


def listing(project: Path, plan_raw):
    """What the takes tab shows: every take with its signature and preview, and the selection."""
    takes = list_takes(project, plan_raw)
    selection = read_selection(project)
    clips = []
    for index, name, _cont in _clips(plan_raw):
        items = []
        for record in sorted(takes.get(index, []), key=lambda r: r.get("saved_at", 0)):
            _pt, _js, mp4 = take_files(project, index, record["id"])
            preview = {"subfolder": f"takes/clip_{index:03d}", "filename": mp4.name} if mp4.is_file() else None
            items.append({"id": record["id"], "record": record, "preview": preview})
        clips.append({"index": index, "name": name, "takes": items, "selected": selection.get(index)})
    return {"project": project.name, "clips": clips, "selection_branch": selection.get("branch")}


def select_chain(project: Path, plan_raw, index: int, take_id: str, branch=None):
    """Choose a take and, for a continuation, the takes it is built on. A take of another branch than the
    selected one switches the selection to its branch (the clips of the other branch are dropped)."""
    takes = list_takes(project, plan_raw)
    conts = {i: c for i, _n, c in _clips(plan_raw)}
    by_id = {r["id"]: r for records in takes.values() for r in records}
    if take_id not in by_id:
        raise ValueError(_t("takes.clip_has_no_take", index=index, take_id=take_id))
    selection = read_selection(project)
    if branch and selection.get("branch") not in (None, branch):
        selection = {}
    if branch:
        selection["branch"] = branch
    selection[index] = take_id
    record = by_id[take_id]
    while conts.get(index) and record.get("parent") in by_id:
        index -= 1
        selection[index] = record["parent"]
        record = by_id[record["parent"]]
    write_selection(project, selection)
    return selection


def save_selection(project: Path, plan_raw, selection):
    takes = list_takes(project, plan_raw)
    clean = {}
    for key, take_id in (selection or {}).items():
        if key == "branch":
            if take_id:
                clean["branch"] = str(take_id)
            continue
        index = int(key)
        if take_id and any(r["id"] == take_id for r in takes.get(index, [])):
            clean[index] = take_id
    write_selection(project, clean)
    return clean


def ancestors(project: Path, plan_raw, index: int, take_id: str):
    """[(clip index, record)] from the given take up to the start of its scene."""
    takes = list_takes(project, plan_raw)
    conts = {i: c for i, _n, c in _clips(plan_raw)}
    out = []
    while take_id:
        record = next((r for r in takes.get(index, []) if r["id"] == take_id), None)
        if record is None:
            raise ValueError(_t("takes.take_of_clip_no_longer_exists", take_id=take_id, index=index))
        out.append((index, record))
        if conts.get(index):
            take_id, index = record.get("parent"), index - 1
        else:
            take_id = None
    return out


# --------------------------------------------------------------------------- validity (Studio rules)
# Every take belongs to a branch (record["studio"]["branch"]); a branch holds its reference files, song and
# picture size.
# A take is "invalid" when something it was made with differs
#   1. from the project as it is now (a reference file or the song of its branch, the picture size, its
#      clip in the plan): undone by putting the old value back, or
#   2. from a more recent take that shares it (same branch for references and song): final - only a
#      checkpoint brings such a take back,
# or when the take it continues is invalid or missing. Takes of another branch than the selected one are
# "other". Nothing is ever deleted.
# The same rules are written in plan_core.js (studioResolveTakes); keep both identical.
def take_branch(record, default):
    return (record.get("studio") or {}).get("branch") or default


def _take_keys(record, index, free, branch, legacy_ref_size):
    """{key: value} of what a take was made with."""
    studio = record.get("studio") or {}
    keys = {f"{branch}|size": [record.get("width"), record.get("height")],
            f"{branch}|refsize": studio.get("ref_image_size") or legacy_ref_size,
            f"plan:{index}": [record.get("fingerprint"), record.get("frames")]}
    for name, kinds in sorted((studio.get("refs") or {}).items()):
        keys[f"{branch}|image:{name}"] = (kinds or {}).get("image")
        if free:
            keys[f"{branch}|voice:{name}"] = (kinds or {}).get("voice")
    if not free and "song" in studio:
        keys[f"{branch}|song"] = studio.get("song")
    return keys


def _reason(key, final):
    key = key.split("|", 1)[-1]
    kind, _, name = key.partition(":")
    what = {"size": _t("takes.the_picture_size"), "refsize": _t("takes.the_reference_size"), "plan": _t("takes.the_clip_s_plan"), "image": _t("takes.the_picture_of_name", name=name),
            "voice": _t("takes.the_voice_of", name=name), "song": _t("takes.the_song")}[kind]
    return _t("takes.redone_since_with_another_value", what=what) if final else _t("takes.has_changed", what=what)


def studio_resolve(plan, takes_by_clip, selection, current):
    """plan: normalized; selection: {index: id, "branch": id}; current: {"fingerprints": {index: fp},
    "branches": {id: {"refs": {name: {"image": sha, "voice": sha}}, "song": sha, "size": [w, h]}}, "default_branch": id}.
    Returns {index: {"chosen": id or None, "takes": {id: (state, reason)}}, "branch": selected branch},
    state in ok / other / invalid."""
    free = plan["mode"] == "free"
    default = current.get("default_branch")
    selection = dict(selection or {})
    wanted_branch = selection.pop("branch", None)
    selection = {int(k): v for k, v in selection.items()}
    now = {}
    for clip in plan["clips"]:
        now[f"plan:{clip['index']}"] = [current["fingerprints"][clip["index"]], clip["frames"]]
    for bid, bset in (current.get("branches") or {}).items():
        for name, kinds in ((bset or {}).get("refs") or {}).items():
            now[f"{bid}|image:{name}"] = (kinds or {}).get("image")
            now[f"{bid}|voice:{name}"] = (kinds or {}).get("voice")
        now[f"{bid}|song"] = (bset or {}).get("song")
        now[f"{bid}|size"] = list((bset or {}).get("size") or [None, None])
        now[f"{bid}|refsize"] = (bset or {}).get("ref_image_size")
    records, branch_of = [], {}
    for index, items in takes_by_clip.items():
        for record in items:
            branch = take_branch(record, default)
            branch_of[record["id"]] = branch
            records.append((index, record, _take_keys(record, index, free, branch, current.get("legacy_ref_image_size") or "match")))
    records.sort(key=lambda r: r[1].get("saved_at", 0))
    why = {}
    # 1. differs from the project now
    for index, record, keys in records:
        for key, value in keys.items():
            if value != now.get(key):
                why.setdefault(record["id"], _reason(key, False))
                break
    # 2. a more recent take was made with another value (final)
    later = {}
    for index, record, keys in reversed(records):
        for key, value in keys.items():
            seen = later.setdefault(key, [])
            if any(v != value for v in seen):
                why[record["id"]] = _reason(key, True)
            if value not in seen:
                seen.append(value)
    # the selected branch
    branches = set(branch_of.values())
    active = wanted_branch if wanted_branch in branches else None
    if active is None:
        for index in sorted(selection):
            if selection[index] in branch_of:
                active = branch_of[selection[index]]
                break
    if active is None:
        first = [r for i, r, _k in records if i == 1 and r["id"] not in why]
        active = branch_of[first[-1]["id"]] if first else (sorted(branches)[0] if branches else None)
    # 3. built on an invalid or missing take, other branch; then choose
    result = {}
    for clip in plan["clips"]:
        index = clip["index"]
        previous = result.get(index - 1)
        states = {}
        for record in sorted(takes_by_clip.get(index, []), key=lambda r: r.get("saved_at", 0)):
            tid = record["id"]
            if tid in why:
                states[tid] = ("invalid", why[tid])
                continue
            if clip["continue"] and index > 1:
                parent = record.get("parent")
                pstate = previous["takes"].get(parent) if previous else None
                if pstate is None:
                    states[tid] = ("invalid", _t("takes.the_take_it_continues_does_not"))
                    continue
                if pstate[0] == "invalid":
                    states[tid] = ("invalid", _t("takes.built_on_an_invalidated_take"))
                    continue
            if branch_of[tid] != active:
                states[tid] = ("other", _t("takes.other_branch"))
            elif clip["continue"] and index > 1 and record.get("parent") != previous["chosen"]:
                states[tid] = ("other", _t("takes.built_on_another_take_of_the"))
            else:
                states[tid] = ("ok", "")
        chosen = selection.get(index)
        if states.get(chosen, ("",))[0] != "ok":
            ok = [tid for tid, (st, _w) in states.items() if st == "ok"]
            chosen = ok[-1] if ok else None
        result[index] = {"chosen": chosen, "takes": states}
    result["branch"] = active
    return result


def branch_state(project: Path, branch):
    """SHA-256 of the files of a branch's set."""
    def sha(rel):
        path = project / rel if rel else None
        return file_sha(path) if path and path.is_file() else None
    return {"refs": {name: {"image": sha((files or {}).get("image")), "voice": sha((files or {}).get("voice"))}
                     for name, files in (branch.get("refs") or {}).items()},
            "song": sha(branch.get("song")), "size": [branch.get("width"), branch.get("height")],
            "ref_image_size": branch.get("ref_image_size")}


def current_state(project: Path, plan, settings, branches):
    """What studio_resolve compares the takes with, read from the project files."""
    try:
        legacy = json.loads((project / "project.json").read_text(encoding="utf-8")).get("legacy_ref_image_size") or "match"
    except (OSError, ValueError):
        legacy = "match"
    return {"branches": {b["id"]: branch_state(project, b) for b in branches}, "legacy_ref_image_size": legacy,
            "default_branch": branches[0]["id"] if branches else None,
            "fingerprints": {c["index"]: plan_core.take_fingerprint(plan, c["index"]) for c in plan["clips"]}}
