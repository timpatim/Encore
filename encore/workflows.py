"""Encore - the ComfyUI workflows (API format) of a generation and of an assembly.

Pure functions, no state: the clip workflow (models, LoRA, sampler, preview), the latent upscale in two passes,
what a clip needs from the project and which ComfyUI nodes are missing.
Used by the engine (generation, dispatch).
"""
from __future__ import annotations

from .i18n import t as _t

from . import plan_core, projects
from .projects import StudioError


NEEDED_NODES = ["UNETLoader", "CLIPLoader", "VAELoader", "MiniMaxH3SigmaShift", "MiniMaxH3AudioVAECompatibility",
                "RandomNoise", "BasicGuider", "KSamplerSelect", "BasicScheduler", "SamplerCustomAdvanced", "VAEDecode",
                "VHS_VideoCombine", "MiniMaxH3ReferenceToVideo", "MiniMaxH3MotionContextSaveLatent", "LoadImage"]
# 0.50: ComfyUI does all the inference with its own nodes and those of ComfyUI-H3-Motion-Context-MultiRef and
# VideoHelperSuite; Encore composes the prompt and prepares the files (prepare.py)
LOAD_LATENT = "MiniMaxH3MotionContextLoadLatent"
FREE_CONTEXT = "MiniMaxH3GeneratedAVMaskedContext"
SONG_CONTEXT = "MiniMaxH3SongMaskedAVContext"
VIDEO_CONTEXT = "MiniMaxH3ExistingVideoMaskedContext"
REF_GROUPS = ("ref_image", "ref_video", "ref_video_audio", "ref_audio")


