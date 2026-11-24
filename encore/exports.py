"""Encore - the assembled videos in a project's exports/ folder.

Pure functions, no state: the file name of a new export, its information files (.infos.json and .infos.md: the
plan, and for each clip its place in the video, take, seed and settings), and the list shown in the side pane.
Used by the engine (assemblies) and by the server (GET exports).
"""
from __future__ import annotations

from .i18n import t as _t
import json
import os
import re
import time
from pathlib import Path

from . import plan_core, projects, takes


def export_name(project_dir: Path, project, branch_name, when=None, taken=()):
    """projet_branche_AAAA-MM-JJ_HHhMM.mp4 (unique in exports/ and among the assemblies still waiting)."""
    label = re.sub(r"[^\w-]+", "-", branch_name, flags=re.UNICODE).strip("-") or "branch"
    stem = f"{project}_{label}_{time.strftime('%Y-%m-%d_%Hh%M', time.localtime(when or time.time()))}"
    name, number = stem, 2
    while (project_dir / "exports" / f"{name}.mp4").exists() or (project_dir / "exports" / f"{name}.json").exists() or name in taken:
        name, number = f"{stem}_{number}", number + 1
    return name


# --------------------------------------------------------------------------- video information files
def _fmt_time(seconds):
    minutes, sec = divmod(float(seconds), 60)
    return f"{int(minutes)}:{sec:05.2f}"


def _fmt_len(frames):
    if not frames:
        return "—"
    sec = int(frames) / plan_core.FPS
    return f"{sec:.1f} s".replace(".", _t("_decimal", default=".")) if sec < 60 else f"{int(sec // 60)} min {int(round(sec % 60)):02d}"


