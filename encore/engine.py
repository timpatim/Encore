"""Encore - generations: the Studio decides, ComfyUI only computes.

For each generation the Studio
  1. sends ComfyUI what the existing ComfyUI-H3-ClipPlan nodes read: the plan, the reference
     files and, for a continuation, the take it continues (with the takes that one is built on);
  2. builds the workflow (Reference, Voice, Clip, sampler, SaveLatent, preview) and queues it;
  3. follows it (websocket for the progress, /queue and /history for the end);
  4. copies the new take (latent, signature, preview) into the project and chooses it.

ComfyUI's side is a working copy, under names of its own so that it never mixes with the plans
used directly in ComfyUI:
    input/h3studio/<project>/plan.json, reference files       (sent by the Studio)
    output/h3_clip_plan/h3studio_<project>/latents, clips      (takes being made or continued)
When no generation of the project is waiting any more, that working copy is emptied (configurable):
the takes are in the project, and leftovers must not interfere with the next generations.
"""
from __future__ import annotations

from .i18n import t as _t
import base64
import json
import os
import random
import re
import threading
import time
import uuid
from pathlib import Path

from . import assembler, checkpoints, comfy, comfy_setup, plan_core, projects, takeplan, takes
from .projects import StudioError

MIRROR_PREFIX = "h3studio_"
INPUT_DIR = "h3studio"
STEP_KEYS = {"20": "engine.preparing", "25": "engine.generating", "26": "engine.saving", "27": "engine.decoding", "28": "engine.preview", "10": "engine.assembling"}
NEEDED_NODES = ["UNETLoader", "CLIPLoader", "VAELoader", "MiniMaxH3SigmaShift", "MiniMaxH3AudioVAECompatibility",
                "RandomNoise", "BasicGuider", "KSamplerSelect", "BasicScheduler", "SamplerCustomAdvanced", "VAEDecode",
                "VHS_VideoCombine", "H3PlanClip", "H3PlanSaveLatent", "H3PlanReference", "H3PlanVoice"]
ACTIVE = ("queued", "running")


def mirror_name(project: str, branch: str) -> str:
    """ComfyUI's working copy of one branch (the plugin compares takes with each other: one set per copy)."""
    return f"{MIRROR_PREFIX}{project}__{branch}"


def plan_file_of(project: str, branch: str) -> str:
    return f"{INPUT_DIR}/{project}/{branch}/plan.json"


# --------------------------------------------------------------------------- workflow (API format)
def _model_chain(p, s):
    p["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": s["unet_name"], "weight_dtype": s["weight_dtype"]}}
    model = ["1", 0]
    if s.get("attention"):
        p["2"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": model, "attention": s["attention"]}}
        model = ["2", 0]
    for number, lora in enumerate(projects.active_loras(s)):      # LoRA stack: one loader after the other
        node = str(40 + number)
        p[node] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": lora["name"],
                                                                  "strength_model": float(lora["strength"])}}
        model = [node, 0]
    if s.get("preview_mode") == "kj":                            # KJNodes live preview (TAE, animated, with sound)
        inputs = {"model": model, "max_resolution": int(s.get("kj_max_res", 512)), "jpeg_quality": int(s.get("kj_quality", 80)),
                  "suppress_default_preview": True, "preview_frames": int(s.get("_kj_frames_value", 1)),
                  "preview_fps": int(s.get("kj_fps", 7)), "tiny_vae": s.get("kj_tiny_vae") or "none"}
        if s.get("kj_audio"):
            inputs["audio_vae"] = ["8", 0]
        p["45"] = {"class_type": "ModelPreviewOverrideKJ", "inputs": inputs}
        model = ["45", 0]
    p["4"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": model, "shift_video": float(s["shift_video"]),
                                                              "shift_audio": float(s["shift_audio"])}}
    return ["4", 0]


def clip_workflow(job):
    """job: plan_file, clip_index, mode, refs [{name, image, voice}] (ComfyUI paths), song (ComfyUI path),
    take_token, parent_token, seed, settings."""
    s = job["settings"]
    p = {}
    model = _model_chain(p, s)
    p["5"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": s["clip_name"], "type": s["clip_type"], "device": "default"}}
    p["6"] = {"class_type": "VAELoader", "inputs": {"vae_name": s["video_vae"]}}
    p["7"] = {"class_type": "VAELoader", "inputs": {"vae_name": s["audio_vae"]}}
    p["8"] = {"class_type": "MiniMaxH3AudioVAECompatibility", "inputs": {"audio_vae": ["7", 0]}}
    free = job["mode"] == "free"
    if not free:
        p["9"] = {"class_type": "LoadAudio", "inputs": {"audio": job["song"]}}
    refs, node = None, 30
    for ref in job["refs"]:
        if ref.get("image"):
            inputs = {"name": ref["name"], "image": ref["image"]}
            if refs:
                inputs["references"] = refs
            p[str(node)] = {"class_type": "H3PlanReference", "inputs": inputs}
            refs, node = [str(node), 0], node + 1
        if ref.get("voice") and free:
            inputs = {"name": ref["name"], "voice_file": ref["voice"]}
            if refs:
                inputs["references"] = refs
            p[str(node)] = {"class_type": "H3PlanVoice", "inputs": inputs}
            refs, node = [str(node), 0], node + 1
        if ref.get("video"):
            refs, node = _video_node(p, node, ref, refs)
    clip = {"clip": ["5", 0], "vae": ["6", 0], "audio_vae": ["8", 0], "plan_file": job["plan_file"],
            "clip_index": int(job["clip_index"]), "seed_mode": "plan", "width": int(s["width"]), "height": int(s["height"]),
            "take_token": job["take_token"], "parent_token": job.get("parent_token") or "", "seed_override": int(job["seed"])}
    if not free:
        clip["master_audio"] = ["9", 0]
    if refs:
        clip["references"] = refs
    p["20"] = {"class_type": "H3PlanClip", "inputs": clip}
    p["21"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": ["20", 3]}}
    p["22"] = {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": ["20", 0]}}
    p["23"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": s["sampler_name"]}}
    p["24"] = {"class_type": "BasicScheduler", "inputs": {"model": model, "scheduler": s["scheduler"], "steps": int(s["steps"]), "denoise": 1.0}}
    p["25"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["21", 0], "guider": ["22", 0], "sampler": ["23", 0],
                                                                 "sigmas": ["24", 0], "latent_image": ["20", 1]}}
    p["26"] = {"class_type": "H3PlanSaveLatent", "inputs": {"latent": ["25", 0], "plan_clip": ["20", 5], "delete_stale": False,
                                                            "audio_vae": ["8", 0]}}
    p["27"] = {"class_type": "VAEDecode", "inputs": {"samples": ["26", 0], "vae": ["6", 0]}}
    p["28"] = {"class_type": "VHS_VideoCombine", "inputs": {
        "images": ["27", 0], "audio": ["26", 1] if free else ["20", 2], "frame_rate": 24, "loop_count": 0,
        "filename_prefix": ["20", 4], "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": int(s["crf"]),
        "save_metadata": False, "trim_to_audio": False, "pingpong": False, "save_output": True}}
    if job.get("upscale"):
        add_upscale(p, job, model)
    return p


def _video_node(p, node, ref, refs):
    """An « H3 Plan - Video » node (the start video) in the chain of references."""
    inputs = {"name": ref["name"], "video_file": ref["video"]}
    if refs:
        inputs["references"] = refs
    p[str(node)] = {"class_type": "H3PlanVideo", "inputs": inputs}
    return [str(node), 0], node + 1


def assemble_workflow(plan_file, mode, last_clip, settings, song=None, start_video=None, size=None, edit_video=None):
    """The plugin's assembly node: the selection of ComfyUI's working copy, clips 1 to last_clip.
    start_video: {"name", "video"} (ComfyUI path) when the segment opens the video;
    edit_video: the same for the edited video, when the final video keeps its original sound."""
    p = {"1": {"class_type": "VAELoader", "inputs": {"vae_name": settings["video_vae"]}}}
    inputs = {"video_vae": ["1", 0], "plan_file": plan_file, "last_clip": int(last_clip), "crf": int(settings["crf"])}
    if mode == "free" or start_video:
        p["2"] = {"class_type": "VAELoader", "inputs": {"vae_name": settings["audio_vae"]}}
        p["4"] = {"class_type": "MiniMaxH3AudioVAECompatibility", "inputs": {"audio_vae": ["2", 0]}}
        inputs["audio_vae"] = ["4", 0] if start_video else ["2", 0]
    if start_video:
        refs, _node = _video_node(p, 30, start_video, None)
        inputs.update(references=refs, width=int(size[0]), height=int(size[1]))
    if edit_video:
        refs, _node = _video_node(p, 30, edit_video, None)
        inputs["references"] = refs
    if mode != "free":
        p["3"] = {"class_type": "LoadAudio", "inputs": {"audio": song}}
        inputs["master_audio"] = ["3", 0]
    p["10"] = {"class_type": "H3PlanAssemble", "inputs": inputs}
    return p


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
                  "crf": job.get("crf"), "checkpoint": job.get("checkpoint"), "comfy_prompt_id": job.get("prompt_id")},
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
        "invalidated_takes": (job.get("rewrite") or {}).get("invalid") or [],
        "warnings": (job.get("rewrite") or {}).get("warnings") or [],
        "plan": raw,
    }
    md = [f"# {job['export']}.mp4", "",
          _t("engine.project_branch", v0=job['project'], v1=job.get('branch_name')),
          _t("engine.assembled_on_encore", created=created, STUDIO_VERSION=projects.STUDIO_VERSION),
          _t("engine.clips_1_to_frames_at_fps", v0=job.get('clips'), v1=_fmt_time(end / fps), end=end, fps=fps, v4=size[0], v5=size[1], v6=job.get('crf')),
          _t("engine.song_reference_size", v0=job.get('song_file') or '—', v1=job.get('ref_image_size') or '—'),
          _t("engine.linked_checkpoint", v0=job.get('checkpoint') or '—'), ""]
    rewrite = job.get("rewrite") or {}
    if rewrite:
        md += [_t("engine.invalid_takes_heading"), "", _t("engine.invalid_takes_intro"), ""]
        md += [_t("engine.invalid_take_line", clip=i["clip"], take=i["take"], reason=i.get("reason") or "—")
               for i in rewrite.get("invalid") or []] or [_t("engine.invalid_takes_none")]
        md += [f"- ⚠ {w}" for w in rewrite.get("warnings") or []]
        md.append("")
    md += ["## Clips", "",
          _t("engine.clip_length_start_end_take_seed"),
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    invalid_ids = {i["take"] for i in (job.get("rewrite") or {}).get("invalid") or []}
    for c in out_clips:
        g, m = c["generation"], (c["generation"].get("models") or {})
        loras = ", ".join(f"{l.get('name')} ({l.get('strength')})" for l in (m.get("loras") or [])) or _t("engine.no_lora")
        up = g.get("upscale")
        md.append("| " + " | ".join(_md(v) for v in [
            c["index"], c["name"], _fmt_len(c["frames"]), _fmt_time(c["video"]["start_s"]), _fmt_time(c["video"]["end_s"]),
            (_t("engine.take_not_found") if c["take"]["missing"] else "") + ("⚠ " if c["take"]["id"] in invalid_ids else "")
            + str(c["take"]["id"]), c["take"]["seed"],
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
                # its branch was deleted: hidden in the side pane, back when a checkpoint restores the branch
                info["removed"] = bool(branch_ids is not None and info.get("branch") and info["branch"] not in branch_ids)
                out.append(info)
    out.sort(key=lambda e: e.get("created", 0), reverse=True)
    return out


def clip_needs(plan, index, settings):
    """References of a clip with the project files chosen for them, and what is missing."""
    clip = plan["clips"][index - 1]
    free = plan["mode"] == "free"
    used = plan_core.PLACEHOLDER_RE.findall(clip["prompt"])
    numbered = "<Picture " in clip["prompt"] and not used
    problems, refs = [], []
    for name in clip["refs"]:
        chosen = (settings.get("refs") or {}).get(name) or {}
        wants_image = any(kind == "picture" and n == name for kind, n in used) or numbered
        if wants_image and not chosen.get("image"):
            problems.append(_t("engine.picture_of_not_chosen", name=name))
        refs.append({"name": name, "image": chosen.get("image") or None, "voice": (chosen.get("voice") or None) if free else None})
    if not free and not settings.get("song"):
        problems.append(_t("engine.song_not_chosen"))
    spec = plan.get("start_video")
    if index == 1 and clip["continue"] and spec:      # clip 1 continues the start video
        chosen = (settings.get("refs") or {}).get(spec["ref"]) or {}
        if not chosen.get("video"):
            problems.append(_t("engine.start_video_not_chosen"))
        refs.append({"name": spec["ref"], "image": None, "voice": None, "video": chosen.get("video") or None})
    edit = plan.get("edit_video")
    if edit and plan_core.edit_slice(plan, index):    # the clips inside the segment edit their slice of the video
        chosen = (settings.get("refs") or {}).get(edit["ref"]) or {}
        if not chosen.get("video"):
            problems.append(_t("engine.edit_video_not_chosen"))
        refs.append({"name": edit["ref"], "image": None, "voice": None, "video": chosen.get("video") or None})
    return refs, problems


def kj_frames_value(info, settings):
    """preview_frames for KJNodes: -1 = the whole clip (sent as -1 if the node accepts it, else its maximum)."""
    wanted = int(settings.get("kj_frames", -1))
    spec = (((info.get("ModelPreviewOverrideKJ") or {}).get("input") or {}).get("required") or {}).get("preview_frames") \
        or (((info.get("ModelPreviewOverrideKJ") or {}).get("input") or {}).get("optional") or {}).get("preview_frames")
    options = spec[1] if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict) else {}
    low, high = int(options.get("min", 1)), int(options.get("max", 1024))
    if wanted <= 0:
        return -1 if low <= -1 else high
    return max(low, min(high, wanted))


# --------------------------------------------------------------------------- latent upscale
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)       # H3 video latent: frames covered by each latent frame
UPSCALER_NODES = {"lbh3d": ["MinimaxH3LatentUpscaler3D"], "lbh2d": ["MinimaxH3LatentUpscalerNode2D"],
                  "builtin": ["LatentUpscaleModelLoader", "MiniMaxH3LatentUpscaleWithModel"]}
UPSCALE_NODES = ["LTXVSeparateAVLatent", "LTXVConcatAVLatent", "LatentUpscale", "LatentCut", "ReplaceVideoLatentFrames",
                 "SplitSigmas", "ManualSigmas"]
UPSCALER_LABEL = {"lbh3d": "LBH 3D", "lbh2d": "LBH 2D", "builtin": "ComfyUI"}


def latent_frames(pixels):
    """Number of H3 latent frames that hold the first `pixels` frames."""
    count, total = 0, 0
    while total < pixels:
        total += FRAME_PER_TOKEN[count % 5]
        count += 1
    if total != pixels:
        raise StudioError(_t("engine.frames_do_not_fall_on_an", pixels=pixels))
    return count


def parse_sigmas(text, label):
    try:
        values = [float(v) for v in str(text or "").replace(";", ",").split(",") if v.strip()]
    except ValueError:
        raise StudioError(_t("engine.invalid_list_of_noise_levels_numbers", label=label)) from None
    if len(values) < 2 or any(b >= a for a, b in zip(values, values[1:])) or values[-1] < 0 or values[0] > 1.5:
        raise StudioError(_t("engine.at_least_two_decreasing_noise_levels", label=label))
    return values


def upscale_plan(up, width, height, steps):
    """Checks a branch's upscale settings for one generation; returns what the workflow needs."""
    if up.get("upscaler") not in UPSCALER_NODES:
        raise StudioError(_t("engine.upscale_unknown_upscaler"))
    if not str(up.get("model") or "").strip():
        raise StudioError(_t("engine.upscale_choose_the_upscale_model_file"))
    w0, h0 = projects.start_size(up.get("start_mp") or 0.2, width, height)
    if w0 >= width or h0 >= height:
        raise StudioError(_t("engine.upscale_the_start_size_is_not", w0=w0, h0=h0, width=width, height=height))
    factor = ((width / w0) + (height / h0)) / 2
    if up["upscaler"] != "builtin" and factor > 4:
        raise StudioError(_t("engine.upscale_factor_too_large_4_at", v0=f"{factor:.2f}"))
    plan = {"upscaler": up["upscaler"], "model": up["model"], "sharpness": int(up.get("sharpness") or 1),
            "w0": w0, "h0": h0, "factor": round(factor, 2), "start_mp": float(up.get("start_mp") or 0.2),
            "pass2_loras": up.get("pass2_loras"), "pass2_sampler": up.get("pass2_sampler") or ""}
    if up.get("pass1_mode") == "manual":
        plan["pass1"] = {"sigmas": parse_sigmas(up.get("pass1_sigmas"), _t("engine.upscale_pass", n=1))}
        p1 = len(plan["pass1"]["sigmas"]) - 1
    else:
        split = int(up.get("pass1_steps") or 0)
        if not 1 <= split < int(steps):
            raise StudioError(_t("engine.upscale_pass_1_must_have_1", v0=int(steps) - 1, v1=int(steps)))
        plan["pass1"] = {"split": split}
        p1 = split
    if up.get("pass2_mode") == "rest":
        if "split" not in plan["pass1"]:
            raise StudioError(_t("engine.upscale_rest_of_the_schedule_in"))
        plan["pass2"] = {"rest": True}
        p2 = int(steps) - plan["pass1"]["split"]
    else:
        plan["pass2"] = {"sigmas": parse_sigmas(up.get("pass2_sigmas"), _t("engine.upscale_pass", n=2))}
        p2 = len(plan["pass2"]["sigmas"]) - 1
    plan["steps"] = [p1, p2]
    plan["summary"] = (_t("engine.mp_st_st", v0=f"{plan['start_mp']:g}", w0=w0, h0=h0, p1=p1, v4=f"{plan['factor']:g}", v5=UPSCALER_LABEL[up['upscaler']], width=width, height=height, p2=p2))
    return plan


def _pass2_model(p, s, loras):
    """Model of the second pass when it uses other LoRA than the first one."""
    model = ["2", 0] if s.get("attention") else ["1", 0]
    for number, lora in enumerate(projects.active_loras({"loras": loras})):
        node = str(80 + number)
        p[node] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": lora["name"],
                                                                  "strength_model": float(lora["strength"])}}
        model = [node, 0]
    p["79"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": model, "shift_video": float(s["shift_video"]),
                                                               "shift_audio": float(s["shift_audio"])}}
    return ["79", 0]


