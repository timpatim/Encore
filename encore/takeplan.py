"""Encore - the plan a take was made with, and the assembly of invalidated takes.

Since 0.24 a take records the entry of its clip in the plan (studio.plan_clip) and the raw start of its song
window (studio.raw_start). For older takes the entry is found again by its fingerprint in the plans Encore
keeps: the current plan, plan.previous.json, the checkpoints and the info sheets of the exports.
"""
from __future__ import annotations

import json
from pathlib import Path

from .i18n import t as _t
from . import plan_core, projects, takes


def _normalized(raw):
    try:
        return plan_core.normalize(json.loads(json.dumps(raw)))
    except Exception:              # a plan with errors: it cannot hold the snapshot
        return None


def _candidate_plans(project: Path, current_raw):
    """[(source, raw plan)], the most likely first."""
    yield "current", current_raw
    try:
        yield "previous", json.loads((project / "plan.previous.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    found = []
    for file in (project / "checkpoints").glob("cp_*.json") if (project / "checkpoints").is_dir() else []:
        try:
            cp = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (cp.get("state") or {}).get("plan"):
            found.append((cp.get("created") or 0, "checkpoint:" + str(cp.get("name") or cp.get("id")), cp["state"]["plan"]))
    for file in (project / "exports").glob("*.infos.json") if (project / "exports").is_dir() else []:
        try:
            info = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if info.get("plan"):
            found.append((file.stat().st_mtime, "export:" + file.name[:-len(".infos.json")], info["plan"]))
    for _when, source, raw in sorted(found, key=lambda f: -f[0]):
        yield source, raw


def take_snapshot(project: Path, current_raw, index: int, record):
    """(clip entry, raw start in frames or None, source) of the plan the take was made with, or (None, None, None)."""
    studio = record.get("studio") or {}
    if studio.get("plan_clip"):
        return studio["plan_clip"], studio.get("raw_start"), "record"
    fingerprint, frames = record.get("fingerprint"), record.get("frames")
    if not fingerprint:
        return None, None, None
    for source, raw in _candidate_plans(project, current_raw):
        plan = _normalized(raw)
        if not plan:
            continue
        order = [index] + [c["index"] for c in plan["clips"] if c["index"] != index]
        for j in order:
            if j > len(plan["clips"]) or plan["clips"][j - 1]["frames"] != frames:
                continue
            if plan_core.take_fingerprint(plan, j) == fingerprint:
                return (json.loads(json.dumps(raw["clips"][j - 1])), plan_core.timeline(plan)[j - 1]["raw_start"],
                        source)
    return None, None, None


def _file_info(project: Path, rel, sha=None):
    if not rel:
        return None
    file = projects.safe_join(project, rel)
    now = takes.file_sha(file) if file.is_file() else None
    return {"file": rel, "exists": now is not None, "sha": sha, "same": sha is None or now == sha}


def take_plan(root, name, index: int, take_id: str):
    """What the take window shows: the plan entry then and now, and the reference files then and now."""
    project = projects.project_dir(root, name)
    raw = projects.read_plan(root, name)
    record = next((r for r in takes.list_takes(project, raw).get(index, []) if r["id"] == take_id), None)
    if record is None:
        raise projects.StudioError(_t("takes.take_of_clip_no_longer_exists", take_id=take_id, index=index))
    snapshot, raw_start, source = take_snapshot(project, raw, index, record)
    return dict(_plan_view(project, raw, index, record, snapshot, raw_start, source), take=take_id)


def job_plan(root, name, job):
    """The same for a generation still queued or running: the plan it was launched with (kept with the job)."""
    project = projects.project_dir(root, name)
    raw = projects.read_plan(root, name)
    studio = job.get("studio") or {}
    record = {"studio": studio, "width": studio.get("width"), "height": studio.get("height"), "seed": job.get("seed"),
              "saved_at": job.get("created"), "parent": None}
    return dict(_plan_view(project, raw, int(job["clip"]), record, studio.get("plan_clip"), studio.get("raw_start"),
                           "job" if studio.get("plan_clip") else None), job=job["id"])


def _plan_view(project, raw, index, record, snapshot, raw_start, source):
    current = raw["clips"][index - 1] if 0 < index <= len(raw.get("clips") or []) else None
    studio = record.get("studio") or {}
    meta = projects.read_meta(project)
    branch_id = takes.take_branch(record, meta["branches"][0]["id"] if meta["branches"] else None)
    branch = next((b for b in meta["branches"] if b["id"] == branch_id), {})
    refs = {}
    names = list((studio.get("files") or {}).keys()) + [n for n in (branch.get("refs") or {}) if n not in (studio.get("files") or {})]
    for ref in names:
        then = (studio.get("files") or {}).get(ref) or {}
        shas = (studio.get("refs") or {}).get(ref) or {}
        now = (branch.get("refs") or {}).get(ref) or {}
        refs[ref] = {kind: {"then": _file_info(project, then.get(kind), shas.get(kind)),
                            "now": _file_info(project, now.get(kind))} for kind in ("image", "voice")}
    now_raw_start = None
    plan = _normalized(raw)
    if plan and current is not None:
        now_raw_start = plan_core.timeline(plan)[index - 1]["raw_start"]
    return {"clip": index, "snapshot": snapshot, "source": source, "current": current,
            "raw_start": raw_start, "now_raw_start": now_raw_start, "branch": branch_id,
            "size": [record.get("width"), record.get("height")], "refs": refs, "upscale": studio.get("upscale"),
            # what the generation used besides the plan (the « Generation » block of the window)
            "generation": {"models": studio.get("models"), "extra_loras": studio.get("extra_loras"),
                           "ref_image_size": studio.get("ref_image_size"), "song": studio.get("song_file")},
            "seed": record.get("seed"), "saved_at": record.get("saved_at"), "parent": record.get("parent")}


# --------------------------------------------------------------------------- assembling invalidated takes
def invalid_chain(project: Path, raw, plan, settings, branches, leaf_clip: int, leaf_id: str):
    """The takes an assembly ending with leaf_id would use when invalidated takes are allowed: the real parents
    of the leaf, and before a scene start the take chosen for the previous clip (the selection when usable, else
    the latest take of the branch). Returns {"chosen": {clip: id}, "records": {clip: record}, "invalid": [...],
    "warnings": [...], "error": str or None, "size": [w, h]}."""
    local = takes.list_takes(project, raw)
    by_id = {r["id"]: (i, r) for i, records in local.items() for r in records}
    if leaf_id not in by_id or by_id[leaf_id][0] != leaf_clip:
        raise projects.StudioError(_t("engine.take_of_clip_no_longer_exists", leaf_id=leaf_id, leaf_clip=leaf_clip))
    default = branches[0]["id"] if branches else "b1"
    branch_id = takes.take_branch(by_id[leaf_id][1], default)
    current_sel = takes.read_selection(project)
    selection = {"branch": branch_id}
    if current_sel.get("branch") in (None, branch_id):
        selection.update({int(k): v for k, v in current_sel.items() if k != "branch"})
    resolved = takes.studio_resolve(plan, local, selection, takes.current_state(project, plan, settings, branches))
    chosen, records, jumps = {}, {}, []
    index, take_id = leaf_clip, leaf_id
    while index >= 1:
        record = next((r for r in local.get(index, []) if r["id"] == take_id), None) if take_id else None
        if record is None:
            ok = resolved[index]["chosen"]
            sel = selection.get(index)
            mine = [r for r in sorted(local.get(index, []), key=lambda r: r.get("saved_at", 0))
                    if takes.take_branch(r, default) == branch_id]
            pick = ok or (sel if any(r["id"] == sel for r in mine) else None) or (mine[-1]["id"] if mine else None)
            if not pick:
                return {"error": _t("engine.nothing_to_assemble_clip_has_no", index=index), "chosen": {}, "records": {},
                        "invalid": [], "warnings": [], "size": None}
            record = next(r for r in local[index] if r["id"] == pick)
        chosen[index], records[index] = record["id"], record
        parent = record.get("parent")
        if parent and index > 1 and not any(r["id"] == parent for r in local.get(index - 1, [])):
            jumps.append(index)                  # what it continues is gone: another take is put before it
            parent = None
        take_id, index = parent, index - 1
    invalid = []
    for i in sorted(chosen):
        state, reason = resolved[i]["takes"].get(chosen[i], ("invalid", ""))
        if state == "invalid":
            invalid.append({"clip": i, "take": chosen[i], "reason": reason})
    sizes = {(r.get("width"), r.get("height")) for r in records.values()}
    warnings = [_t("takeplan.seam_jump", clip=i) for i in jumps]
    error = None
    if len(sizes) > 1:
        error = _t("takeplan.sizes_differ", sizes=", ".join(f"{w}×{h}" for w, h in sorted(sizes, key=str)))
    sent = sent_plan(project, raw, records, jumps)
    problems, _warn = plan_core.validate(json.loads(json.dumps(sent)))
    sent_norm = _normalized(sent) if not problems else None
    if problems and not error:
        error = _t("takeplan.plan_rebuild_failed", error=str(list(problems)[0]))
    if plan["mode"] != "free" and not error:
        sent_rows = plan_core.timeline(sent_norm)
        # where each take's song passage started when it was made: recorded (or found with its plan); else a
        # continuation started where its parent ended, and a scene start where the plan puts it now
        now_rows = plan_core.timeline(plan)
        shifted, made = [], {}
        for i in sorted(records):
            record = records[i]
            _snap, then_start, _src = take_snapshot(project, raw, i, record)
            if then_start is None:
                if i > 1 and record.get("parent") and i not in jumps and (i - 1) in made:
                    then_start = made[i - 1] + int(records[i - 1].get("frames") or 0) - sent_rows[i - 1]["context"]
                else:
                    then_start = now_rows[i - 1]["raw_start"] if i <= len(now_rows) else sent_rows[i - 1]["raw_start"]
            made[i] = then_start
            if then_start != sent_rows[i - 1]["raw_start"]:
                shifted.append(i)
        if shifted:
            warnings.append(_t("takeplan.song_shift", clips=", ".join(str(i) for i in sorted(shifted))))
    return {"chosen": chosen, "records": records, "invalid": invalid, "warnings": warnings, "error": error,
            "size": list(next(iter(sizes))) if len(sizes) == 1 else None, "branch": branch_id, "sent_plan": sent,
            "jumps": jumps}


def sent_plan(project: Path, raw, records, jumps=()):
    """The plan sent with an assembly of invalidated takes: clips 1..k as the takes were made (their entry from
    the snapshot when known, their frames, continue when they continue a take), the rest of the plan dropped."""
    copy = json.loads(json.dumps(raw))
    count = max(records)
    clips = []
    for i in range(1, count + 1):
        record = records[i]
        snap, _start, _src = take_snapshot(project, raw, i, record)
        entry = json.loads(json.dumps(snap if snap else raw["clips"][i - 1]))
        entry["name"] = raw["clips"][i - 1].get("name") or entry.get("name")
        entry["frames"] = int(record.get("frames") or entry.get("frames"))
        entry["continue"] = i > 1 and (bool(record.get("parent")) or i in jumps)
        entry.pop("seed", None)
        clips.append(entry)
    copy["clips"] = clips
    # a reference renamed or removed since a take: declared again (the names do not matter to an assembly)
    if not isinstance(copy.get("refs"), dict):
        copy["refs"] = {}
    declared = copy["refs"]
    for entry in clips:
        for ref in entry.get("refs") or []:
            declared.setdefault(ref, ref)
    return copy


def rewritten_record(sent_normalized, index, record, previous_id=None):
    """The record sent with the rewritten plan: the plugin finds it up to date."""
    data = dict(record)
    data["parent"] = previous_id if sent_normalized["clips"][index - 1]["continue"] else None
    data["fingerprint"] = plan_core.take_fingerprint(sent_normalized, index)
    data["frames"] = sent_normalized["clips"][index - 1]["frames"]
    data["refs"] = {}
    return data
