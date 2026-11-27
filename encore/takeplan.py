"""Encore - the portion of plan a take was made with (the ≡ window of a take or of a waiting generation).

A take keeps its portion of plan (studio.portion) and the take before it (studio.predecessor); see plans.py.
"""
from __future__ import annotations

from .i18n import t as _t
from . import plans, projects, takes


def _file_info(project, rel, sha=None):
    if not rel:
        return None
    file = projects.safe_join(project, rel)
    now = takes.file_sha(file) if file.is_file() else None
    return {"file": rel, "exists": now is not None, "sha": sha, "same": sha is None or now == sha}


def take_plan(root, name, index: int, take_id: str):
    """What the window of a take shows: its portion of plan, the files and the generation settings."""
    project = projects.project_dir(root, name)
    record = next((r for r in takes.list_takes(project).get(index, []) if r["id"] == take_id), None)
    if record is None:
        raise projects.StudioError(_t("takes.take_of_clip_no_longer_exists", take_id=take_id, index=index))
    return dict(_plan_view(project, index, record), take=take_id, source="record")


def job_plan(root, name, job):
    """The same for a generation still queued or running."""
    project = projects.project_dir(root, name)
    studio = job.get("studio") or {}
    record = {"studio": studio, "width": studio.get("width"), "height": studio.get("height"), "seed": job.get("seed"),
              "saved_at": job.get("created"), "parent": None, "frames": job.get("frames")}
    return dict(_plan_view(project, int(job["clip"]), record), job=job["id"], source="job")


def _plan_view(project, index, record):
    studio = record.get("studio") or {}
    portion = plans.portion_of(record) or {}
    entry = plans.locked_entry(portion, record) if portion.get("clip") else None
    refs = {}
    for ref, then in (studio.get("files") or {}).items():
        shas = (studio.get("refs") or {}).get(ref) or {}
        refs[ref] = {kind: {"then": _file_info(project, (then or {}).get(kind), shas.get(kind))} for kind in ("image", "voice")}
    return {"clip": index, "snapshot": entry, "edit_instruction": ((entry or {}).get("defs") or {}).get("edit_instruction"),
            "raw_start": studio.get("raw_start"), "branch": studio.get("branch"), "predecessor": studio.get("predecessor"),
            "size": [record.get("width"), record.get("height")], "refs": refs, "upscale": studio.get("upscale"),
            # what the generation used besides the plan (the « Generation » block of the window)
            "generation": {"models": studio.get("models"), "extra_loras": studio.get("extra_loras"),
                           "ref_image_size": studio.get("ref_image_size"), "song": studio.get("song_file")},
            "seed": record.get("seed"), "saved_at": record.get("saved_at"), "parent": record.get("parent")}
