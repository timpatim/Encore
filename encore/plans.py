"""Encore - the plans of a project: master plans, suites, and the plan of a twig (chantier A).

A take never changes once made: its record keeps the *portion* of plan it was made with (studio.portion) and
the take before it in time (studio.predecessor: the take it continues, or the one it was timed after for a new
scene). What can still change is stored here, in plans.json:

    {"masters": {branch id: plan},                         the plan of a branch before any take (« plan maître »)
     "suites":  {take id: {"after": k, "plan": plan}}}     what comes after a take: clips k+1..N, header included

A plan has the form of a plan file (header + "clips"); a suite holds only the clips after its take. The plan of
a twig 1 → … → k (a chain of takes ending with the « leaf ») is never stored: the portions of the chain are read
from the records, then the suite of the leaf is added (plan_of). A generation sends such a composed plan to the
plugin; nothing else ever reads a plan file.

Used by the engine (launching, sending, assemblies) and the server (plan routes).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .i18n import t as _t
from . import plan_core, takes
from .projects import StudioError

FILE = "plans.json"
# the generations still waiting, when the caller gives none: {take id: (clip, pseudo-record)} of a project (set by
# the engine). A selection can go through a take not made yet (0.45).
PENDING = None


def _pending_of(path: Path):
    try:
        return PENDING(path.name) if PENDING else {}
    except Exception:   # noqa: BLE001 - no engine (tests of the module alone): no generation waiting
        return {}
# header keys a branch fixes with its first take (A1: only checked; the branch settings window comes in A2), and
# edit_video (but its instruction and its sound)
FROZEN_HEADER = ("mode", "start_video", "context_frames")


def _copy(value):
    return json.loads(json.dumps(value))


def load(path: Path):
    try:
        data = json.loads((path / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("masters", {})
    data.setdefault("suites", {})
    return data


def save(path: Path, data):
    file = path / FILE
    tmp = file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, file)


def head(plan):
    """The plan without its clips."""
    return {k: _copy(v) for k, v in (plan or {}).items() if k != "clips"}


# --------------------------------------------------------------------------- portions
def portion_of(record):
    """The portion of plan of a take: {"clip": raw entry, "edit_instruction", "refs_desc"}, or None."""
    return ((record or {}).get("studio") or {}).get("portion")


def predecessor_of(record):
    return ((record or {}).get("studio") or {}).get("predecessor")


def branch_of(record, default=None):
    return takes.take_branch(record or {}, default)


def locked_entry(portion, record):
    """The clip entry of a generated take, as it was made: {edit} replaced by its own instruction, the frames
    of the take, no seed (it is in the record)."""
    entry = _copy(portion["clip"])
    prompt, refs = plan_core.expand_edit(entry.get("prompt"), entry.get("refs") or [], portion.get("edit_instruction"))
    entry["prompt"], entry["refs"] = prompt, refs
    entry.pop("seed", None)
    if record and record.get("frames"):
        entry["frames"] = int(record["frames"])
    return entry


# --------------------------------------------------------------------------- chains
def records_by_id(path: Path):
    """{take id: (clip index, record)} of every visible take of the project."""
    out = {}
    for index, records in takes.list_takes(path).items():
        for record in records:
            out[record["id"]] = (index, record)
    return out


def is_cut(index, record):
    """True for a take of a new scene (✂): it does not continue the frames of the take before it."""
    if int(index) <= 1:
        return False
    clip = (portion_of(record) or {}).get("clip") or {}
    if "continue" in clip:
        return not clip["continue"]
    return not (record or {}).get("parent")


def _start_end(record):
    raw = ((record or {}).get("studio") or {}).get("raw_start")
    frames = (record or {}).get("frames")
    if raw is None or frames is None:
        return None, None
    return int(raw), int(raw) + int(frames)


def cut_fits(header, record, prev_record):
    """A new-scene take fits after prev_record when it would start there at the same moment of the song or of
    the edited video (in free mode, without an edited video: always)."""
    if (header or {}).get("mode") == "free" and not (header or {}).get("edit_video"):
        return True
    start, _end = _start_end(record)
    _pstart, pend = _start_end(prev_record)
    if start is None or pend is None:
        return False
    context = plan_core.snap_context(int((header or {}).get("context_frames", plan_core.DEFAULT_CONTEXT)),
                                     int(prev_record["frames"]), int(record["frames"]))
    return pend - context == start


def fits_map(path: Path, known=None, pending=None):
    """{take id of a new scene: [take ids of the clip before, same branch, after which it fits]} (the take it
    was made after is not listed)."""
    known = records_by_id(path) if known is None else known
    every = dict(pending or {}, **known)
    masters = load(path)["masters"]
    by_clip = {}
    for take_id, (index, record) in every.items():
        by_clip.setdefault(index, []).append((take_id, record))
    out = {}
    for take_id, (index, record) in known.items():
        if not is_cut(index, record):
            continue
        branch = branch_of(record)
        header = masters.get(branch) or {}
        own = predecessor_of(record)
        ok = [pid for pid, prev in by_clip.get(index - 1, [])
              if pid != own and branch_of(prev) == branch and cut_fits(header, record, prev)]
        if ok:
            out[take_id] = ok
    return out


def base_of(path: Path, branch_id):
    """[take ids of clips 1..k] a duplicated branch takes over from another branch ([] otherwise)."""
    from . import projects
    try:
        meta = projects.read_meta(path)
    except (OSError, ValueError, StudioError):
        return []
    branch = next((b for b in meta.get("branches") or [] if b["id"] == branch_id), None)
    return projects.branch_base(branch)


def selection_prefer(path: Path, branch_id):
    """Where a twig meets a new scene, it follows the selection (when it is in this branch); the clips a branch
    takes over always come first."""
    sel = takes.read_selection(path)
    out = {k: v for k, v in sel.items() if k != "branch"} if sel.get("branch") in (None, branch_id) else {}
    out.update({i: t for i, t in enumerate(base_of(path, branch_id), start=1)})
    return out


def chain(path: Path, leaf_id, known=None, pending=None, prefer=None):
    """[(clip index, take id, record or None)] from clip 1 to the leaf, following the predecessors; at a new scene
    (✂), the take chosen in `prefer` ({clip index: take id}, the selection) for the clip before when the new scene
    fits after it (cut_fits). known: records_by_id(path) if already read. pending: {take id: (clip index,
    pseudo-record)} for generations still waiting (their take id is known at launch). Raises StudioError when a
    link is missing."""
    known = records_by_id(path) if known is None else known
    pending = _pending_of(path) if pending is None else pending
    prefer = prefer or {}
    masters = None
    out, take_id, seen = [], leaf_id, set()
    while take_id:
        if take_id in seen:
            raise StudioError(_t("plans.chain_loop", take_id=take_id))
        seen.add(take_id)
        if take_id in known:
            index, record = known[take_id]
        elif take_id in pending:
            index, record = pending[take_id]
        else:
            raise StudioError(_t("plans.take_missing", take_id=take_id))
        if out and index != out[-1][0] - 1:
            raise StudioError(_t("plans.chain_broken", take_id=take_id))
        out.append((index, take_id, record))
        nxt = predecessor_of(record)
        alt = prefer.get(index - 1)
        if alt and alt != nxt and is_cut(index, record) and (alt in known or alt in pending):
            masters = load(path)["masters"] if masters is None else masters
            prev = (known.get(alt) or pending.get(alt))[1]
            if branch_of(prev) == branch_of(record) and cut_fits(masters.get(branch_of(record)) or {}, record, prev):
                nxt = alt
        take_id = nxt
    out.reverse()
    if out and out[0][0] != 1:
        raise StudioError(_t("plans.chain_broken", take_id=out[0][1]))
    return out


# --------------------------------------------------------------------------- plans
def master(path: Path, branch_id):
    plan = load(path)["masters"].get(branch_id)
    return _copy(plan) if plan else None


def set_master(path: Path, branch_id, plan):
    data = load(path)
    data["masters"][branch_id] = _copy(plan)
    save(path, data)


def suite(path: Path, take_id):
    item = load(path)["suites"].get(take_id)
    return _copy(item) if item else None


def set_suite(path: Path, take_id, after: int, plan):
    data = load(path)
    data["suites"][take_id] = {"after": int(after), "plan": _copy(plan)}
    save(path, data)


def drop_suites(path: Path, take_ids):
    data = load(path)
    for take_id in take_ids:
        data["suites"].pop(take_id, None)
    save(path, data)


def plan_of(path: Path, branch_id, leaf_id=None, known=None, pending=None, project_name=None, prefer=None):
    """The plan of a twig: {"plan": raw plan (header of the leaf's suite, portions of the chain, then the
    suite), "locked": k (clips 1..k generated, read-only), "chain": [take ids], "takes": {index: take id}}.
    Without a leaf: the master plan of the branch (nothing locked). prefer: see chain (default: the selection)."""
    data = load(path)
    if not leaf_id:
        plan = _copy(data["masters"].get(branch_id) or {})
        if not plan:
            raise StudioError(_t("plans.no_master", branch_id=branch_id))
        plan.setdefault("clips", [])
        if project_name:
            plan["project"] = project_name
        base = base_of(path, branch_id)
        if not base:
            return {"plan": plan, "locked": 0, "chain": [], "takes": {}}
        # a duplicated branch: its master plan starts with the clips it takes over, read-only
        known = records_by_id(path) if known is None else known
        clips = []
        for take_id in base:
            if take_id not in known:
                raise StudioError(_t("plans.take_missing", take_id=take_id))
            record = known[take_id][1]
            clips.append(locked_entry(portion_of(record), record))
        plan["clips"] = clips + plan["clips"][len(base):]
        return {"plan": plan, "locked": len(base), "chain": list(base),
                "takes": {i: t for i, t in enumerate(base, start=1)}}
    if leaf_id in base_of(path, branch_id):
        # a clip a duplicated branch takes over: what follows is the master plan of that branch
        return plan_of(path, branch_id, None, known, pending, project_name)
    links = chain(path, leaf_id, known, pending, selection_prefer(path, branch_id) if prefer is None else prefer)
    item = data["suites"].get(leaf_id)
    if item is None:
        # a take without a suite (made before its suite was written): the master after its clip
        base = _copy(data["masters"].get(branch_id) or {"clips": []})
        item = {"after": len(links), "plan": dict(base, clips=(base.get("clips") or [])[len(links):])}
    plan = head(item["plan"])
    clips, declared = [], dict(plan.get("refs") or {})
    for index, _take_id, record in links:
        portion = portion_of(record)
        if not portion:
            raise StudioError(_t("plans.take_without_portion", take_id=_take_id))
        clips.append(locked_entry(portion, record))
        for name in clips[-1].get("refs") or []:
            declared.setdefault(name, (portion.get("refs_desc") or {}).get(name) or name)
    clips += _copy(item["plan"].get("clips") or [])
    plan["refs"] = declared
    plan["clips"] = clips
    if project_name:
        plan["project"] = project_name
    return {"plan": plan, "locked": len(links), "chain": [t for _i, t, _r in links],
            "takes": {i: t for i, t, _r in links}}


def suite_from(plan, locked: int):
    """The editable part of a twig's plan: header + clips after the locked ones."""
    out = head(plan)
    out["clips"] = _copy((plan.get("clips") or [])[locked:])
    return out