def add_upscale(p, job, model):
    """Turn the single sampling of clip_workflow into: first pass at the start size, latent upscale, second pass
    at the branch size. The latent prepared by H3PlanClip at the branch size (continuation frames, song and their
    noise masks) is split and recombined with ComfyUI's own nodes, so the plugin is unchanged."""
    s, up = job["settings"], job["upscale"]
    width, height = int(s["width"]), int(s["height"])
    music = job["mode"] != "free"
    p["60"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["20", 1]}}
    # first pass: the prepared video shrunk to the start size (LatentUpscale counts latents in eighths, H3 in sixteenths)
    p["61"] = {"class_type": "LatentUpscale", "inputs": {"samples": ["60", 0], "upscale_method": "bilinear",
                                                         "width": up["w0"] // 2, "height": up["h0"] // 2, "crop": "disabled"}}
    p["62"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["61", 0], "audio_latent": ["60", 1]}}
    if "split" in up["pass1"]:
        p["63"] = {"class_type": "SplitSigmas", "inputs": {"sigmas": ["24", 0], "step": int(up["pass1"]["split"])}}
        sigmas1 = ["63", 0]
    else:
        p["64"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": ", ".join(f"{v:g}" for v in up["pass1"]["sigmas"])}}
        sigmas1 = ["64", 0]
    p["25"]["inputs"]["sigmas"] = sigmas1
    p["25"]["inputs"]["latent_image"] = ["62", 0]
    # the estimate of the clean video after the first pass, upscaled to the branch size
    p["66"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["25", 1]}}
    if up["upscaler"] == "builtin":
        p["67"] = {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": up["model"]}}
        p["68"] = {"class_type": "MiniMaxH3LatentUpscaleWithModel", "inputs": {"model": ["67", 0], "samples": ["66", 0],
                                                                               "width": width, "height": height}}
    elif up["upscaler"] == "lbh3d":
        p["68"] = {"class_type": "MinimaxH3LatentUpscaler3D", "inputs": {
            "latent": ["66", 0], "model_name": up["model"], "mode": "target dimensions", "mode.width": width, "mode.height": height,
            "align": 32, "enable_temporal_chunking": True, "force_unload": True, "device": "cuda", "precision": "fp16"}}
    else:
        p["68"] = {"class_type": "MinimaxH3LatentUpscalerNode2D", "inputs": {
            "latent": ["66", 0], "model_name": up["model"], "mode": "target dimensions", "mode.width": width, "mode.height": height,
            "sharpness": up["sharpness"], "align": 32, "temporal_chunking": "chunked", "temporal_chunking.chunk_frames": 32,
            "force_unload": True, "device": "cuda", "precision": "fp16"}}
    # exactly the branch size (an upscaler may round differently)
    p["69"] = {"class_type": "LatentUpscale", "inputs": {"samples": ["68", 0], "upscale_method": "bilinear",
                                                         "width": width // 2, "height": height // 2, "crop": "disabled"}}
    video = ["69", 0]
    if job.get("context_latent"):
        # the frames continued from the previous clip go back as they were, with the prepared noise mask
        p["70"] = {"class_type": "LatentCut", "inputs": {"samples": ["60", 0], "dim": "t", "index": 0,
                                                         "amount": int(job["context_latent"])}}
        p["71"] = {"class_type": "ReplaceVideoLatentFrames", "inputs": {"destination": ["69", 0], "source": ["70", 0], "index": 0}}
        video = ["71", 0]
    # sound: the song (music video) as prepared; in free mode, what the first pass made of it
    p["72"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": video, "audio_latent": ["60", 1] if music else ["66", 1]}}
    model2, guider2, sampler2 = model, ["22", 0], ["23", 0]
    if up.get("pass2_loras") is not None:
        model2 = _pass2_model(p, s, up["pass2_loras"])
        p["73"] = {"class_type": "BasicGuider", "inputs": {"model": model2, "conditioning": ["20", 0]}}
        guider2 = ["73", 0]
    if up.get("pass2_sampler"):
        p["74"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": up["pass2_sampler"]}}
        sampler2 = ["74", 0]
    if up["pass2"].get("rest"):
        sigmas2 = ["63", 1]
    else:
        p["65"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": ", ".join(f"{v:g}" for v in up["pass2"]["sigmas"])}}
        sigmas2 = ["65", 0]
    p["75"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["21", 0], "guider": guider2, "sampler": sampler2,
                                                                 "sigmas": sigmas2, "latent_image": ["72", 0]}}
    p["26"]["inputs"]["latent"] = ["75", 0]
    return p


def missing_nodes(info, settings, music=False, upscale=None, video=False):
    need = list(NEEDED_NODES)
    if video:
        need.append("H3PlanVideo")
    if upscale:
        need += UPSCALE_NODES + UPSCALER_NODES[upscale["upscaler"]]
        if upscale.get("pass2_loras"):
            need.append("LoraLoaderModelOnly")
    if settings.get("attention"):
        need.append("ModelAttentionBackend")
    if projects.active_loras(settings):
        need.append("LoraLoaderModelOnly")
    if music:
        need.append("LoadAudio")
    if settings.get("preview_mode") == "kj":
        need.append("ModelPreviewOverrideKJ")
    missing = [n for n in need if n not in info]
    clip = info.get("H3PlanClip")
    if clip and "take_token" not in ((clip.get("input") or {}).get("optional") or {}):
        missing.append(_t("engine.h3planclip_up_to_date_plugin_comfyui"))
    elif clip and "H3PlanVideo" not in info and "H3PlanVideo" not in missing:
        missing.append(_t("engine.plugin_too_old_plan_v4"))     # plans are version 4 since Encore 0.30
    return missing


# --------------------------------------------------------------------------- preview diagnostic
class Diagnostic:
    """While generations run, writes what ComfyUI sends on its websocket to diagnostic_apercu.log
    (next to Encore.bat), and keeps the first preview images in diagnostic_apercu/."""
    MAX_LINES = 20000
    MAX_IMAGES = 20

    def __init__(self, folder: Path):
        self.log_path = folder / "diagnostic_apercu.log"
        self.image_dir = folder / "diagnostic_apercu"
        self.lines = 0
        self.images = 0
        self.lock = threading.Lock()
        self.started = False

    def _write(self, text):
        with self.lock:
            if self.lines >= self.MAX_LINES:
                return
            try:
                if not self.started:
                    self.started = True
                    with open(self.log_path, "a", encoding="utf-8") as handle:
                        handle.write(f"\n===== Encore {projects.STUDIO_VERSION} - session {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
                with open(self.log_path, "a", encoding="utf-8") as handle:
                    handle.write(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {text}\n")
                self.lines += 1
            except OSError:
                pass

    def save_image(self, data: bytes, mime: str, label: str):
        with self.lock:
            if self.images >= self.MAX_IMAGES:
                return None
            self.images += 1
            number = self.images
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "video/mp4": ".mp4"}.get(mime, ".bin")
        try:
            self.image_dir.mkdir(exist_ok=True)
            name = f"{number:02d}_{label}{ext}"
            (self.image_dir / name).write_bytes(data)
            return name
        except OSError:
            return None

    @staticmethod
    def _short(value, depth=0):
        if isinstance(value, str):
            return value if len(value) <= 160 else f"{value[:60]}…[{len(value)} car.]"
        if isinstance(value, dict):
            return {k: Diagnostic._short(v, depth + 1) for k, v in list(value.items())[:40]}
        if isinstance(value, list):
            return [Diagnostic._short(v, depth + 1) for v in value[:20]] + ([_t("engine.items", v0=len(value))] if len(value) > 20 else [])
        return value

    def json_message(self, msg):
        kind = msg.get("type")
        self._write(f"JSON type={kind} data={json.dumps(self._short(msg.get('data')), ensure_ascii=False)[:1500]}")

    def binary_message(self, info, raw: bytes):
        meta = info.get("metadata")
        line = _t("engine.binary_event_size_start", v0=info.get('event'), v1=info.get('size'), v2=raw[:16].hex())
        if "image" in info:
            line += _t("engine.image_bytes", v0=info.get('mime'), v1=len(info['image']), v2=image_size(info['image']))
            saved = self.save_image(info["image"], info.get("mime"), f"binaire_e{info.get('event')}")
            if saved:
                line += f" -> {saved}"
        if meta is not None:
            line += _t("engine.metadata", v0=json.dumps(self._short(meta), ensure_ascii=False)[:600])
        self._write(line)

    def note(self, text):
        self._write(text)


def image_size(data: bytes) -> str:
    """'LxH' read from a PNG, JPEG, WebP or GIF header ('' if unknown)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            return f"{w}x{h}"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return f"{int.from_bytes(data[6:8], 'little')}x{int.from_bytes(data[8:10], 'little')}"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                return f"{int.from_bytes(data[24:27], 'little') + 1}x{int.from_bytes(data[27:30], 'little') + 1} (VP8X{' animé' if data[20] & 2 else ''})"
            if chunk == b"VP8 ":
                return f"{int.from_bytes(data[26:28], 'little') & 0x3FFF}x{int.from_bytes(data[28:30], 'little') & 0x3FFF}"
            if chunk == b"VP8L":
                b = data[21:25]
                return f"{((b[1] & 0x3F) << 8 | b[0]) + 1}x{((b[3] & 0xF) << 10 | b[2] << 2 | (b[1] & 0xC0) >> 6) + 1}"
        if data[:3] == b"\xff\xd8\xff":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    return f"{int.from_bytes(data[i + 7:i + 9], 'big')}x{int.from_bytes(data[i + 5:i + 7], 'big')}"
                i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    except (IndexError, ValueError):
        pass
    return ""


# --------------------------------------------------------------------------- engine
def _failed_dep(job):
    """Error message of a job that waited for `job`, which failed."""
    if job.get("kind") == "clip" and job.get("clip"):
        return _t("engine.clip_it_depends_on_has_failed", v0=job['clip'])
    return _t("engine.the_generation_it_depended_on_did")


def _ranges(numbers):
    """[3, 4, 5, 9] -> "3 à 5, 9" """
    runs = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ", ".join(f"{a}" if a == b else _t("engine.to", a=a, b=b) for a, b in runs)


class Engine:
    def __init__(self, studio):
        self.studio = studio
        self.lock = threading.RLock()
        self.launch_lock = threading.RLock()
        self.client_id = "encore-" + uuid.uuid4().hex
        self.jobs = {}              # job id -> job (job["prompt_id"]: its prompt in ComfyUI once dispatched)
        self.order = []             # ids of the jobs waiting in the Studio's own queue, in order (all projects)
        self.paused = False         # nothing new is sent to ComfyUI
        self.loaded = set()         # projects whose jobs.json was read
        self.mirror = {}            # (project, branch) -> {(clip, take id)} present in ComfyUI's working copy
        self.mirror_url = None      # the ComfyUI that mirror describes: another address starts from nothing
        self.comfy_down_at = None   # last time ComfyUI did not answer while jobs were running there
        self.uploaded = {}          # (comfy url, subfolder, name) -> sha already sent
        self.socket = None
        self.socket_url = None
        self.info = None
        self.info_time = 0
        self.previews = {}          # prompt id -> (image bytes, mime type)
        self.local_procs = {}       # job id -> ffmpeg process of an assembly made by Encore
        self.diagnostic = Diagnostic(Path(studio.config_path).resolve().parent) if studio.config.get("diagnostic_preview", False) else None
        self.wake = threading.Event()
        self._load_queue()
        self.poller = threading.Thread(target=self._poll_loop, daemon=True, name="encore-poll")
        self.poller.start()

    # ------------------------------------------------------------------ helpers
    @property
    def client(self):
        return comfy.ComfyClient(self.studio.config["comfy_url"])

    def _project(self, name):
        return projects.project_dir(self.studio.root, name)

    def _comfy_down(self):
        """ComfyUI does not answer: it may come back restarted, or reinstalled with empty folders. A job gone from
        its queue after this was lost by the restart, and what Encore sent it before is sent again."""
        with self.lock:
            self.comfy_down_at = time.time()
            self.uploaded.clear()
            self.mirror, self.mirror_url = {}, None

    def _mirror(self, name, branch):
        """The takes known to be in ComfyUI's copy of a branch; forgotten when the ComfyUI address changes."""
        url = self.studio.config.get("comfy_url")
        if url != self.mirror_url:
            self.mirror, self.mirror_url = {}, url
        return self.mirror.setdefault((name, branch), set())

    def _ensure_socket(self):
        url = self.studio.config["comfy_url"]
        if self.socket and self.socket_url == url and self.socket.is_alive():
            return
        if self.socket:
            self.socket.stop()
        self.socket = comfy.EventSocket(url, self.client_id, self._on_event, on_binary=self._on_binary)
        self.socket_url = url
        self.socket.start()

    def _object_info(self, force=False):
        if force or not self.info or time.time() - self.info_time > 60:
            self.info = self.client.object_info()
            self.info_time = time.time()
        return self.info

    # ------------------------------------------------------------------ persistence of the jobs
    def _jobs_file(self, name):
        return self._project(name) / "jobs.json"

    def _load(self, name):
        if name in self.loaded:
            return
        self.loaded.add(name)
        try:
            data = json.loads(self._jobs_file(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for job in data.get("jobs") or []:
            if job.get("id") and job["id"] not in self.jobs:
                job["progress"] = None
                if job.get("local") and job["status"] in ACTIVE:     # Encore closed during its own assembly
                    job.update(status="queued", local=None, step=None)
                if "dispatched" not in job:         # jobs of earlier versions: sent to ComfyUI at once
                    job["dispatched"], job["prompt_id"] = True, job["id"]
                self.jobs[job["id"]] = job
                if not job.get("dispatched") and job["status"] in ACTIVE and job["id"] not in self.order:
                    self.order.append(job["id"])
        if any(j["status"] in ACTIVE for j in self.jobs.values()):
            self._ensure_socket()
            self.wake.set()

    def _save(self, name):
        keep = [{k: v for k, v in j.items() if k != "progress"} for j in self.jobs.values()
                if j["project"] == name and j["status"] in ACTIVE + ("harvest",)]
        path = self._jobs_file(name)
        try:
            if keep:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps({"jobs": keep}, indent=1, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, path)
            elif path.exists():
                path.unlink()
        except OSError:
            pass

    def _queue_file(self):
        return Path(self.studio.config_path).resolve().parent / "queue.json"

    def _load_queue(self):
        """The Studio's queue (all projects): order of the waiting jobs, pause."""
        try:
            data = json.loads(self._queue_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.paused = bool(data.get("paused"))
        wanted = [(p, i) for p, i in data.get("order") or []]
        for project in dict.fromkeys(p for p, _i in wanted):
            try:
                self._load(project)
            except Exception:  # noqa: BLE001 - a project that cannot be read
                continue
        known = [i for _p, i in wanted if i in self.jobs and not self.jobs[i].get("dispatched") and self.jobs[i]["status"] in ACTIVE]
        self.order = known + [i for i in self.order if i not in known]

    def _save_queue(self):
        data = {"paused": self.paused, "order": [[self.jobs[i]["project"], i] for i in self.order if i in self.jobs]}
        try:
            tmp = self._queue_file().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, self._queue_file())
        except OSError:
            pass

    def _by_prompt(self, prompt_id):
        if not prompt_id:
            return None
        return next((j for j in self.jobs.values() if j.get("prompt_id") == prompt_id), None)

    # ------------------------------------------------------------------ the Studio's queue
    @staticmethod
    def _deps(job):
        """The jobs this one waits for: the generation it continues, and for a planned assembly every generation
        that makes one of its takes."""
        return [d for d in [job.get("parentJob")] + list(job.get("waitFor") or []) if d]

    def _dependents(self, job_id):
        """Jobs waiting for this one (and those waiting for them)."""
        out, todo = [], [job_id]
        while todo:
            current = todo.pop()
            for j in self.jobs.values():
                if current in self._deps(j) and j["status"] in ACTIVE and j["id"] not in out:
                    out.append(j["id"])
                    todo.append(j["id"])
        return out

    def _group_root(self, job):
        """First job of the group: going up the parents still waiting in the queue. A lot (what a ▶▶ launched, with
        its assembly) is one group whatever the links inside it."""
        if job.get("lot"):
            return "L" + job["lot"]
        seen = set()
        while job.get("parentJob") in self.order and job["parentJob"] not in seen:
            seen.add(job["parentJob"])
            job = self.jobs[job["parentJob"]]
        return job["id"]

    def _groups(self):
        """[(root id, [job ids in order])] for the waiting jobs."""
        groups, index = [], {}
        for jid in self.order:
            job = self.jobs.get(jid)
            if not job:
                continue
            root = self._group_root(job)
            if not job.get("lot"):
                top = job
                while top.get("parentJob") in self.jobs and not top.get("lot"):
                    top = self.jobs[top["parentJob"]]
                if top.get("lot") and top["id"] in self.order:
                    root = "L" + top["lot"]
            if root not in index:
                index[root] = len(groups)
                groups.append((root, []))
            groups[index[root]][1].append(jid)
        return groups

    def _enqueue(self, job):
        """A new job: after the last job of its group when it depends on a waiting one, else at the end."""
        parent = job.get("parentJob")
        if parent in self.jobs and self.jobs[parent].get("lot") and not job.get("lot") and parent in self.order:
            job["lot"], job["lot_label"] = self.jobs[parent]["lot"], self.jobs[parent].get("lot_label")
        if job.get("lot"):
            members = [i for i in self.order if self.jobs.get(i, {}).get("lot") == job["lot"]]
            if members and job.get("kind") == "assemble" and parent:
                # an assembly planned on a waiting generation of the lot: right after it, not after the whole lot
                at = self.order.index(parent) + 1 if parent in self.order else self.order.index(members[0])
                self.order.insert(at, job["id"])
                job["suspended"] = bool(self.jobs[members[0]].get("suspended"))
            elif members:
                self.order.insert(max(self.order.index(m) for m in members) + 1, job["id"])
                job["suspended"] = bool(self.jobs[members[0]].get("suspended"))
            else:
                self.order.append(job["id"])
            self._save_queue()
            return
        if parent in self.order:
            root = self._group_root(self.jobs[parent])
            members = dict(self._groups()).get(root, [])
            position = max(self.order.index(m) for m in members) + 1
            self.order.insert(position, job["id"])
            job["suspended"] = bool(self.jobs[parent].get("suspended"))
        else:
            self.order.append(job["id"])
        self._save_queue()

    def queue_state(self):
        """Everything the generation manager shows (all projects)."""
        with self.lock:
            now = time.time()
            estimates = self._estimates(now)
            branch_names = {}
            def describe(job):
                key = job["project"]
                if key not in branch_names:
                    try:
                        branch_names[key] = {b["id"]: (b["name"], b.get("color")) for b in projects.read_meta(self._project(key))["branches"]}
                    except Exception:  # noqa: BLE001
                        branch_names[key] = {}
                name, color = branch_names[key].get(job.get("branch"), (job.get("branch_name") or job.get("branch"), None))
                return dict(self._public(job), **estimates.get(job["id"], {}), project=job["project"], branch_name=name,
                            branch_color=color, dependents=len(self._dependents(job["id"])))
            sent = [describe(j) for j in sorted(self.jobs.values(), key=lambda j: j.get("dispatched_at", 0))
                    if j.get("dispatched") and j["status"] in ACTIVE + ("harvest",)]
            groups = [{"id": root, "suspended": all(self.jobs[i].get("suspended") for i in ids),
                       "label": next((self.jobs[i].get("lot_label") for i in ids if self.jobs[i].get("lot_label")), None),
                       "jobs": [describe(self.jobs[i]) for i in ids]} for root, ids in self._groups()]
            errors = [{"id": j["id"], "project": j["project"], "clip": j.get("clip"), "kind": j["kind"], "error": j.get("error")}
                      for j in self.jobs.values() if j["status"] == "error"]
        return {"paused": self.paused, "comfy_foreign": getattr(self, "comfy_foreign", 0), "sent": sent, "groups": groups, "waiting": sum(len(g["jobs"]) for g in groups), "errors": errors,
                "socket": bool(self.socket and self.socket.connected)}

    def queue_pause(self, mode):
        """mode "after": the job running ends, nothing else starts; "now": it is interrupted and goes back to the
        head of the queue (it will start again from the beginning, same seed)."""
        with self.lock:
            self.paused = True
            self._save_queue()
            sent = [j for j in self.jobs.values() if j.get("dispatched") and j["status"] in ACTIVE] if mode == "now" else []
        if sent:
            client = self.client
            try:
                state = client.queue_state()
                running = {row[1] for row in state.get("queue_running") or []}
                waiting = [j["prompt_id"] for j in sent if j["prompt_id"] not in running]
                if waiting:
                    client.delete_queued(waiting)
                for job in sent:
                    if job["prompt_id"] in running:
                        job["requeue"] = True
                        client.interrupt(job["prompt_id"])
                    else:
                        self._requeue(job)
            except comfy.ComfyError as exc:
                raise StudioError(str(exc)) from exc
        self.wake.set()
        return self.queue_state()

    def queue_resume(self):
        with self.lock:
            self.paused = False
            self._save_queue()
        self.wake.set()
        return self.queue_state()

    def _requeue(self, job):
        """A job interrupted by a pause: back to the head of the queue, as it was when it was launched."""
        with self.lock:
            for key in ("prompt_id", "t_start", "t_sample", "t_step", "t_sample_end", "requeue", "missing", "dispatched_at"):
                job.pop(key, None)
            job.update(status="queued", dispatched=False, progress=None, step=None, error=None, preview=None)
            self.previews.pop(job["id"], None)
            if job["id"] not in self.order:
                self.order.insert(0, job["id"])
            self._save(job["project"])
            self._save_queue()

    def queue_move(self, group, before=None):
        """Moves a whole group before another one (None: at the end). The order inside a group never changes."""
        with self.lock:
            groups = self._groups()
            ids = dict(groups).get(group)
            if not ids:
                raise StudioError(_t("engine.this_group_is_no_longer_in"))
            rest = [(r, m) for r, m in groups if r != group]
            position = next((n for n, (r, _m) in enumerate(rest) if r == before), len(rest))
            rest.insert(position, (group, ids))
            self.order = [i for _r, members in rest for i in members]
            self._save_queue()
        self.wake.set()
        return self.queue_state()

    def queue_suspend(self, group, suspended):
        with self.lock:
            ids = dict(self._groups()).get(group)
            if not ids:
                raise StudioError(_t("engine.this_group_is_no_longer_in"))
            for jid in ids:
                self.jobs[jid]["suspended"] = bool(suspended)
            for name in {self.jobs[i]["project"] for i in ids}:
                self._save(name)
        self.wake.set()
        return self.queue_state()

    def queue_cancel(self, ids):
        """Cancels jobs of any project, and the jobs that depend on them."""
        with self.lock:
            names = {self.jobs[i]["project"] for i in ids if i in self.jobs}
        for name in names:
            self.cancel(name, [i for i in ids if i in self.jobs and self.jobs[i]["project"] == name])
        return self.queue_state()

    # ------------------------------------------------------------------ public API
    def list_jobs(self, name):
        with self.lock:
            self._load(name)
            now = time.time()
            for jid in [j for j, job in self.jobs.items() if job["status"] == "done" and now - job.get("ended", now) > 60]:
                del self.jobs[jid]
            estimates = self._estimates(now)
            jobs = [dict(self._public(j), **estimates.get(j["id"], {})) for j in self.jobs.values() if j["project"] == name]
        jobs.sort(key=lambda j: j["created"])
        return {"jobs": jobs, "socket": bool(self.socket and self.socket.connected), "paused": self.paused}

    # ------------------------------------------------------------------ time estimates
    # Durations of past generations, per unit of work (pixels x frames), kept next to config.json:
    #   prep  seconds before sampling starts (models, encoding)      - not scaled
    #   step  seconds per sampling step and per unit
    #   post  seconds after sampling (decoding, preview, copy) per unit
    #   unit  seconds per unit for an assembly
    def _timings_path(self):
        return Path(self.studio.config_path).resolve().parent / "timings.json"

    def _timings(self):
        if getattr(self, "_timings_cache", None) is None:
            try:
                self._timings_cache = json.loads(self._timings_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._timings_cache = {"clip": [], "assemble": []}
        return self._timings_cache

    def _record_timing(self, job):
        units, end = job.get("units"), job.get("ended") or time.time()
        if not units or not job.get("t_start"):
            return
        data = self._timings()
        if job.get("kind") == "assemble":
            entry = {"unit": (end - job["t_start"]) / units}
            data.setdefault("assemble", []).append(entry)
        elif job.get("upscale"):
            data.setdefault("clip_upscale", []).append({"unit": (end - job["t_start"]) / units})
        else:
            if not (job.get("t_sample") and job.get("t_sample_end") and job.get("steps")):
                return
            entry = {"prep": job["t_sample"] - job["t_start"],
                     "step": (job["t_sample_end"] - job["t_sample"]) / job["steps"] / units,
                     "post": (end - job["t_sample_end"]) / units}
            data.setdefault("clip", []).append(entry)
        for key in ("clip", "assemble", "clip_upscale"):
            data[key] = data.get(key, [])[-30:]
        try:
            self._timings_path().write_text(json.dumps(data, indent=0), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _median(values):
        values = sorted(v for v in values if v is not None and v >= 0)
        return values[len(values) // 2] if values else None

    def _total_estimate(self, job):
        """Expected duration of a whole job, from past ones (None if unknown)."""
        data, units = self._timings(), job.get("units")
        if not units:
            return None
        if job.get("kind") == "assemble" or job.get("upscale"):
            unit = self._median([e.get("unit") for e in data.get("assemble" if job.get("kind") == "assemble" else "clip_upscale", [])])
            return unit * units if unit is not None else None
        prep = self._median([e.get("prep") for e in data.get("clip", [])])
        step = self._median([e.get("step") for e in data.get("clip", [])])
        post = self._median([e.get("post") for e in data.get("clip", [])])
        if None in (prep, step, post):
            return None
        return prep + step * units * int(job.get("steps") or 0) + post * units

    def _count_foreign(self, state):
        """ComfyUI may run work of its own (or of another app): count what is ahead of each job sent by Encore."""
        mine = {j["prompt_id"] for j in self.jobs.values() if j.get("prompt_id")}
        rows = [(-1, r[1]) for r in state.get("queue_running") or []] + [(r[0], r[1]) for r in state.get("queue_pending") or []]
        foreign = [(n, pid) for n, pid in rows if pid not in mine]
        self.comfy_foreign = len(foreign)
        with self.lock:
            for job in self.jobs.values():
                if not job.get("dispatched") or job["status"] not in ACTIVE:
                    continue
                own = next((n for n, pid in rows if pid == job.get("prompt_id")), None)
                job["comfy_ahead"] = 0 if own is None or own == -1 else sum(1 for n, _pid in foreign if n < own)

    def _remaining(self, job, now):
        """Seconds left for a running job (None if unknown)."""
        data, units = self._timings(), job.get("units") or 0
        post = self._median([e.get("post") for e in data.get("clip", [])])
        if job.get("kind") == "assemble" or job.get("upscale"):
            total = self._total_estimate(job)
            return max(0.0, total - (now - job.get("t_start", now))) if total is not None else None
        if job.get("t_sample_end"):
            return max(0.0, post * units - (now - job["t_sample_end"])) if post is not None else None
        t_step = job.get("t_step")
        if t_step and job.get("t_sample") and t_step[0] > 0:
            value, top, at = t_step
            per_step = (at - job["t_sample"]) / value
            left = per_step * max(0, top - value) - (now - at)
            return max(0.0, left) + (post * units if post is not None else 0.0)
        total = self._total_estimate(job)
        if total is None:
            return None
        return max(0.0, total - (now - job.get("t_start", now)))

    def _estimates(self, now):
        """{job id: {"eta": seconds left} or {"start_in": seconds}} for the Studio's jobs, in queue order."""
        out, ahead = {}, 0.0
        sent = sorted((j for j in self.jobs.values() if j["status"] in ACTIVE and j.get("dispatched")),
                      key=lambda j: (j["status"] != "running", j.get("dispatched_at", 0)))
        waiting = [self.jobs[i] for i in self.order if i in self.jobs and not self.jobs[i].get("suspended")]
        active = sent + ([] if self.paused else waiting)
        known, lower = True, False
        for job in active:
            if job["status"] == "running":
                left = self._remaining(job, now)
                if left is None:
                    known = False
                else:
                    out[job["id"]] = {"eta": round(left)}
                    ahead += left
            else:
                if job.get("comfy_ahead"):
                    lower = True       # ComfyUI has other work before it: the estimates become a minimum
                if known:
                    out[job["id"]] = {"start_in": round(ahead)}
                    if lower:
                        out[job["id"]]["at_least"] = True
                total = self._total_estimate(job)
                if total is None:
                    known = False
                else:
                    ahead += total
        return out

    @staticmethod
    def _public(job):
        out = {k: job.get(k) for k in ("id", "kind", "clip", "token", "parentToken", "parentJob", "status", "progress", "step",
                                       "error", "take", "created", "seed", "preview", "previewMime", "branch",
                                       "clips", "export", "checkpoint", "eta", "start_in", "takes", "upscale", "suspended",
                                       "frames", "loras", "lot", "waitFor", "comfy_ahead", "at_least")}
        out["dispatched"] = bool(job.get("dispatched"))
        if job.get("rewrite"):
            out["with_invalid"] = len(job["rewrite"].get("invalid") or [])
        if job.get("pending"):
            out["waiting_for"] = _t("engine.waiting_for_clips", count=len(job["pending"]), clips=_ranges(sorted(int(k) for k in job["pending"])))
        return out

    def preview(self, name, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["project"] != name:
                return None
            return self.previews.get(job_id)

    def remove(self, name, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job["project"] == name and job["status"] not in ACTIVE:
                del self.jobs[job_id]
                self._save(name)
        return self.list_jobs(name)

    def cancel(self, name, ids):
        """Take queued generations out of ComfyUI's queue, interrupt the running one."""
        with self.lock:
            wanted = [i for i in ids if i in self.jobs and self.jobs[i]["project"] == name]
            for i in list(wanted):                       # what depends on a cancelled job cannot run any more
                wanted += [d for d in self._dependents(i) if d not in wanted]
            targets = [self.jobs[i] for i in wanted]
        sent = [j for j in targets if j.get("dispatched") and j["status"] in ACTIVE]
        client = self.client
        if sent:
            try:
                state = client.queue_state()
                now_running = {row[1] for row in state.get("queue_running") or []}
                queued = [j["prompt_id"] for j in sent if j["prompt_id"] not in now_running]
                if queued:
                    client.delete_queued(queued)
                for j in sent:
                    if j["prompt_id"] in now_running:
                        client.interrupt(j["prompt_id"])
            except comfy.ComfyError as exc:
                raise StudioError(str(exc)) from exc
        for job in targets:
            proc = self.local_procs.get(job["id"])
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
        with self.lock:
            for job in targets:
                self.jobs.pop(job["id"], None)
                self.previews.pop(job["id"], None)
                if job["id"] in self.order:
                    self.order.remove(job["id"])
            self._save(name)
            self._save_queue()
        for job in targets:
            if job.get("kind") == "assemble" and job.get("dispatched"):
                self._purge_workspace(client, job)
        self.wake.set()
        return self.list_jobs(name)

    def generate(self, name, clip_index, parent_token=None, random_seed=False, seed=None, branch=None, upscale=None, loras=None,
                 upscale_settings=None):
        """upscale: None (clip, then branch), "on" or "off". loras: None (branch + clip defaults) or the exact list
        of LoRA added for this take, on top of the project's stack. upscale_settings: None (the clip's own, else the
        branch's) or the settings of this take only."""
        with self.launch_lock:
            return self._generate(name, int(clip_index), (parent_token or "").strip().lower() or None, bool(random_seed),
                                  None if seed is None else int(seed), branch or None, upscale, loras,
                                  upscale_settings=upscale_settings)

    # ------------------------------------------------------------------ "tout générer" for a branch
    def fill_branch(self, name, branch_id, dry_run=True, assemble=True):
        """Fills every hole of a branch, in plan order: a clip without a usable take of this branch, and every clip
        that continues one that is redone. Starts from the selection when it is in this branch, otherwise from the
        most recent usable takes. dry_run: only says what would be generated."""
        with self.launch_lock:
            todo = self._fill_plan(name, branch_id)
            if dry_run or not todo["items"]:
                return todo
            items = todo["items"]
            lot = uuid.uuid4().hex[:10]
            label = _t("engine.fill_label", branch=todo['branch_name'], s='s' if len(items) > 1 else '', clips=_ranges([i['clip'] for i in items])) \
                + (_t("engine.assembly") if assemble else "")
            launched, last_token, made = [], None, {}
            for item in items:
                parent = item["parent_token"] if item["parent"] == "take" else last_token if item["parent"] == "job" else None
                job = self._generate(name, item["clip"], parent, True, None, branch_id, None, None, lot=lot, lot_label=label)
                last_token = job["token"]
                launched.append(job["id"])
                made[item["clip"]] = job["id"]
            assembly = None
            if assemble:
                path = self._project(name)
                project = projects.read_project(self.studio.root, name)
                plan = plan_core.normalize(json.loads(json.dumps(project["plan"])))
                branch = projects.find_branch(project["branches"], branch_id)
                count = len(plan["clips"])
                chosen = {k: v for k, v in todo["keep"].items() if k not in made}
                assembly = self._make_assembly(name, path, project["plan"], plan, project["settings"], branch, chosen, count,
                                               pending=made, wait_for=list(made.values()), lot=lot, lot_label=label)
            return dict(todo, launched=launched, assembly=assembly["id"] if assembly else None)

    def _fill_plan(self, name, branch_id):
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        raw, settings, branches = project["plan"], project["settings"], project["branches"]
        if project["validation"]["errors"]:
            raise StudioError(_t("engine.the_plan_has_error_s", v0=len(project['validation']['errors']), v1=project['validation']['errors'][0]))
        branch = projects.find_branch(branches, branch_id)
        if branch is None:
            raise StudioError(_t("engine.unknown_branch"))
        with self.lock:
            self._load(name)
            busy = [j for j in self.jobs.values() if j["project"] == name and j["status"] in ACTIVE
                    and j.get("kind") != "assemble" and (j.get("branch") or (branches[0]["id"] if branches else None)) == branch_id]
        if busy:
            raise StudioError(_t("engine.generation_s_of_this_branch_are", v0=len(busy)), code="busy")
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        local = takes.list_takes(path, raw)
        default = branches[0]["id"] if branches else None
        selection = takes.read_selection(path)
        own = {"branch": branch_id}
        if selection.get("branch") == branch_id:
            own.update({k: v for k, v in selection.items() if k != "branch"})
        resolved = takes.studio_resolve(plan, local, own, takes.current_state(path, plan, settings, branches))
        branch_of = {r["id"]: takes.take_branch(r, default) for recs in local.values() for r in recs}
        steps = int(settings.get("steps") or 8)
        w, h = branch.get("width") or 960, branch.get("height") or 544
        items, redo_prev, prev_take, total, known, keep = [], False, None, 0.0, True, {}
        for clip in plan["clips"]:
            k = clip["index"]
            chosen = resolved[k]["chosen"]
            if chosen and branch_of.get(chosen) != branch_id:
                chosen = None
            cont = clip["continue"] and k > 1
            if chosen and not (cont and redo_prev):
                redo_prev, prev_take = False, chosen
                keep[k] = chosen
                continue
            mine = [(tid, st) for tid, st in resolved[k]["takes"].items() if branch_of.get(tid) == branch_id]
            if not mine:
                reason = _t("engine.no_take_yet")
            elif cont and redo_prev:
                reason = _t("engine.clip_is_redone", v0=k - 1)
            elif any(st[0] == "invalid" for _t, st in mine):
                reason = _t("engine.invalidated_take") + next(st[1] for _t, st in reversed(mine) if st[0] == "invalid")
            elif mine:
                reason = _t("engine.its_takes_follow_another_take_of")
            else:
                reason = _t("engine.to_redo")
            if cont:
                parent = "job" if redo_prev else "take"
            else:
                parent = None
            use_up = bool(projects.upscale_of(branch).get("enabled"))
            estimate = self._total_estimate({"units": int(w) * int(h) * int(clip["frames"]) / 1e6,
                                             "steps": steps, "upscale": use_up})
            if estimate is None:
                known = False
            else:
                total += estimate
            items.append({"clip": k, "name": clip.get("name") or "", "frames": clip["frames"], "reason": reason,
                          "parent": parent, "parent_token": prev_take.split("_")[-1] if parent == "take" and prev_take else None,
                          "after": prev_take if parent == "take" else None, "new_scene": not cont})
            redo_prev, prev_take = True, None
        return {"branch": branch_id, "branch_name": branch["name"], "items": items, "keep": keep,
                "eta": round(total) if items and known else None, "from_selection": selection.get("branch") == branch_id}

    def job_plan(self, name, job_id):
        """The plan a queued or running generation was launched with (the ≡ of its card)."""
        with self.lock:
            job = self.jobs.get(str(job_id))
        if not job or job.get("project") != name or job.get("kind") != "clip":
            raise StudioError(_t("engine.generation_not_found"))
        return takeplan.job_plan(self.studio.root, name, job)

    def assemble(self, name, clip, take_id, job_id=None, allow_invalid=False):
        with self.launch_lock:
            if job_id:
                return self._assemble_after(name, str(job_id))
            if allow_invalid:
                return self._assemble_invalid(name, int(clip), str(take_id or ""))
            return self._assemble(name, int(clip), str(take_id or ""))

    def assemble_check(self, name, clip, take_id):
        """What an assembly of clips 1..clip ending with take_id would use when invalidated takes are allowed."""
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        raw, settings, branches = project["plan"], project["settings"], project["branches"]
        if project["validation"]["errors"]:
            raise StudioError(_t("engine.the_plan_has_error_s", v0=len(project['validation']['errors']), v1=project['validation']['errors'][0]))
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        out = takeplan.invalid_chain(path, raw, plan, settings, branches, int(clip), str(take_id or ""))
        return {k: out.get(k) for k in ("chosen", "invalid", "warnings", "error", "size", "branch")} | {
            "chosen": {str(k): v for k, v in out["chosen"].items()}}

    def _assemble_invalid(self, name, leaf_clip, leaf_id):
        """Assembly along the real parents of leaf_id, invalidated takes included: the working copy sent to
        ComfyUI holds the plan as the takes were made, and their records are made to match it."""
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        raw, settings, branches = project["plan"], project["settings"], project["branches"]
        if project["validation"]["errors"]:
            raise StudioError(_t("engine.the_plan_has_error_s", v0=len(project['validation']['errors']), v1=project['validation']['errors'][0]))
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        out = takeplan.invalid_chain(path, raw, plan, settings, branches, leaf_clip, leaf_id)
        if out["error"]:
            raise StudioError(out["error"])
        branch = projects.find_branch(branches, out["branch"])
        sent = out["sent_plan"]
        sent_plan = plan_core.normalize(json.loads(json.dumps(sent)))
        return self._make_assembly(name, path, sent, sent_plan, settings, branch, out["chosen"], leaf_clip, leaf=leaf_id,
                                   rewrite={"invalid": out["invalid"], "warnings": out["warnings"], "size": out["size"]})

    def _assemble_after(self, name, job_id):
        """Assembly planned after a generation still waiting: clips 1 to its clip. The generations of the chain that
        are still to come give their takes when they end; the clips before come from existing takes, like an
        ordinary assembly."""
        with self.lock:
            self._load(name)
            job = self.jobs.get(job_id)
            if not job or job["project"] != name or job["kind"] != "clip" or job["status"] not in ACTIVE:
                raise StudioError(_t("engine.this_generation_is_no_longer_waiting"))
            pending, cur = {}, job
            while True:
                pending[cur["clip"]] = cur["id"]
                parent = self.jobs.get(cur.get("parentJob"))
                if parent and parent["status"] in ACTIVE:
                    cur = parent
                    continue
                break
            first = cur
            base_token = first.get("parentToken")
            base_done = self.jobs.get(first.get("parentJob"))
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        raw, settings, branches = project["plan"], project["settings"], project["branches"]
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        branch = projects.find_branch(branches, job.get("branch") or (branches[0]["id"] if branches else None))
        chosen = {}
        if first["clip"] > 1:
            local = takes.list_takes(path, raw)
            base_id = None
            if base_token:
                base_id = next((r["id"] for r in local.get(first["clip"] - 1, []) if r["id"].endswith("_" + base_token)), None)
                if base_id is None and base_done is not None:
                    base_id = base_done.get("take")
                if base_id is None:
                    raise StudioError(_t("engine.the_take_of_clip_this_generation", v0=first['clip'] - 1))
                full = self._assemble_choice(name, path, raw, plan, settings, branches, first["clip"] - 1, base_id)
            else:                                   # the waiting generation starts a scene: earlier clips from the selection
                full = self._assemble_choice(name, path, raw, plan, settings, branches, first["clip"] - 1, None, branch["id"])
            chosen.update(full)
        count = job["clip"]
        return self._make_assembly(name, path, raw, plan, settings, branch, chosen, count, pending=pending,
                                   parent_job=job["id"], wait_for=list(pending.values()), lot=job.get("lot"),
                                   lot_label=job.get("lot_label"))

    def _assemble_choice(self, name, path, raw, plan, settings, branches, upto, leaf_id, branch_id=None):
        """{clip: take id} for clips 1..upto: the chain ending with leaf_id, and before a cut the selection of the
        branch (as an ordinary assembly)."""
        local = takes.list_takes(path, raw)
        by_id = {r["id"]: (i, r) for i, records in local.items() for r in records}
        default = branches[0]["id"] if branches else "b1"
        chain = {}
        if leaf_id:
            if leaf_id not in by_id:
                raise StudioError(_t("engine.take_no_longer_exists", leaf_id=leaf_id))
            branch_id = takes.take_branch(by_id[leaf_id][1], default)
            try:
                chain = {i: r["id"] for i, r in takes.ancestors(path, raw, upto, leaf_id)}
            except ValueError as exc:
                raise StudioError(str(exc)) from exc
        current_sel = takes.read_selection(path)
        selection = {"branch": branch_id}
        if current_sel.get("branch") in (None, branch_id):
            selection.update({int(k): v for k, v in current_sel.items() if k != "branch"})
        selection.update(chain)
        resolved = takes.studio_resolve(plan, local, selection, takes.current_state(path, plan, settings, branches))
        out = {}
        for index in range(1, upto + 1):
            pick = resolved[index]["chosen"]
            if not pick or (index in chain and pick != chain[index]):
                raise StudioError(_t("engine.nothing_to_assemble_clip_has_no", index=index))
            out[index] = pick
        return out

    def _assemble(self, name, leaf_clip, leaf_id):
        """Assemble clips 1 to leaf_clip along the chain that ends with the take leaf_id. Each assembly has its own
        workspace in ComfyUI (plan copy, latents, selection): it can wait in the queue next to generations and
        other assemblies of the same branch without sharing anything with them."""
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        raw, settings, branches = project["plan"], project["settings"], project["branches"]
        if project["validation"]["errors"]:
            raise StudioError(_t("engine.the_plan_has_error_s", v0=len(project['validation']['errors']), v1=project['validation']['errors'][0]))
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        local = takes.list_takes(path, raw)
        by_id = {r["id"]: (i, r) for i, records in local.items() for r in records}
        if leaf_id not in by_id or by_id[leaf_id][0] != leaf_clip:
            raise StudioError(_t("engine.take_of_clip_no_longer_exists", leaf_id=leaf_id, leaf_clip=leaf_clip))
        default = branches[0]["id"] if branches else "b1"
        branch_id = takes.take_branch(by_id[leaf_id][1], default)
        branch = projects.find_branch(branches, branch_id)
        try:
            chain = {i: r["id"] for i, r in takes.ancestors(path, raw, leaf_clip, leaf_id)}
        except ValueError as exc:
            raise StudioError(str(exc)) from exc
        # earlier scenes (before a cut): the takes of the current selection when it is in this branch
        current_sel = takes.read_selection(path)
        selection = {"branch": branch_id}
        if current_sel.get("branch") in (None, branch_id):
            selection.update({int(k): v for k, v in current_sel.items() if k != "branch"})
        selection.update(chain)
        resolved = takes.studio_resolve(plan, local, selection, takes.current_state(path, plan, settings, branches))
        chosen = {}
        for index in range(1, leaf_clip + 1):
            pick = resolved[index]["chosen"]
            if not pick or (index in chain and pick != chain[index]):
                raise StudioError(_t("engine.nothing_to_assemble_clip_has_no", index=index))
            chosen[index] = pick
        return self._make_assembly(name, path, raw, plan, settings, branch, chosen, leaf_clip, leaf=leaf_id)

    def _make_assembly(self, name, path, raw, plan, settings, branch, chosen, count, leaf=None, pending=None,
                       parent_job=None, wait_for=None, lot=None, lot_label=None, rewrite=None):
        """The assembly job of clips 1..count. chosen: {clip: take id} for takes that exist; pending: {clip: job id}
        for takes still to generate (resolved when they are harvested). With pending takes the checkpoint is made
        when the assembly starts, once every take is known."""
        branch_id = branch["id"]
        free = plan["mode"] == "free"
        workspace = f"{branch_id}_a{uuid.uuid4().hex[:8]}"
        with self.lock:
            self._load(name)
            waiting = {j.get("export") for j in self.jobs.values() if j["project"] == name and j.get("kind") == "assemble"
                       and j["status"] in ACTIVE + ("harvest",)}
        export = export_name(path, name, branch["name"], taken=waiting)
        try:
            info = self._object_info()
        except comfy.ComfyError as exc:
            raise StudioError(str(exc)) from exc
        start = plan.get("start_video") if (plan.get("start_video") or {}).get("in_assembly") else None
        edit = plan.get("edit_video") if (plan.get("edit_video") or {}).get("sound") == "original" else None
        missing = [n for n in ["VAELoader", "H3PlanAssemble"] + ([] if free else ["LoadAudio"])
                   + (["H3PlanVideo", "MiniMaxH3AudioVAECompatibility"] if start else [])
                   + (["H3PlanVideo"] if edit else []) if n not in info]
        if missing:
            raise StudioError(_t("engine.nodes_missing_from_comfyui") + ", ".join(missing)
                              + (_t("engine.video_node_needs_plugin") if "H3PlanVideo" in missing else ""))
        start_video = None
        if start:                                     # the segment opens the video: the project's start video
            rel = (projects.effective_refs(path, branch, plan).get(start["ref"]) or {}).get("video")
            video_file = projects.safe_join(path, rel or "")
            if not rel or not video_file.is_file():
                raise StudioError(_t("engine.start_video_not_chosen"))
            start_video = {"name": start["ref"], "video": rel, "sha": takes.file_sha(video_file)}
        edit_video = None
        if edit:                                      # the final video keeps the edited video's sound
            rel = (projects.effective_refs(path, branch, plan).get(edit["ref"]) or {}).get("video")
            video_file = projects.safe_join(path, rel or "")
            if not rel or not video_file.is_file():
                raise StudioError(_t("engine.edit_video_not_chosen"))
            edit_video = {"name": edit["ref"], "video": rel, "sha": takes.file_sha(video_file)}
        if not free and not projects.safe_join(path, branch.get("song") or "").is_file():
            raise StudioError(_t("engine.song_of_branch_not_found", v0=branch['name']))
        # the state that produced this video, to come back to it (later for a planned assembly)
        cp = None if pending else checkpoints.create(self.studio.root, name, label=_t("engine.assembly_2", export=export), kind="auto",
                                reason=_t("engine.assembly_of_mp4", export=export), limit=self.studio.config.get("checkpoint_limit", 0),
                                selection={**{str(k): v for k, v in chosen.items()}, "branch": branch_id})
        size = list(rewrite["size"]) if rewrite and rewrite.get("size") else [branch.get("width"), branch.get("height")]
        job = {"id": "j" + uuid.uuid4().hex[:15], "prompt_id": None, "dispatched": False,
               "spec": {"raw": raw, "mode": plan["mode"], "settings": settings, "song": None if free else branch.get("song"),
                        "start_video": start_video, "edit_video": edit_video},
               "project": name, "branch": branch_id, "kind": "assemble", "clips": count,
               "frames": int(plan_core.timeline(plan)[count - 1]["end"]) - plan_core.final_start(plan),
               "workspace": workspace, "leaf": leaf,
               "takes": {str(k): v for k, v in chosen.items()}, "pending": {str(k): v for k, v in (pending or {}).items()},
               "parentJob": parent_job, "waitFor": list(wait_for or []), "lot": lot, "lot_label": lot_label,
               "export": export, "checkpoint": cp["id"] if cp else None, "status": "queued", "progress": None, "step": None,
               "error": None, "take": None, "created": time.time(), "clip": count + 1, "token": None, "parentToken": None,
               "seed": None, "branch_name": branch["name"],
               "size": size,
               "plan_snapshot": raw, "crf": int(settings.get("crf") or 0) or None, "rewrite": rewrite,
               "ref_image_size": branch.get("ref_image_size"), "song_file": branch.get("song") if plan["mode"] != "free" else None,
               "units": int(size[0]) * int(size[1]) * int(plan_core.timeline(plan)[count - 1]["end"]) / 1e6}
        with self.lock:
            self.jobs[job["id"]] = job
            self._enqueue(job)
            self._save(name)
        self.wake.set()
        return self._public(job)

    def active_in_branch(self, name, branch, default):
        return [j for j in self.active(name) if (j.get("branch") or default) == branch]

    def active(self, name):
        with self.lock:
            self._load(name)
            return [j for j in self.jobs.values() if j["project"] == name and j["status"] in ACTIVE + ("harvest",)]

    # ------------------------------------------------------------------ launching
    def _generate(self, name, index, parent_token, random_seed, forced_seed=None, branch_id=None, upscale_choice=None,
                  take_loras=None, lot=None, lot_label=None, upscale_settings=None):
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        raw, settings = project["plan"], project["settings"]
        if project["validation"]["errors"]:
            raise StudioError(_t("engine.the_plan_has_error_s", v0=len(project['validation']['errors']), v1=project['validation']['errors'][0]))
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        if not 1 <= index <= len(plan["clips"]):
            raise StudioError(_t("engine.the_plan_has_no_clip", index=index))
        clip = plan["clips"][index - 1]
        free = plan["mode"] == "free"
        branches = project["branches"]
        default = branches[0]["id"] if branches else None
        if any(l.get("enabled") and not l.get("name") for l in settings.get("loras") or []):
            raise StudioError(_t("engine.an_active_lora_has_no_file"))
        with self.lock:
            self._load(name)
            jobs = [j for j in self.jobs.values() if j["project"] == name and j["status"] in ACTIVE]
        local = takes.list_takes(path, raw)
        selection = takes.read_selection(path)
        resolved = takes.studio_resolve(plan, local, selection, takes.current_state(path, plan, settings, branches))

        # the take this clip continues: a take of the project, or a generation still waiting
        parent_take = parent_job = None
        if clip["continue"] and index > 1:
            if parent_token:
                parent_take = next((r for r in local.get(index - 1, []) if r["id"].endswith("_" + parent_token)), None)
                if parent_take is None:
                    parent_job = next((j for j in jobs if j["clip"] == index - 1 and j["token"] == parent_token), None)
                if parent_take is None and parent_job is None:
                    raise StudioError(_t("engine.the_take_of_clip_this_clip", v0=index - 1))
            else:
                chosen = resolved[index - 1]["chosen"]
                waiting = [j for j in jobs if j["clip"] == index - 1]
                if chosen:
                    parent_take = next(r for r in local[index - 1] if r["id"] == chosen)
                elif waiting:
                    parent_job = max(waiting, key=lambda j: j["created"])
                else:
                    raise StudioError(_t("engine.clip_continues_clip_first_generate_a", index=index, v1=index - 1, v2=index - 1))
            if parent_take is not None:
                state, why = resolved[index - 1]["takes"].get(parent_take["id"], ("invalid", "?"))
                if state == "invalid":
                    raise StudioError(_t("engine.take_of_clip_is_invalidated_first", v0=parent_take['id'], v1=index - 1, why=why, v3=index - 1))
                parent_token = parent_take["id"].split("_")[-1]
            else:
                parent_token = parent_job["token"]

        # the branch: the one of the take continued, otherwise the one asked for
        if parent_take is not None:
            branch_id = takes.take_branch(parent_take, default)
        elif parent_job is not None:
            branch_id = parent_job.get("branch") or default
        if not branch_id:
            raise StudioError(_t("engine.no_branch_create_one_with_new"))
        branch = projects.find_branch(branches, branch_id)
        settings = dict(settings, width=int(branch.get("width") or 960), height=int(branch.get("height") or 544))
        problem = plan_core.check_size(settings["width"], settings["height"])
        if problem:
            raise StudioError(_t("engine.branch", v0=branch['name'], problem=problem))
        # LoRA added for this take: the exact list given, otherwise branch + clip defaults (on top of the project stack)
        clip_def = projects.clip_default(project, clip.get("name") or "")
        extra_loras = projects.merge_loras(projects.clean_loras(take_loras)) if take_loras is not None else projects.default_extra_loras(branch, clip_def)
        if extra_loras:
            base = [{"name": l["name"], "strength": float(l["strength"])} for l in projects.active_loras(settings)]
            settings = dict(settings, loras=[dict(l, enabled=True) for l in projects.merge_loras(base, extra_loras)])
        # latent upscale: this generation's choice ("on" / "off"), otherwise the clip's, otherwise the branch's setting
        # the branch's settings, unless this take has its own (« enabled » included); upscale_choice "on" / "off"
        # forces with or without (API of earlier versions)
        up_settings, up_source = projects.upscale_of(branch), "branch"
        if upscale_settings is not None:
            up_settings, up_source = projects.clean_upscale(upscale_settings), "take"
        use_upscale = up_settings["enabled"] if upscale_choice not in ("on", "off") else upscale_choice == "on"
        upscale = upscale_plan(up_settings, settings["width"], settings["height"], settings["steps"]) if use_upscale else None
        if upscale and extra_loras and upscale.get("pass2_loras") is not None:   # own LoRA for pass 2: the take's are added
            base2 = [{"name": l["name"], "strength": float(l["strength"])} for l in projects.active_loras({"loras": upscale["pass2_loras"]})]
            upscale["pass2_loras"] = [dict(l, enabled=True) for l in projects.merge_loras(base2, extra_loras)]
        context_latent = 0
        if upscale and clip["continue"]:     # clip 1 too when it continues the start video
            context = int(plan_core.timeline(plan)[index - 1]["context"])
            context_latent = latent_frames(context) if context else 0
        refs, problems = clip_needs(plan, index, {"refs": projects.effective_refs(path, branch, plan), "song": branch.get("song") or ""})
        if problems:
            raise StudioError(_t("engine.clip_references_button_of_branch", index=index, v1=', '.join(problems), v2=branch['name']))

        busy = any(takes.take_branch(r, default) == branch_id for r in local.get(index, [])) or \
            any(j["clip"] == index and (j.get("branch") or default) == branch_id for j in jobs)
        if forced_seed is not None:               # "régénérer" or a seed typed by the user
            if not 0 <= forced_seed <= 2 ** 48:
                raise StudioError(_t("engine.invalid_seed_an_integer_from_0"))
            seed = forced_seed
        else:
            seed = random.getrandbits(48) if (random_seed or busy) else int(clip["seed"])
        token = uuid.uuid4().hex[:8]

        # frozen now (what was clicked is what will be generated); sent to ComfyUI when its turn comes
        try:
            info = self._object_info()
        except comfy.ComfyError as exc:
            raise StudioError(str(exc)) from exc
        missing = missing_nodes(info, settings, music=not free, upscale=upscale,
                                video=any(r.get("video") for r in refs))
        if missing:
            raise StudioError(_t("engine.nodes_missing_from_comfyui") + ", ".join(missing)
                              + (_t("engine.kjnodes_preview_install_comfyui_kjnodes_or")
                                 if "ModelPreviewOverrideKJ" in missing else "")
                              + (_t("engine.video_node_needs_plugin") if "H3PlanVideo" in missing else ""))
        if extra_loras:
            known = set(((((info.get("LoraLoaderModelOnly") or {}).get("input") or {}).get("required") or {}).get("lora_name") or [[]])[0] or [])
            unknown = [l["name"] for l in extra_loras if known and l["name"] not in known]
            if unknown:
                raise StudioError(_t("engine.lora_not_found_in_comfyui") + ", ".join(unknown))
        settings = dict(settings, _kj_frames_value=kj_frames_value(info, settings))
        files = {}
        for ref in refs:
            files[ref["name"]] = {"image": None, "voice": None, "image_sha": None, "voice_sha": None}
            for kind in ("image", "voice", "video"):
                if ref.get(kind):
                    local_file = projects.safe_join(path, ref[kind])
                    if not local_file.is_file():
                        raise StudioError(_t("engine.file_of_not_found", v0=ref['name'], v1=ref[kind]))
                    files[ref["name"]][kind] = ref[kind]
                    files[ref["name"]][kind + "_sha"] = takes.file_sha(local_file)
        song_sha = None
        if not free:
            song_file = projects.safe_join(path, branch["song"])
            if not song_file.is_file():
                raise StudioError(_t("engine.song_not_found", v0=branch['song']))
            song_sha = takes.file_sha(song_file)
        spec = {"raw": raw, "mode": plan["mode"], "refs": [r["name"] for r in refs], "files": files,
                "song": None if free else branch["song"], "song_sha": song_sha,
                "parent_take": parent_take["id"] if parent_take is not None else None,
                "settings": settings, "upscale": upscale, "context_latent": context_latent}

        studio_info = {
            "branch": branch_id,
            "refs": {n: {"image": f["image_sha"], "voice": f["voice_sha"], **({"video": f["video_sha"]} if f.get("video") else {})}
                     for n, f in files.items()},
            "files": {n: {"image": f["image"], "voice": f["voice"], **({"video": f["video"]} if f.get("video") else {})}
                      for n, f in files.items()},
            "width": int(settings["width"]), "height": int(settings["height"]),
            "ref_image_size": branch.get("ref_image_size") or projects.DEFAULT_REF_SIZE,
            **({"song": song_sha, "song_file": branch["song"]} if not free else {}),
            "models": dict({k: settings.get(k) for k in ("unet_name", "weight_dtype", "clip_name", "video_vae", "audio_vae",
                                                         "sampler_name", "scheduler", "steps", "shift_video", "shift_audio",
                                                         "attention")},
                           loras=[{"name": l["name"], "strength": l["strength"]} for l in projects.active_loras(settings)]),
            "extra_loras": extra_loras,
            # the plan as this take was made with it (the Takes tab shows it, an invalid assembly sends it)
            "plan_clip": json.loads(json.dumps(raw["clips"][index - 1])),
            "raw_start": plan_core.timeline(plan)[index - 1]["raw_start"],
        }
        if upscale:
            studio_info["upscale"] = {k: upscale[k] for k in ("summary", "upscaler", "model", "w0", "h0", "start_mp", "steps",
                                                             "pass1", "pass2", "pass2_loras", "pass2_sampler")}
            # the settings themselves, and where they came from: « ⟲ redo » and ▾ start again from them
            studio_info["upscale"].update(settings={k: v for k, v in up_settings.items() if k != "enabled"}, source=up_source)
        job = {"units": int(settings["width"]) * int(settings["height"]) * int(clip["frames"]) / 1e6,
               "steps": sum(upscale["steps"]) if upscale else int(settings["steps"]), "upscale": bool(upscale),
               "id": "j" + uuid.uuid4().hex[:15], "prompt_id": None, "dispatched": False, "spec": spec,
               "project": name, "branch": branch_id, "kind": "clip", "clip": index, "token": token, "frames": int(clip["frames"]),
               "parentToken": parent_token if clip["continue"] else None,
               "parentJob": parent_job["id"] if parent_job else None, "seed": seed, "status": "queued", "loras": extra_loras,
               "progress": None, "step": None, "error": None, "take": None, "created": time.time(), "studio": studio_info,
               "lot": lot, "lot_label": lot_label}
        with self.lock:
            self.jobs[job["id"]] = job
            self._enqueue(job)
            self._save(name)
        self.wake.set()
        return self._public(job)

    # ------------------------------------------------------------------ sending a job to ComfyUI
    def _dispatch_clip(self, client, job):
        """Sends what a frozen generation needs (plan, references, song, takes continued) and queues it."""
        name, branch_id, spec = job["project"], job["branch"], job["spec"]
        path, raw, index = self._project(name), spec["raw"], job["clip"]
        with self.lock:
            others = [j for j in self.jobs.values() if j is not job and j["project"] == name and _branch(j) == branch_id
                      and (j.get("dispatched") and j["status"] in ACTIVE or j["status"] == "harvest")]
        if not others:
            self._purge_branch(client, name, branch_id)        # nothing left over from earlier sessions
        plan_file = self._send_plan(client, name, branch_id, raw)
        sent_refs = []
        for ref_name in spec["refs"]:
            f = spec["files"].get(ref_name) or {}
            item = {"name": ref_name, "image": None, "voice": None, "video": None}
            for kind in ("image", "voice", "video"):
                if f.get(kind):
                    local_file = projects.safe_join(path, f[kind])
                    if not local_file.is_file() or takes.file_sha(local_file) != f.get(kind + "_sha"):
                        raise StudioError(_t("engine.the_file_of_has_changed_or", ref_name=ref_name, v1=f[kind]))
                    item[kind] = self._send_input(client, local_file, f[kind + "_sha"], f"{INPUT_DIR}/{name}", job=job)
            sent_refs.append(item)
        song = None
        if spec.get("song"):
            song_file = projects.safe_join(path, spec["song"])
            if not song_file.is_file() or takes.file_sha(song_file) != spec.get("song_sha"):
                raise StudioError(_t("engine.the_song_has_changed_or_disappeared", v0=spec['song']))
            song = self._send_input(client, song_file, spec["song_sha"], "", prefix=f"{INPUT_DIR}_{name}_")
        if spec.get("parent_take"):
            self._send_chain(client, name, branch_id, path, raw, index - 1, spec["parent_take"])
        elif job.get("parentToken"):
            self._send_job_chain(client, name, branch_id, path, raw, job)
        workflow = clip_workflow({
            "plan_file": plan_file, "clip_index": index, "mode": spec["mode"], "refs": sent_refs, "song": song,
            "take_token": job["token"], "parent_token": job.get("parentToken") or "", "seed": job["seed"],
            "settings": spec["settings"], "upscale": spec.get("upscale"), "context_latent": spec.get("context_latent") or 0,
        })
        return client.queue_prompt(workflow, self.client_id, {"project": name, "clip": index, "token": job["token"]})

    def _resolve_assembly(self, job):
        """The takes of a planned assembly (generations it waited for) and its checkpoint, known only now."""
        name = job["project"]
        for clip_key, jid in list((job.get("pending") or {}).items()):
            other = self.jobs.get(jid)
            if not other or not other.get("take"):
                raise StudioError(_t("engine.the_take_of_clip_does_not", clip_key=clip_key))
            job["takes"][clip_key] = other["take"]
            del job["pending"][clip_key]
        if not job.get("checkpoint"):
            cp = checkpoints.create(self.studio.root, name, label=_t("engine.assembly_3", v0=job['export']), kind="auto",
                                    reason=_t("engine.assembly_of_mp4_2", v0=job['export']), limit=self.studio.config.get("checkpoint_limit", 0),
                                    selection={**{str(k): v for k, v in job["takes"].items()}, "branch": job["branch"]})
            job["checkpoint"] = cp["id"]

    def _local_assemblies(self):
        """Assemblies Encore makes itself with ffmpeg from the takes' previews, beside ComfyUI's work (one at a
        time). One that cannot (no ffmpeg, a take without preview, invalidated takes) goes to the plugin."""
        self._sweep_orphans()
        with self.lock:
            if self.paused or any(j.get("local") and j["status"] == "running" for j in self.jobs.values()):
                return
            job = next((self.jobs[i] for i in self.order if i in self.jobs and self.jobs[i]["kind"] == "assemble"
                        and self.jobs[i].get("local") is not False and self._ready(self.jobs[i])), None)
            if job is None:
                return
            try:
                self._resolve_assembly(job)
            except (StudioError, OSError, ValueError) as exc:
                return self._fail(job, str(exc))
            path = self._project(job["project"])
            ffmpeg, why = (None, "invalidated takes") if job.get("rewrite") else assembler.ready_for(path, job, self.studio.config)
            if ffmpeg is None:
                job["local"] = False
                print(f"[Encore] assembly {job['export']} by the plugin: {why}", flush=True)
                self._save(job["project"])
                return
            job.update(local=True, status="running", t_start=time.time(), step=_t("assembler.step", pct=0),
                       progress={"value": 0, "max": 100})
            if job["id"] in self.order:
                self.order.remove(job["id"])
            self._save(job["project"])
            self._save_queue()
        threading.Thread(target=self._run_local_assembly, args=(job, path, ffmpeg), daemon=True,
                         name=f"encore-assemble-{job['id']}").start()

    def _run_local_assembly(self, job, path, ffmpeg):
        def progress(share):
            pct = int(100 * share)
            job["step"], job["progress"] = _t("assembler.step", pct=pct), {"value": pct, "max": 100}
        try:
            target = path / "exports" / f"{job['export']}.mp4"
            report = assembler.build(path, job, ffmpeg, target, on_progress=progress, procs=self.local_procs)
            if job["id"] not in self.jobs:          # cancelled meanwhile
                target.unlink(missing_ok=True)
                return
            self._write_export(path, job, report)
            with self.lock:
                job["status"], job["ended"], job["progress"], job["step"] = "done", time.time(), None, None
                self._save(job["project"])
        except Exception as exc:  # noqa: BLE001 - the job shows the error
            if job["id"] in self.jobs:
                self._fail(job, str(exc))
        finally:
            self.wake.set()

    def _write_export(self, path, job, report):
        """The information file of an assembled video (exports/<name>.json and its infos)."""
        info = {"name": job["export"], "created": time.time(), "branch": job.get("branch"), "branch_name": job.get("branch_name"),
                "clips": job.get("clips"), "takes": {str(k): v for k, v in (job.get("takes") or {}).items()},
                "checkpoint": job.get("checkpoint"), "size": job.get("size"), "report": report, "prompt_id": job.get("prompt_id"),
                "assembled_by": "ffmpeg" if job.get("local") else "plugin"}
        meta = path / "exports" / f"{job['export']}.json"
        tmp = meta.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, meta)
        try:
            write_infos(path, job, report)
        except Exception as exc:          # never lose a video because of its information file
            print(_t("engine.encore_infos_of_not_written", v0=job['export'], exc=exc), flush=True)

    def _dispatch_assembly(self, client, job):
        name, spec = job["project"], job["spec"]
        path, raw, workspace = self._project(name), spec["raw"], job["workspace"]
        self._resolve_assembly(job)
        plan_file = self._send_plan(client, name, workspace, raw, settings_branch=job["branch"])
        chosen = {int(k): v for k, v in job["takes"].items()}
        sent_plan = plan_core.normalize(json.loads(json.dumps(raw))) if job.get("rewrite") else None
        for index in range(1, job["clips"] + 1):
            meta = takes.clip_dir(path, index) / f"{chosen[index]}.json"
            try:
                record = dict(json.loads(meta.read_text(encoding="utf-8")), id=chosen[index])
            except (OSError, ValueError) as exc:
                raise StudioError(_t("engine.take_of_clip_has_disappeared_since", v0=chosen[index], index=index)) from exc
            if sent_plan is not None:           # invalidated takes allowed: the record matches the plan sent
                record = takeplan.rewritten_record(sent_plan, index, record, chosen.get(index - 1))
            self._send_take(client, name, workspace, path, index, record)
        client.save_selection(plan_file, chosen)
        song = None
        if spec.get("song"):
            song_file = projects.safe_join(path, spec["song"])
            if not song_file.is_file():
                raise StudioError(_t("engine.song_not_found", v0=spec['song']))
            song = self._send_input(client, song_file, takes.file_sha(song_file), "", prefix=f"{INPUT_DIR}_{name}_")
        start_video = None
        if spec.get("start_video"):
            sv = spec["start_video"]
            video_file = projects.safe_join(path, sv["video"])
            if not video_file.is_file() or takes.file_sha(video_file) != sv["sha"]:
                raise StudioError(_t("engine.the_file_of_has_changed_or", ref_name=sv["name"], v1=sv["video"]))
            start_video = {"name": sv["name"], "video": self._send_input(client, video_file, sv["sha"], f"{INPUT_DIR}/{name}", job=job)}
        edit_video = None
        if spec.get("edit_video"):
            ev = spec["edit_video"]
            video_file = projects.safe_join(path, ev["video"])
            if not video_file.is_file() or takes.file_sha(video_file) != ev["sha"]:
                raise StudioError(_t("engine.the_file_of_has_changed_or", ref_name=ev["name"], v1=ev["video"]))
            edit_video = {"name": ev["name"], "video": self._send_input(client, video_file, ev["sha"], f"{INPUT_DIR}/{name}", job=job)}
        workflow = assemble_workflow(plan_file, spec["mode"], job["clips"], spec["settings"], song,
                                     start_video=start_video, size=job.get("size"), edit_video=edit_video)
        return client.queue_prompt(workflow, self.client_id, {"project": name, "kind": "assemble", "branch": job["branch"]})

    def _ready(self, job):
        """Can this waiting job be sent? (the generation it continues must be over and harvested)"""
        if job.get("suspended"):
            return False
        for dep in self._deps(job):
            other = self.jobs.get(dep)
            if other is not None and other["status"] != "done":
                return False
            if other is None and dep in (job.get("pending") or {}).values():
                return False          # cannot know its take any more: _sweep_orphans fails it
        return True

    def _sweep_orphans(self):
        """Waiting jobs whose dependency failed (or vanished before giving its take) cannot run: error, with their
        own dependents. Only them: what does not depend on the failed generation keeps going."""
        with self.lock:
            doomed = []
            for jid in self.order:
                job = self.jobs.get(jid)
                if not job:
                    continue
                for dep in self._deps(job):
                    other = self.jobs.get(dep)
                    if (other is not None and other["status"] == "error") or (other is None and dep in (job.get("pending") or {}).values()):
                        clip = other.get("clip") if other else None
                        doomed.append((job, _t("engine.clip_it_depends_on_has_failed_2", clip=clip) if clip else _t("engine.a_generation_it_depends_on_did")))
                        break
        for job, message in doomed:
            if job["status"] in ACTIVE:
                self._fail(job, message)

    def _dispatch_next(self):
        """One job at a time in ComfyUI: when ours are all over, the first ready job of the queue is sent."""
        self._sweep_orphans()
        with self.launch_lock:
            with self.lock:
                if self.paused or any(j.get("dispatched") and j["status"] in ACTIVE for j in self.jobs.values()):
                    return
                if any(j["status"] == "harvest" for j in self.jobs.values()):
                    return
                job = next((self.jobs[i] for i in self.order if i in self.jobs and self._ready(self.jobs[i])
                            and not (self.jobs[i]["kind"] == "assemble" and self.jobs[i].get("local") is not False)), None)
                if job is None:
                    return
            client = self.client
            self._ensure_socket()
            try:
                answer = self._dispatch_assembly(client, job) if job["kind"] == "assemble" else self._dispatch_clip(client, job)
            except comfy.ComfyError as exc:
                if exc.unreachable:
                    self._comfy_down()
                    return                              # ComfyUI unreachable: try again later
                return self._fail(job, str(exc))
            except (StudioError, OSError, ValueError) as exc:
                return self._fail(job, str(exc))
            with self.lock:
                job.update(prompt_id=answer["prompt_id"], dispatched=True, dispatched_at=time.time())
                if job["id"] in self.order:
                    self.order.remove(job["id"])
                self._save(job["project"])
                self._save_queue()

    def _fail(self, job, message):
        """A job that cannot run: error, and the jobs that depend on it are taken out of the queue."""
        with self.lock:
            job.update(status="error", error=message)
            dependents = self._dependents(job["id"])
            for jid in dependents:
                self.jobs[jid].update(status="error", error=_failed_dep(job))
            for jid in [job["id"]] + dependents:
                if jid in self.order:
                    self.order.remove(jid)
            for name in {job["project"]}:
                self._save(name)
            self._save_queue()

    def _send_plan(self, client, name, branch, raw, settings_branch=None):
        copy = json.loads(json.dumps(raw))
        copy["project"] = mirror_name(name, branch)
        meta = projects.read_meta(self._project(name))
        copy["ref_image_size"] = next((b.get("ref_image_size") for b in meta["branches"] if b["id"] == (settings_branch or branch)), None) \
            or projects.DEFAULT_REF_SIZE        # a branch setting: the plan does not hold it any more
        # version 5 only for an edited video: plans without one stay readable by the plugin 3.7
        copy["version"] = plan_core.PLAN_VERSION if copy.get("edit_video") else 4
        data = (json.dumps(copy, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        return self._put(client, data, "plan.json", f"{INPUT_DIR}/{name}/{branch}", "input")

    def _send_input(self, client, local_file: Path, sha, subfolder, prefix="", job=None):
        """A project file in ComfyUI's input folder, named after its content (sent once; a big file shows its
        progress on the job)."""
        stem, ext = os.path.splitext(local_file.name)
        name = f"{prefix}{stem[:40]}_{sha[:10]}{ext.lower()}"
        key = (self.studio.config["comfy_url"], subfolder, name)
        if self.uploaded.get(key) != sha:
            def progress(sent, total):
                if job is not None and total > 8 * 1024 * 1024:
                    job["step"] = _t("engine.sending_to_comfyui", file=local_file.name, v1=int(100 * sent / total))
            self._put(client, local_file, name, subfolder, "input", progress, named_by_content=True)
            self.uploaded[key] = sha
        return f"{subfolder}/{name}" if subfolder else name

    def _put(self, client, data, name, subfolder, kind, progress=None, named_by_content=False):
        """A file (bytes, or the path of a file) into ComfyUI's input or output folder; returns its path there.
        When ComfyUI's folder is known (configuration) the file is written straight into it: no size limit. Otherwise,
        or if ComfyUI does not see that copy (another input folder, another machine), it goes through ComfyUI's upload
        route, which refuses files over its --max-upload-size (100 MB by default)."""
        rel = f"{subfolder}/{name}" if subfolder else name
        if self._copy_into(client, data, name, subfolder, kind, progress, named_by_content):
            return rel
        try:
            return client.upload(data, name, subfolder, kind, progress=progress)
        except comfy.ComfyError as exc:
            if exc.status == 413:
                size = len(data) if isinstance(data, (bytes, bytearray)) else Path(data).stat().st_size
                label = name if isinstance(data, (bytes, bytearray)) else Path(data).name
                raise StudioError(_t("engine.upload_too_big", file=label, v1=f"{size / 1024 ** 2:.0f}")) from exc
            raise

    def _copy_into(self, client, data, name, subfolder, kind, progress, named_by_content):
        root = comfy_setup.comfy_root(self.studio.config.get("comfy_dir"))
        if root is None:
            return False
        folder = root / kind / subfolder if subfolder else root / kind
        target = folder / name
        try:
            size = len(data) if isinstance(data, (bytes, bytearray)) else Path(data).stat().st_size
            if not (named_by_content and target.is_file() and target.stat().st_size == size):
                folder.mkdir(parents=True, exist_ok=True)
                part = target.with_name(target.name + ".part")
                if isinstance(data, (bytes, bytearray)):
                    part.write_bytes(data)
                else:
                    sent = 0
                    with open(data, "rb") as src, open(part, "wb") as dst:
                        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
                            dst.write(chunk)
                            sent += len(chunk)
                            if progress:
                                progress(sent, size)
                os.replace(part, target)
        except OSError:
            return False
        return client.exists(name, subfolder, kind)

    def _send_take(self, client, name, branch, path, index, record):
        key = (index, record["id"])
        present = self._mirror(name, branch)
        if key in present:
            return
        pt, meta, _mp4 = takes.take_files(path, index, record["id"])
        sub = f"h3_clip_plan/{mirror_name(name, branch)}/latents/clip_{index:03d}"
        self._put(client, pt, pt.name, sub, "output")
        data = {k: v for k, v in record.items() if k != "id"}
        self._put(client, json.dumps(data, indent=1).encode("utf-8"), meta.name, sub, "output")
        present.add(key)

    def _send_chain(self, client, name, branch, path, raw, index, take_id):
        try:
            chain = takes.ancestors(path, raw, index, take_id)
        except ValueError as exc:
            raise StudioError(str(exc)) from exc
        for number, record in reversed(chain):
            self._send_take(client, name, branch, path, number, record)

    def _send_job_chain(self, client, name, branch, path, raw, job):
        """The takes a waiting generation will continue (it has already sent them; checked again)."""
        while job:
            if not job.get("parentToken"):
                return
            local = takes.list_takes(path, raw).get(job["clip"] - 1, [])
            record = next((r for r in local if r["id"].endswith("_" + job["parentToken"])), None)
            if record:
                return self._send_chain(client, name, branch, path, raw, job["clip"] - 1, record["id"])
            job = self.jobs.get(job.get("parentJob"))

    # ------------------------------------------------------------------ following the generations
    def _running_job(self, prompt_id=None):
        with self.lock:
            job = self._by_prompt(prompt_id)
            if job:
                return job
            running = [j for j in self.jobs.values() if j["status"] == "running" and j.get("dispatched")]
            return running[0] if len(running) == 1 else None

    def _keep_preview(self, job, data, mime):
        with self.lock:
            self.previews[job["id"]] = (data, mime)
            job["preview"] = (job.get("preview") or 0) + 1
            job["previewMime"] = mime

    def _logging(self):
        return self.diagnostic is not None and any(j["status"] in ACTIVE for j in self.jobs.values())

    def _on_binary(self, payload):
        info = comfy.parse_binary(payload)
        if self._logging():
            self.diagnostic.binary_message(info, payload)
        if info.get("image"):
            job = self._running_job((info.get("metadata") or {}).get("prompt_id"))
            if job and job["status"] in ACTIVE:
                self._keep_preview(job, info["image"], info.get("mime") or comfy.sniff_mime(info["image"]))

    def _images_in(self, value, found):
        """data:image/... strings inside a JSON message (custom preview widgets send them this way)."""
        if isinstance(value, str) and value.startswith("data:image/") and ";base64," in value:
            head, _, body = value.partition(";base64,")
            try:
                found.append((base64.b64decode(body), head[5:]))
            except ValueError:
                pass
        elif isinstance(value, dict):
            for v in value.values():
                self._images_in(v, found)
        elif isinstance(value, list):
            for v in value:
                self._images_in(v, found)
        return found

    def _on_event(self, msg):
        data = msg.get("data") or {}
        kind = msg.get("type")
        if self._logging():
            self.diagnostic.json_message(msg)
        if kind == "kj_preview_override" and isinstance(data, dict) and data.get("image"):
            try:
                image = base64.b64decode(data["image"])
            except ValueError:
                image = None
            if image:
                mime = data.get("mime") or "image/jpeg"
                if self._logging():
                    saved = self.diagnostic.save_image(image, mime, "kj")
                    self.diagnostic.note(_t("engine.kjnodes_preview_step_bytes_x_fps", v0=data.get('step'), v1=data.get('total'), mime=mime, v3=len(image), v4=data.get('w'), v5=data.get('h'), v6=data.get('fps'), v7=data.get('audio')) + (f" -> {saved}" if saved else ""))
                job = self._running_job()
                if job and job["status"] in ACTIVE:
                    self._keep_preview(job, image, mime)
            return
        if kind not in ("status", "progress", "executing", "execution_start", "execution_cached", "executed",
                        "execution_success", "execution_error", "execution_interrupted", "progress_state", "crystools.monitor"):
            images = self._images_in(data, [])
            if images:
                job = self._running_job(data.get("prompt_id") if isinstance(data, dict) else None)
                if self._logging():
                    for img, mime in images:
                        saved = self.diagnostic.save_image(img, mime, f"json_{kind}")
                        self.diagnostic.note(_t("engine.image_in_the_json_message_bytes", kind=kind, mime=mime, v2=len(img), v3=image_size(img)) + (f" -> {saved}" if saved else ""))
                if job and job["status"] in ACTIVE:
                    self._keep_preview(job, images[-1][0], images[-1][1])
        if kind == "status":
            self.wake.set()
            return
        prompt_id = data.get("prompt_id")
        with self.lock:
            job = self._by_prompt(prompt_id)
            if not job or job["status"] not in ACTIVE:
                return
            now = time.time()
            if kind == "execution_start":
                job["status"] = "running"
                job["step"] = job.get("step") or _t("engine.preparing")
                job.setdefault("t_start", now)
            elif kind == "executing":
                if data.get("node") is None:
                    self.wake.set()
                else:
                    job["status"] = "running"
                    job.setdefault("t_start", now)
                    node = str(data.get("node"))
                    job["step"] = _t(STEP_KEYS[node]) if node in STEP_KEYS else (job.get("step") or _t("engine.preparing"))
                    if node == "25":
                        job.setdefault("t_sample", now)
                    elif node in ("26", "27", "28") and job.get("t_sample"):
                        job.setdefault("t_sample_end", now)
            elif kind == "progress":
                job["status"] = "running"
                job.setdefault("t_start", now)
                job["progress"] = {"value": data.get("value"), "max": data.get("max")}
                if str(data.get("node")) == "25" and data.get("value"):
                    job.setdefault("t_sample", now)
                    job["t_step"] = [int(data["value"]), int(data.get("max") or 0), now]
                if str(data.get("node")) in STEP_KEYS:
                    job["step"] = _t(STEP_KEYS[str(data.get("node"))])
            elif kind in ("execution_success", "execution_error", "execution_interrupted"):
                self.wake.set()

    def _poll_loop(self):
        while True:
            self.wake.wait(1.0)
            self.wake.clear()
            try:
                self._poll()
            except Exception:  # noqa: BLE001 - keep following
                time.sleep(1.0)

    def _poll(self):
        self._follow()
        self._local_assemblies()
        self._dispatch_next()

    def _follow(self):
        with self.lock:
            active = [j for j in self.jobs.values() if j["status"] in ACTIVE and j.get("dispatched")]
            pending = [j for j in self.jobs.values() if j["status"] == "harvest"]
        if not active and not pending:
            return
        client = self.client
        try:
            state = client.queue_state()
        except comfy.ComfyError as exc:
            if exc.unreachable:
                self._comfy_down()
            return
        running = {row[1] for row in state.get("queue_running") or []}
        queued = {row[1] for row in state.get("queue_pending") or []}
        self._count_foreign(state)
        touched = set()
        for job in active:
            pid = job["prompt_id"]
            if pid in running:
                if job["status"] != "running":
                    job["status"] = "running"
                    job["step"] = job.get("step") or _t("engine.preparing")
                continue
            if pid in queued:
                continue
            try:
                entry = client.history(pid).get(pid)
            except comfy.ComfyError:
                continue
            if job.get("requeue") and entry is not None:       # interrupted by « pause immédiate »
                self._requeue(job)
                continue
            with self.lock:
                if entry is None:
                    job["missing"] = job.get("missing", 0) + 1
                    if job.get("requeue") and job["missing"] >= 2:      # interrupted before it started
                        self._requeue(job)
                        continue
                    restarted = (self.comfy_down_at or 0) > (job.get("dispatched_at") or 0)
                    if job["missing"] >= 5 and restarted and job.get("lost", 0) < 2:   # ComfyUI restarted: its queue is gone
                        job["lost"] = job.get("lost", 0) + 1
                        self._requeue(job)
                        continue
                    if job["missing"] >= 5:
                        job["status"], job["error"] = "error", _t("engine.gone_from_the_comfyui_queue_comfyui")
                        for jid in self._dependents(job["id"]):
                            self.jobs[jid].update(status="error", error=_failed_dep(job))
                            if jid in self.order:
                                self.order.remove(jid)
                        touched.add((job["project"], _branch(job)))
                    continue
                status = (entry.get("status") or {})
                if status.get("status_str") == "error" or not status.get("completed", True):
                    messages = status.get("messages") or []
                    err = next((m[1] for m in messages if m and m[0] == "execution_error"), None)
                    interrupted = any(m and m[0] == "execution_interrupted" for m in messages)
                    job["status"] = "error"
                    job["error"] = _t("engine.interrupted") if interrupted and not err else (
                        f"{err.get('node_type', '')} : {err.get('exception_message', _t('engine.error'))}".strip() if err else _t("engine.error"))
                    for jid in self._dependents(job["id"]):
                        self.jobs[jid].update(status="error", error=_failed_dep(job))
                        if jid in self.order:
                            self.order.remove(jid)
                    self._save_queue()
                else:
                    job["status"] = "harvest"
                    pending.append(job)
                touched.add((job["project"], _branch(job)))
        for job in pending:
            self._harvest(client, job)
            touched.add((job["project"], _branch(job)))
        with self.lock:
            for name in {n for n, _b in touched}:
                self._save(name)
        for name, branch in touched:
            self._purge_if_idle(client, name, branch)
        finished_assemblies = [j for j in active + pending if j.get("kind") == "assemble" and j["status"] in ("done", "error")]
        for job in finished_assemblies:
            self._purge_workspace(client, job)

    def _harvest(self, client, job):
        if job.get("kind") == "assemble":
            return self._harvest_assembly(client, job)
        name, branch = job["project"], _branch(job)
        try:
            path = self._project(name)
            plan_file = plan_file_of(name, branch)
            listing = client.takes(plan_file)
            entry = next((c for c in listing.get("clips") or [] if c["index"] == job["clip"]), None)
            take = next((t for t in (entry or {}).get("takes") or [] if t["id"].endswith("_" + job["token"])), None)
            if take is None:
                raise StudioError(_t("engine.generation_finished_but_the_take_cannot"))
            take_id = take["id"]
            pt, meta, mp4 = takes.take_files(path, job["clip"], take_id)
            sub = f"h3_clip_plan/{mirror_name(name, branch)}/latents/clip_{job['clip']:03d}"
            client.download(pt.name, sub, str(pt))
            if take.get("preview"):
                pv = take["preview"]
                client.download(pv["filename"], pv["subfolder"], str(mp4), pv.get("type", "output"))
            record = {k: v for k, v in (take.get("record") or {}).items() if k != "id"}
            record["studio"] = dict(job.get("studio") or {}, prompt_id=job.get("prompt_id"))
            tmp = meta.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, meta)
            raw = json.loads((path / "plan.json").read_text(encoding="utf-8-sig"))
            try:
                # the new take is chosen, unless the selection is in another branch
                selection = takes.read_selection(path)
                local = takes.list_takes(path, raw)
                default = (projects.read_meta(path)["branches"] or [{"id": "b1"}])[0]["id"]
                current = selection.get("branch")
                if current is None:
                    by_id = {r["id"]: r for records in local.values() for r in records}
                    chosen = [by_id[v] for k, v in sorted((k, v) for k, v in selection.items() if k != "branch") if v in by_id]
                    current = takes.take_branch(chosen[0], default) if chosen else None
                if current in (None, branch):
                    takes.select_chain(path, raw, job["clip"], take_id, branch=branch)
            except (ValueError, IndexError, KeyError, StudioError):
                pass
            with self.lock:
                self._mirror(name, branch).add((job["clip"], take_id))
                job["status"], job["take"], job["ended"] = "done", take_id, time.time()
                for other in self.jobs.values():               # planned assemblies waiting for this take
                    pending = other.get("pending") or {}
                    for clip_key, jid in list(pending.items()):
                        if jid == job["id"]:
                            other["takes"][clip_key] = take_id
                            del pending[clip_key]
                            self._save(other["project"])
                self._record_timing(job)
                job["progress"] = None
                self.previews.pop(job["id"], None)
        except (StudioError, comfy.ComfyError, OSError, ValueError) as exc:
            with self.lock:
                job["harvest_tries"] = job.get("harvest_tries", 0) + 1
                if job["harvest_tries"] >= 3:
                    job["status"], job["error"] = "error", _t("engine.cannot_collect_the_take", exc=exc)

    def _harvest_assembly(self, client, job):
        name = job["project"]
        try:
            path = self._project(name)
            entry = client.history(job["prompt_id"]).get(job["prompt_id"]) or {}
            outputs = (entry.get("outputs") or {}).get("10") or {}
            files = [f for f in (outputs.get("gifs") or outputs.get("videos") or outputs.get("images") or [])
                     if str(f.get("filename", "")).lower().endswith((".mp4", ".webm", ".mov", ".mkv"))]
            if not files:
                raise StudioError(_t("engine.assembly_finished_but_the_video_cannot"))
            video = files[-1]
            target = path / "exports" / f"{job['export']}.mp4"
            client.download(video["filename"], video.get("subfolder", ""), str(target), video.get("type", "output"))
            report = (outputs.get("text") or [""])[0]
            self._write_export(path, job, report)
            with self.lock:
                job["status"], job["ended"], job["progress"] = "done", time.time(), None
                self._record_timing(job)
        except (StudioError, comfy.ComfyError, OSError, ValueError) as exc:
            with self.lock:
                job["harvest_tries"] = job.get("harvest_tries", 0) + 1
                if job["harvest_tries"] >= 3:
                    job["status"], job["error"] = "error", _t("engine.cannot_collect_the_video", exc=exc)

    def _purge_workspace(self, client, job):
        """The ComfyUI copy made for one assembly: of no use once it is over."""
        workspace = job.get("workspace")
        if not workspace or not self.studio.config.get("purge_comfy_copy", True):
            return
        name = job["project"]
        try:
            listing = client.takes(plan_file_of(name, workspace))
            items = [{"clip": c["index"], "id": t["id"]} for c in listing.get("clips") or [] for t in c.get("takes") or []]
            if items:
                client.delete_takes(plan_file_of(name, workspace), items)
        except (StudioError, comfy.ComfyError, OSError, ValueError):
            pass
        self.mirror.pop((name, workspace), None)

    def _purge_branch(self, client, name, branch):
        if not self.studio.config.get("purge_comfy_copy", True):
            return
        try:
            listing = client.takes(plan_file_of(name, branch))
            items = [{"clip": c["index"], "id": t["id"]} for c in listing.get("clips") or [] for t in c.get("takes") or []]
            if items:
                client.delete_takes(plan_file_of(name, branch), items)
        except (StudioError, comfy.ComfyError, OSError, ValueError):
            pass
        self.mirror[(name, branch)] = set()

    def _purge_if_idle(self, client, name, branch):
        if not self.studio.config.get("purge_comfy_copy", True):
            return
        with self.launch_lock:
            with self.lock:
                mine = [j for j in self.jobs.values() if j["project"] == name and _branch(j) == branch]
                if any(j["status"] in ACTIVE + ("harvest",) for j in mine):
                    return
                # takes whose copy into the project failed are kept (their files can still be fetched by hand)
                keep = {j["token"] for j in mine if j.get("harvest_tries")}
            try:
                listing = client.takes(plan_file_of(name, branch))
                items = [{"clip": c["index"], "id": t["id"]} for c in listing.get("clips") or [] for t in c.get("takes") or []
                         if t["id"].split("_")[-1] not in keep]
                if items:
                    client.delete_takes(plan_file_of(name, branch), items)
                self.mirror[(name, branch)] = set()
            except (StudioError, comfy.ComfyError, OSError, ValueError):
                pass


def _branch(job):
    return job.get("branch") or "b1"     # generations started before branches existed
