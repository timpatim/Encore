"""Encore - the plans of a project: master plans, suites, and the plan of a twig (chantier A).

A take never changes once made: its record keeps the *portion* of plan it was made with (studio.portion) and
the take before it in time (studio.predecessor: the take it continues, or the one it was timed after for a new
scene). What can still change is stored here, in plans.json:

    {"masters": {branch id: plan},                         the plan of a branch before any take (« plan maître »)
     "suites":  {take id: {"after": k, "plan": plan}},     what comes after a take: clips k+1..N, header included
     "frozen":  {branch id: {"clips": k, "subjects": [names]}}}   what of a master plan no longer changes (0.48)

The master line (0.48): the takes made from the master plan itself (studio.line), one per clip, in a row at the
top of the branch; they have no suite of their own, what follows them is the master plan. Once a branch has a take
or a generation waiting, its master plan is frozen: its clips 1..k and its subjects (with the files they use) do not
change any more; clips can be added at the end, and new subjects. A master clip the line generates is frozen too.

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
    data.setdefault("frozen", {})
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
    """The portion of plan of a take: {"clip": raw entry, with its 'defs' (subjects, files and edit instruction it
    was made with)}, or None."""
    return ((record or {}).get("studio") or {}).get("portion")


def predecessor_of(record):
    return ((record or {}).get("studio") or {}).get("predecessor")


def branch_of(record, default=None):
    return takes.take_branch(record or {}, default)


def locked_entry(portion, record):
    """The clip entry of a generated take, as it was made (its 'defs' hold the subjects, files and edit
    instruction it used), with the frames of the take and no seed (it is in the record)."""
    entry = _copy(portion["clip"])
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
    """[take id or None of clips 1..k] a duplicated branch takes over from another branch ([] otherwise); None: a
    clip left free between two portions (0.49)."""
    from . import projects
    try:
        meta = projects.read_meta(path)
    except (OSError, ValueError, StudioError):
        return []
    branch = next((b for b in meta.get("branches") or [] if b["id"] == branch_id), None)
    return projects.branch_base(branch)


def kept_of(path: Path, branch_id):
    """{clip index: take id} of the clips a duplicated branch takes over."""
    return {i: t for i, t in enumerate(base_of(path, branch_id), start=1) if t}


def holes_of(path: Path, branch_id):
    """0.49: the clips left free before the last clip a duplicated branch takes over (their frames are locked,
    so that the portions after them stay at their moment of the song)."""
    base = base_of(path, branch_id)
    return [i for i, t in enumerate(base, start=1) if not t]


def selection_prefer(path: Path, branch_id):
    """Where a twig meets a new scene, it follows the selection (when it is in this branch); the clips a branch
    takes over always come first."""
    sel = takes.read_selection(path)
    out = {k: v for k, v in sel.items() if k != "branch"} if sel.get("branch") in (None, branch_id) else {}
    out.update(kept_of(path, branch_id))
    return out


def chain(path: Path, leaf_id, known=None, pending=None, prefer=None, branch=None):
    """[(clip index, take id, record or None)] from clip 1 to the leaf, following the predecessors; at a new scene
    (✂), the take chosen in `prefer` ({clip index: take id}, the selection) for the clip before when the new scene
    fits after it (cut_fits). known: records_by_id(path) if already read. pending: {take id: (clip index,
    pseudo-record)} for generations still waiting (their take id is known at launch). Raises StudioError when a
    link is missing. branch (0.49): the twig is read in that branch: a clip it takes over after a clip left free
    follows its own take of that clip (the one of `prefer` when it is one, otherwise the one of its master line).
    """
    known = records_by_id(path) if known is None else known
    pending = _pending_of(path) if pending is None else pending
    prefer = prefer or {}
    masters = None
    kept = kept_of(path, branch) if branch else {}
    line = None
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
        if kept and kept.get(index) == take_id and index > 1 and (index - 1) not in kept:
            # a portion taken over after a clip left free: it follows the branch's own take of that clip
            fill = prefer.get(index - 1)
            mine = (known.get(fill) or pending.get(fill)) if fill else None
            if not (mine and int(mine[0]) == index - 1 and branch_of(mine[1]) == branch):
                line = line_of(path, branch, known, pending) if line is None else line
                fill = line.get(index - 1)
            if not fill or fill in kept.values():
                raise StudioError(_t("plans.portion_hole", index=index - 1))
            take_id = fill
            continue
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


# --------------------------------------------------------------------------- the master line, the frozen master
def is_line(record):
    return bool(((record or {}).get("studio") or {}).get("line"))


def line_of(path: Path, branch_id, known=None, pending=None):
    """{clip index: take id} of the master line of a branch: the clips it takes over (duplicated branch), then its
    takes made from the master plan (generations waiting included), the oldest one when there are several."""
    known = records_by_id(path) if known is None else known
    pending = _pending_of(path) if pending is None else pending
    out = kept_of(path, branch_id)
    found = [(index, record.get("saved_at") or 0, take_id) for take_id, (index, record) in known.items()
             if is_line(record) and branch_of(record) == branch_id]
    found += [(index, float("inf"), take_id) for take_id, (index, record) in pending.items()
              if is_line(record) and branch_of(record) == branch_id and take_id not in known]
    for index, _at, take_id in sorted(found):
        out.setdefault(int(index), take_id)
    return out


def line_end(line):
    """The last clip of a master line, from clip 1 without a gap (0: nothing generated yet)."""
    k = 0
    while (k + 1) in line:
        k += 1
    return k


def has_own_takes(path: Path, branch_id, known=None, pending=None):
    """True when a branch has a take of its own (not one it takes over) or a generation waiting."""
    known = records_by_id(path) if known is None else known
    pending = _pending_of(path) if pending is None else pending
    base = set(kept_of(path, branch_id).values())
    return (any(branch_of(r) == branch_id and t not in base for t, (_i, r) in known.items())
            or any(branch_of(r) == branch_id for _t, (_i, r) in pending.items()))


def frozen_of(path: Path, branch_id, known=None, pending=None):
    """What of a branch's master plan no longer changes: {"clips": k, "subjects": [names]}, or None while the
    branch has no take of its own and no generation waiting."""
    if not has_own_takes(path, branch_id, known, pending):
        return None
    data = load(path)
    item = data["frozen"].get(branch_id)
    if item is None:     # a branch with takes made before 0.48: frozen as it is now
        item = _snapshot(data, branch_id)
        data["frozen"][branch_id] = item
        save(path, data)
    return _copy(item)


def _snapshot(data, branch_id):
    master_plan = data["masters"].get(branch_id) or {}
    return {"clips": len(master_plan.get("clips") or []), "subjects": sorted((master_plan.get("subjects") or {}).keys())}


def freeze(path: Path, branch_id, index=None, subjects=(), known=None, pending=None):
    """A generation of the branch is launched (before it is queued): the master plan is frozen as it is, if it was
    not already; a clip of the master line freezes that clip and the subjects it uses."""
    active = has_own_takes(path, branch_id, known, pending)
    data = load(path)
    item = data["frozen"].get(branch_id) if active else None
    item = _copy(item) if item else _snapshot(data, branch_id)
    if index:
        item["clips"] = max(int(item["clips"]), int(index))
    item["subjects"] = sorted(set(item["subjects"]) | set(subjects or ()))
    data["frozen"][branch_id] = item
    save(path, data)


def _frozen_files(plan, item):
    """The file labels the frozen part of a master plan uses: pictures and voices of its frozen subjects, anchors
    of its frozen clips, the edited video."""
    out = set()
    subjects = plan.get("subjects") or {}
    for name in item["subjects"]:
        subject = subjects.get(name) or {}
        out.update(p.get("file") for p in subject.get("pictures") or [] if isinstance(p, dict))
        if subject.get("voice"):
            out.add(subject["voice"])
    for clip in (plan.get("clips") or [])[:item["clips"]]:
        anchors = (clip or {}).get("anchors") or {}
        out.update(x for x in (anchors.get("first"), anchors.get("last")) if x)
        out.update(k.get("file") for k in anchors.get("keyframes") or [] if isinstance(k, dict))
    for key in ("edit_video", "start_video"):
        if isinstance(plan.get(key), dict) and plan[key].get("ref"):
            out.add(plan[key]["ref"])
    out.discard(None)
    return out


def master_frozen_problems(path: Path, branch_id, new_plan):
    """What a new master plan changes in the frozen part of the old one ([] when nothing, or not frozen)."""
    item = frozen_of(path, branch_id)
    if not item:
        return []
    old = load(path)["masters"].get(branch_id) or {}
    kept = kept_of(path, branch_id)      # the clips taken over are never read from the master plan
    old_clips, new_clips = old.get("clips") or [], new_plan.get("clips") or []
    problems = []
    k = min(item["clips"], len(old_clips))
    if len(new_clips) < k or any(_copy(new_clips[i]) != _copy(old_clips[i]) for i in range(k) if (i + 1) not in kept):
        problems.append(_t("plans.frozen_clips", k=k))
    old_subjects, new_subjects = old.get("subjects") or {}, new_plan.get("subjects") or {}
    changed = [n for n in item["subjects"] if n in old_subjects and _copy(new_subjects.get(n)) != _copy(old_subjects[n])]
    if changed:
        problems.append(_t("plans.frozen_subjects", names=", ".join("@" + n for n in changed)))
    old_files, new_files = old.get("files") or {}, new_plan.get("files") or {}
    def filled(f):         # a file declared without its path (an imported plan) may get one: that changes nothing made
        o, n = old_files[f] or {}, new_files.get(f) or {}
        return not o.get("file") and n.get("file") and {k: v for k, v in n.items() if k != "file"} == {k: v for k, v in o.items() if k != "file"}
    files = [f for f in sorted(_frozen_files(old, item)) if f in old_files and _copy(new_files.get(f)) != _copy(old_files[f]) and not filled(f)]
    if files:
        problems.append(_t("plans.frozen_files", names=", ".join(files)))
    return problems


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
        kept = kept_of(path, branch_id)
        frozen = frozen_of(path, branch_id, known, pending)
        out = {"plan": plan, "locked": 0, "chain": [], "takes": {}}
        if kept:
            # a duplicated branch: its master plan starts with the clips it takes over, read-only; the clips left
            # free between them (0.49) stay editable ("free"), their length locked
            known = records_by_id(path) if known is None else known
            clips = list(plan["clips"])
            last = max(kept)
            while len(clips) < last:
                clips.append({})
            for i, take_id in kept.items():
                if take_id not in known:
                    raise StudioError(_t("plans.take_missing", take_id=take_id))
                record = known[take_id][1]
                clips[i - 1] = locked_entry(portion_of(record), record)
            plan["clips"] = clips
            prefix = []
            while (len(prefix) + 1) in kept:
                prefix.append(kept[len(prefix) + 1])
            out = {"plan": plan, "locked": last, "chain": prefix, "takes": dict(kept)}
            holes = [i for i in range(1, last + 1) if i not in kept]
            if holes:
                out["holes"] = holes
        if frozen:
            # a frozen master plan: its first clips are read-only (with the take of the master line that made them)
            out["locked"] = max(out["locked"], min(frozen["clips"], len(plan["clips"])))
            out["takes"] = line_of(path, branch_id, known, pending)
            out["frozen"] = frozen
        if out.get("holes"):
            # 0.49: the clips left free stay editable like any clip of a master plan (until the master line freezes
            # them); only their length and link are locked (lock_length)
            out["free"] = [i for i in out["holes"] if not (frozen and i <= int(frozen["clips"]))]
        return out
    kept = kept_of(path, branch_id)
    if leaf_id in kept.values():
        # a clip a duplicated branch takes over: what follows is the master plan of that branch; the twig up to it
        # goes through the branch's own takes of the clips left free (0.49), when they are made
        master_view = plan_of(path, branch_id, None, known, pending, project_name)
        try:
            links = chain(path, leaf_id, known, pending, selection_prefer(path, branch_id) if prefer is None else prefer,
                          branch=branch_id)
        except StudioError:
            return master_view
        plan = master_view["plan"]
        clips = []
        for _index, _take_id, record in links:
            clips.append(locked_entry(portion_of(record), record))
        plan["clips"] = clips + (plan.get("clips") or [])[len(links):]
        out = dict(master_view, chain=[t for _i, t, _r in links])
        out["takes"] = {**master_view["takes"], **{i: t for i, t, _r in links}}
        return out
    links = chain(path, leaf_id, known, pending, selection_prefer(path, branch_id) if prefer is None else prefer,
                  branch=branch_id if kept else None)
    item = data["suites"].get(leaf_id)
    if item is None:
        # a take without a suite (made before its suite was written): the master after its clip
        base = _copy(data["masters"].get(branch_id) or {"clips": []})
        item = {"after": len(links), "plan": dict(base, clips=(base.get("clips") or [])[len(links):])}
    plan = head(item["plan"])
    clips = []
    for index, _take_id, record in links:
        portion = portion_of(record)
        if not portion:
            raise StudioError(_t("plans.take_without_portion", take_id=_take_id))
        clips.append(locked_entry(portion, record))
    clips += _copy(item["plan"].get("clips") or [])
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
    kept = kept_of(path, branch_id)
    if not leaf_id or leaf_id in kept.values():
        set_master(path, branch_id, plan)
        return max(kept) if kept else 0
    locked = len(chain(path, leaf_id, known, prefer=selection_prefer(path, branch_id), branch=branch_id if kept else None))
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