def ref_inputs(info):
    """How MiniMaxH3ReferenceToVideo names its growing inputs, read in /object_info: {group: (pattern, first
    number)}; a pattern takes the number (« ref_images.ref_image_{} »). Default: the form of ComfyUI's workflows,
    numbered from 0."""
    spec = ((info or {}).get("MiniMaxH3ReferenceToVideo") or {}).get("input") or {}
    keys = set((spec.get("required") or {}).keys()) | set((spec.get("optional") or {}).keys())
    out = {}
    for group in REF_GROUPS:
        found = None
        for form in (group + "s." + group + "_{}", group + "_{}"):
            numbers = sorted(int(k[len(form) - 2:]) for k in keys if k.startswith(form[:-2]) and k[len(form) - 2:].isdigit())
            if numbers:
                found = (form, numbers[0])
                break
        out[group] = found or (group + "s." + group + "_{}", 0)
    return out


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
    """The workflow of one take (0.50: native nodes, MultiRef and VHS only). job:
    settings, mode, prompt (composed by Encore), length (frames), ref_image_size, seed,
    images / voices: [ComfyUI input path] in the order of <Picture i> / <Audio j>,
    song: input path (music video, already shifted on the plan's timeline), clip_start: seconds in it,
    context: frames continued, feather: audio feather ticks,
    source: None | {"latent": path from ComfyUI's output folder} | {"video": input path} (the take or the video it
    continues), edit: None | {"video": input path, "sound": bool} (the slice of the edited video),
    save_prefix / preview_prefix: names in ComfyUI's output folder, names: ref_inputs(object_info),
    upscale, context_latent."""
    s = job["settings"]
    p = {}
    model = _model_chain(p, s)
    p["5"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": s["clip_name"], "type": s["clip_type"], "device": "default"}}
    p["6"] = {"class_type": "VAELoader", "inputs": {"vae_name": s["video_vae"]}}
    p["7"] = {"class_type": "VAELoader", "inputs": {"vae_name": s["audio_vae"]}}
    p["8"] = {"class_type": "MiniMaxH3AudioVAECompatibility", "inputs": {"audio_vae": ["7", 0]}}
    free = job["mode"] == "free"
    names = job.get("names") or ref_inputs(None)
    ref_name = lambda group, k: names[group][0].format(names[group][1] + k)  # noqa: E731
    r2v = {"clip": ["5", 0], "vae": ["6", 0], "audio_vae": ["8", 0], "prompt": job["prompt"], "width": int(s["width"]),
           "height": int(s["height"]), "length": int(job["length"]), "ref_image_size": job.get("ref_image_size") or "match"}
    for k, image in enumerate(job.get("images") or []):
        node = str(30 + k)
        p[node] = {"class_type": "LoadImage", "inputs": {"image": image}}
        r2v[ref_name("ref_image", k)] = [node, 0]
    for k, voice in enumerate(job.get("voices") or []):
        node = str(50 + k)
        p[node] = {"class_type": "LoadAudio", "inputs": {"audio": voice}}
        r2v[ref_name("ref_audio", k)] = [node, 0]
    edit = job.get("edit")
    if edit:
        p["11"] = _load_video(edit["video"])
        r2v[ref_name("ref_video", 0)] = ["11", 0]
        if edit.get("sound"):
            r2v[ref_name("ref_video_audio", 0)] = ["11", 2]
    p["20"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": r2v}
    # the latent to sample: the empty one, or with the end of the take (or video) it continues and the song protected
    source, latent, sound = job.get("source") or {}, ["20", 1], None
    if source.get("latent"):
        p["18"] = {"class_type": LOAD_LATENT, "inputs": {"latent_path": source["latent"], "clip_index": 0}}
    if source.get("video"):
        p["12"] = _load_video(source["video"])
    if not free:
        p["9"] = {"class_type": "LoadAudio", "inputs": {"audio": job["song"]}}
        ctx = {"latent": ["20", 1], "audio_vae": ["8", 0], "master_audio": ["9", 0], "clip_start_seconds": round(float(job["clip_start"]), 6),
               "context_length": int(job["context"]) if source else 0, "source_fps": 24.0, "crop": "disabled"}
        if source.get("latent"):
            ctx["source_latent"] = ["18", 0]
        elif source.get("video"):
            ctx.update(vae=["6", 0], source_frames=["12", 0])
        p["19"] = {"class_type": SONG_CONTEXT, "inputs": ctx}
        latent, sound = ["19", 0], ["19", 2]
    elif source.get("latent"):
        p["19"] = {"class_type": FREE_CONTEXT, "inputs": {"latent": ["20", 1], "source_latent": ["18", 0],
                                                          "context_length": int(job["context"]), "audio_feather_ticks": int(job.get("feather", 8))}}
        latent = ["19", 0]
    elif source.get("video"):
        p["19"] = {"class_type": VIDEO_CONTEXT, "inputs": {"latent": ["20", 1], "vae": ["6", 0], "audio_vae": ["8", 0],
                                                           "source_frames": ["12", 0], "source_audio": ["12", 2], "source_fps": 24.0,
                                                           "context_length": int(job["context"]), "crop": "disabled",
                                                           "audio_feather_ticks": int(job.get("feather", 8))}}
        latent = ["19", 0]
    job["latent_link"] = latent
    p["21"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(job["seed"])}}
    p["22"] = {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": ["20", 0]}}
    p["23"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": s["sampler_name"]}}
    p["24"] = {"class_type": "BasicScheduler", "inputs": {"model": model, "scheduler": s["scheduler"], "steps": int(s["steps"]), "denoise": 1.0}}
    p["25"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["21", 0], "guider": ["22", 0], "sampler": ["23", 0],
                                                                 "sigmas": ["24", 0], "latent_image": latent}}
    p["26"] = {"class_type": "MiniMaxH3MotionContextSaveLatent", "inputs": {"latent": ["25", 0], "filename_prefix": job["save_prefix"],
                                                                           "clip_index": 1}}
    p["27"] = {"class_type": "VAEDecode", "inputs": {"samples": ["25", 0], "vae": ["6", 0]}}
    if free:
        p["29"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["25", 0], "vae": ["8", 0]}}
        sound = ["29", 0]
    p["28"] = {"class_type": "VHS_VideoCombine", "inputs": {
        "images": ["27", 0], "audio": sound, "frame_rate": 24, "loop_count": 0,
        "filename_prefix": job["preview_prefix"], "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": int(s["crf"]),
        "save_metadata": False, "trim_to_audio": False, "pingpong": False, "save_output": True}}
    if job.get("upscale"):
        add_upscale(p, job, model)
    return p


def _load_video(path):
    """A prepared piece of video (prepare.video_piece: already at the size, 24 fps), with its sound."""
    return {"class_type": "VHS_LoadVideo", "inputs": {"video": path, "force_rate": 24, "custom_width": 0, "custom_height": 0,
                                                      "frame_load_cap": 0, "skip_first_frames": 0, "select_every_nth": 1}}


def saved_latent_name(save_prefix):
    """(subfolder, file name) in ComfyUI's output folder of the latent node 26 saves (MultiRef's fixed slot 1)."""
    sub, _, stem = save_prefix.rpartition("/")
    return sub, f"{stem}_00001.safetensors"


def clip_needs(plan, index, settings):
    """The files a clip uses (normalized plan v7: its subjects' pictures and voices, its anchors, the video it
    continues or edits) with their paths in the project, and what is missing. settings: {"video": the project's
    video file, "song": the song}."""
    clip = plan["clips"][index - 1]
    free = plan["mode"] == "free"
    problems, refs = [], []
    files = (clip.get("compose") or {}).get("files") or {}
    for name in clip["refs"]:
        entry = files.get(name) or plan_core.file_of(plan, name)
        rel = entry.get("file") or None
        kind = entry.get("kind")
        if not rel and kind != "voice":            # a voice without its file: H3 chooses one (its lines are removed)
            problems.append(_t("engine.file_not_chosen", name=name))
        refs.append({"name": name, "image": rel if kind == "image" else None, "voice": rel if kind == "voice" and free else None})
    if not free and not settings.get("song"):
        problems.append(_t("engine.song_not_chosen"))
    spec = plan.get("start_video")
    if index == 1 and clip["continue"] and spec:      # clip 1 continues the start video
        if not settings.get("video"):
            problems.append(_t("engine.start_video_not_chosen"))
        refs.append({"name": spec["ref"], "image": None, "voice": None, "video": settings.get("video") or None})
    edit = plan.get("edit_video")
    if edit and plan_core.edit_slice(plan, index):    # the clips inside the segment edit their slice of the video
        if not settings.get("video"):
            problems.append(_t("engine.edit_video_not_chosen"))
        refs.append({"name": edit["ref"], "image": None, "voice": None, "video": settings.get("video") or None})
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
    at the branch size. The latent prepared at the branch size (continuation frames, song and their noise masks)
    is split and recombined with ComfyUI's own nodes."""
    s, up = job["settings"], job["upscale"]
    width, height = int(s["width"]), int(s["height"])
    music = job["mode"] != "free"
    p["60"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": job.get("latent_link") or ["20", 1]}}
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
    for node in ("26", "27", "29"):          # the latent saved and decoded: the one of the second pass
        if node in p:
            p[node]["inputs"]["latent" if node == "26" else "samples"] = ["75", 0]
    return p


def missing_nodes(info, settings, music=False, upscale=None, video=False, voices=False, continues=False):
    """The nodes a generation needs that ComfyUI does not have (0.50: native, MultiRef and VHS nodes)."""
    need = list(NEEDED_NODES)
    if video:
        need += ["VHS_LoadVideo", VIDEO_CONTEXT]
    if music:
        need += ["LoadAudio", SONG_CONTEXT]
    else:
        need.append("VAEDecodeAudio")
    if voices:
        need.append("LoadAudio")
    if continues:
        need += [LOAD_LATENT, FREE_CONTEXT if not music else SONG_CONTEXT]
    if upscale:
        need += UPSCALE_NODES + UPSCALER_NODES[upscale["upscaler"]]
        if upscale.get("pass2_loras"):
            need.append("LoraLoaderModelOnly")
    if settings.get("attention"):
        need.append("ModelAttentionBackend")
    if projects.active_loras(settings):
        need.append("LoraLoaderModelOnly")
    if settings.get("preview_mode") == "kj":
        need.append("ModelPreviewOverrideKJ")
    out = []
    for n in need:
        if n not in info and n not in out:
            out.append(n)
    return out
