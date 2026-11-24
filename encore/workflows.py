"""Encore - the ComfyUI workflows (API format) of a generation and of an assembly.

Pure functions, no state: the clip workflow (models, LoRA, sampler, preview), the latent upscale in two passes,
the assembly workflow (plugin fallback), what a clip needs from the project and which ComfyUI nodes are missing.
Used by the engine (generation, dispatch).
"""
from __future__ import annotations

from .i18n import t as _t

from . import plan_core, projects
from .projects import StudioError


NEEDED_NODES = ["UNETLoader", "CLIPLoader", "VAELoader", "MiniMaxH3SigmaShift", "MiniMaxH3AudioVAECompatibility",
                "RandomNoise", "BasicGuider", "KSamplerSelect", "BasicScheduler", "SamplerCustomAdvanced", "VAEDecode",
                "VHS_VideoCombine", "H3PlanClip", "H3PlanSaveLatent", "H3PlanReference", "H3PlanVoice"]


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