def _md(text):
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def build_infos(project_dir: Path, job, report=""):
    """Everything about how an assembled video was made: the plan at assembly time, and for each clip its place
    in the video, the take used, its seed and the settings it was really generated with. Returns (json, markdown)."""
    raw = job.get("plan_snapshot") or {}
    plan = plan_core.normalize(json.loads(json.dumps(raw))) if raw else None
    rows = {r["index"]: r for r in plan_core.timeline(plan)} if plan else {}
    clips_by_index = {c["index"]: c for c in (plan or {}).get("clips", [])}
    fps = plan_core.FPS
    first = plan_core.final_start(plan) if plan else 0     # a start video: times counted from the video's first frame
    out_clips = []
    chosen = {str(k): v for k, v in (job.get("takes") or {}).items()}
    for index in range(1, int(job.get("clips") or 0) + 1):
        take_id = chosen.get(str(index))
        row, clip = rows.get(index, {}), clips_by_index.get(index, {})
        record = {}
        try:
            record = json.loads((takes.clip_dir(project_dir, index) / f"{take_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        studio = record.get("studio") or {}
        start = max(row.get("visible", 0), first) - first if (index > 1 or first or (plan or {}).get("start_video")) else 0
        stop = (row.get("end") or 0) - first
        out_clips.append({
            "index": index, "name": clip.get("name") or row.get("name"),
            "video": {"start_frame": start, "end_frame": stop, "start_s": round(start / fps, 3),
                      "end_s": round(stop / fps, 3)},
            "frames": clip.get("frames"), "continue": bool(clip.get("continue")), "context_frames": row.get("context"),
            "lyrics": clip.get("lyrics"),
            "take": {"id": take_id, "seed": record.get("seed"), "parent": record.get("parent"),
                     "saved": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record["saved_at"])) if record.get("saved_at") else None,
                     "missing": not record},
            "generation": {"width": record.get("width"), "height": record.get("height"),
                           "ref_image_size": studio.get("ref_image_size"), "models": studio.get("models"),
                           "upscale": studio.get("upscale"), "song": studio.get("song_file"),
                           "extra_loras": studio.get("extra_loras") or [],
                           "references": {n: {"image": f.get("image"), "voice": f.get("voice"),
                                              "sha": (studio.get("refs") or {}).get(n)} for n, f in (studio.get("files") or {}).items()}},
            "refs": clip.get("refs"),
            "prompt": clip.get("prompt"),
        })
    size = job.get("size") or [None, None]
    end = (rows.get(int(job.get("clips") or 0), {}).get("end") or 0) - first
    created = time.strftime("%Y-%m-%d %H:%M:%S")
    sv = (plan or {}).get("start_video")
    ev = (plan or {}).get("edit_video")
    data = {
        "video": {"file": f"{job['export']}.mp4", "project": job["project"], "created": created,
                  "studio_version": projects.STUDIO_VERSION, "clips": job.get("clips"),
                  "duration_s": round(end / fps, 3), "frames": end, "fps": fps, "size": size,
                  "crf": job.get("crf"), "comfy_prompt_id": job.get("prompt_id")},
        "branch": {"id": job.get("branch"), "name": job.get("branch_name"), "size": size,
                    "ref_image_size": job.get("ref_image_size"), "song": job.get("song_file")},
        "clips": out_clips,
        **({"start_video": {"ref": sv["ref"], "file": ((job.get("spec") or {}).get("start_video") or {}).get("video"),
                            "segment_s": [round(sv["start_frame"] / fps, 3), round(sv["end_frame"] / fps, 3)],
                            "in_video": sv["in_assembly"], "song": sv["song"]}} if sv else {}),
        **({"edit_video": {"ref": ev["ref"], "file": ((job.get("spec") or {}).get("edit_video") or {}).get("video"),
                           "segment_s": [round(ev["start_frame"] / fps, 3), round(ev["end_frame"] / fps, 3)],
                           "sound": ev["sound"]}} if ev else {}),
        "assembly_report": report,
        "plan": raw,
    }
    md = [f"# {job['export']}.mp4", "",
          _t("engine.project_branch", v0=job['project'], v1=job.get('branch_name')),
          _t("engine.assembled_on_encore", created=created, STUDIO_VERSION=projects.STUDIO_VERSION),
          _t("engine.clips_1_to_frames_at_fps", v0=job.get('clips'), v1=_fmt_time(end / fps), end=end, fps=fps, v4=size[0], v5=size[1], v6=job.get('crf')),
          _t("engine.song_reference_size", v0=job.get('song_file') or '—', v1=job.get('ref_image_size') or '—'), ""]
    md += ["## Clips", "",
          _t("engine.clip_length_start_end_take_seed"),
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in out_clips:
        g, m = c["generation"], (c["generation"].get("models") or {})
        loras = ", ".join(f"{l.get('name')} ({l.get('strength')})" for l in (m.get("loras") or [])) or _t("engine.no_lora")
        up = g.get("upscale")
        md.append("| " + " | ".join(_md(v) for v in [
            c["index"], c["name"], _fmt_len(c["frames"]), _fmt_time(c["video"]["start_s"]), _fmt_time(c["video"]["end_s"]),
            (_t("engine.take_not_found") if c["take"]["missing"] else "") + str(c["take"]["id"]), c["take"]["seed"],
            f"{g.get('width')} × {g.get('height')}" if g.get("width") else "—",
            f"{m.get('unet_name') or '—'} · {loras}", f"{m.get('sampler_name') or '—'} / {m.get('scheduler') or '—'}",
            m.get("steps") or "—", up.get("summary") if up else _t("engine.no")]) + " |")
    md += ["", _t("engine.clip_details"), ""]
    for c in out_clips:
        m = c["generation"].get("models") or {}
        md += [f"### {c['index']}. {c['name']}", "",
               _t("engine.in_the_video_frames_to_clip", v0=_fmt_time(c['video']['start_s']), v1=_fmt_time(c['video']['end_s']), v2=c['video']['start_frame'], v3=c['video']['end_frame'], v4=_fmt_len(c['frames']), v5=c['frames'])
               + (_t("engine.seam_of_frames_with_the_previous", v0=c['context_frames']) if c["continue"] and c["context_frames"] else _t("engine.scene_start")),
               _t("engine.take_seed_made_on", v0=c['take']['id'], v1=c['take']['seed'], v2=c['take']['saved'] or '—')
               + (_t("engine.following", v0=c['take']['parent']) if c["take"]["parent"] else ""),
               _t("engine.model_sigmashift_steps", v0=m.get('unet_name') or '—', v1=m.get('weight_dtype') or '—', v2=m.get('shift_video'), v3=m.get('shift_audio'), v4=m.get('sampler_name'), v5=m.get('scheduler'), v6=m.get('steps'))
               + (" · LoRA " + ", ".join(f"{l.get('name')} ({l.get('strength')})" for l in m.get("loras")) if m.get("loras") else ""),
               _t("engine.references") + (", ".join(f"{n} = {r.get('image') or '—'}" + (f" + {r['voice']}" if r.get("voice") else "")
                                              for n, r in c["generation"]["references"].items()) or "—")]
        if c["generation"].get("extra_loras"):
            md.append(_t("engine.lora_of_this_take_only_on")
                      + ", ".join(f"{l.get('name')} ({l.get('strength')})" for l in c["generation"]["extra_loras"]))
        if c["generation"].get("upscale"):
            md.append(_t("engine.latent_upscale_line", summary=c['generation']['upscale'].get('summary')))
        if c.get("lyrics"):
            md.append(_t("engine.lyrics", v0=c['lyrics']))
        md += ["", "```text", str(c.get("prompt") or "").strip(), "```", ""]
    return data, "\n".join(md) + "\n"


def write_infos(project_dir: Path, job, report=""):
    data, md = build_infos(project_dir, job, report)
    folder = project_dir / "exports"
    for name, text in ((f"{job['export']}.infos.json", json.dumps(data, indent=2, ensure_ascii=False) + "\n"),
                       (f"{job['export']}.infos.md", md)):
        tmp = folder / (name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, folder / name)


def list_exports(project_dir: Path):
    out = []
    folder = project_dir / "exports"
    try:
        branch_ids = {b["id"] for b in projects.read_meta(project_dir)["branches"]}
    except (OSError, ValueError, KeyError):
        branch_ids = None
    if folder.is_dir():
        for meta in folder.glob("*.json"):
            if meta.name.endswith(".infos.json"):
                continue
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (folder / f"{meta.stem}.mp4").is_file():
                info["file"] = f"exports/{meta.stem}.mp4"
                info["infos"] = f"exports/{meta.stem}.infos.md" if (folder / f"{meta.stem}.infos.md").is_file() else None
                # its branch was deleted (its videos are deleted with it; an old one left over is hidden)
                info["removed"] = bool(branch_ids is not None and info.get("branch") and info["branch"] not in branch_ids)
                out.append(info)
    out.sort(key=lambda e: e.get("created", 0), reverse=True)
    return out