def save_twig_plan(path: Path, branch_id, leaf_id, plan, known=None):
    """Saves what can change in the plan of a twig (or the master plan without a leaf). The clips 1..k of a
    twig are the portions of its takes: they are not stored again."""
    if not isinstance(plan, dict) or not isinstance(plan.get("clips"), list):
        raise StudioError(_t("projects.the_plan_must_be_a_json"))
    if not leaf_id or leaf_id in base_of(path, branch_id):
        set_master(path, branch_id, plan)
        return len(base_of(path, branch_id))
    locked = len(chain(path, leaf_id, known, prefer=selection_prefer(path, branch_id)))
    set_suite(path, leaf_id, locked, suite_from(plan, locked))
    return locked


def frozen_problems(path: Path, branch_id, new_plan, has_takes: bool):
    """Header changes a branch with takes refuses (A1: mode, start video, context; the edited video except its
    instruction)."""
    if not has_takes:
        return []
    old = load(path)["masters"].get(branch_id) or {}
    # what only the assembly uses stays free: the start video in the final video or not, the edited video's sound
    loose = {"start_video": ("in_assembly",), "edit_video": ("instruction", "sound")}
    strip = lambda key, v: {k: x for k, x in v.items() if k not in loose.get(key, ())} if isinstance(v, dict) else v  # noqa: E731
    problems = []
    for key in FROZEN_HEADER + ("edit_video",):
        if _copy(strip(key, old.get(key))) != _copy(strip(key, new_plan.get(key))):
            problems.append(key)
    return problems
