"""Encore - projects on disk (standard library only).

A project is a folder of the projects root:

    <root>/<name>/
        project.json     studio settings: models, sampling, picture size, which file is which reference
        plans.json       the master plan of each branch and the suite of each take (encore/plans.py)
        selection.json   the selected twig
        refs/images/     imported reference images
        refs/voices/     imported voice samples
        refs/songs/      imported songs
        refs/videos/     imported videos (a plan can start from a segment of one)
        takes/           generated takes (step 2)
        store/           files kept once, by content hash (step 3)
        exports/         final videos (step 4)
"""
from __future__ import annotations

from .i18n import t as _t
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from . import plan_core, takes

STUDIO_VERSION = "0.45.1"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
RESOURCE_KINDS = {
    "images": (".png", ".jpg", ".jpeg", ".webp", ".bmp"),
    "voices": (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"),
    "songs": (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"),
    "videos": (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"),
}
SUBDIRS = ("refs/images", "refs/voices", "refs/songs", "refs/videos", "takes", "store", "exports")
DEFAULT_SETTINGS = {
    "unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default",
    "clip_name": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors", "clip_type": "minimax",
    "video_vae": "minimax_h3_video_vae_int8_convrot.safetensors", "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    "attention": "comfy kitchen attention",
    "loras": [{"name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "strength": 1.0, "enabled": True}],
    "shift_video": 12.0, "shift_audio": 3.0, "sampler_name": "res_multistep", "scheduler": "simple", "steps": 8,
    "crf": 19,
    # live preview: "comfy" (ComfyUI's own) or "kj" (KJNodes Model Preview Override)
    "preview_mode": "comfy", "kj_tiny_vae": "none", "kj_frames": -1, "kj_fps": 7, "kj_audio": True,
    "kj_max_res": 512, "kj_quality": 80,
}


class StudioError(Exception):
    """An error meant for the user (shown as is). ``code``: a fixed word the interface can test (the message
    itself is translated)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- configuration
def default_config():
    return {
        "projects_root": str(Path.home() / "Documents" / _t("projects.encore_projects")),
        "comfy_url": "http://127.0.0.1:8188",
        "purge_comfy_copy": True,       # remove ComfyUI's copy of the takes once they are in the project
        "assembly_engine": "ffmpeg",    # final videos made by Encore with ffmpeg ("plugin": by ComfyUI, as before 0.40)
    }


def load_config(path: Path):
    config = default_config()
    try:
        config.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return config


def migrate_settings(settings):
    """Settings of version 0.2.2 and older had a single LoRA (lora_name, lora_strength)."""
    out = dict(settings)
    if "loras" not in out:
        name = out.get("lora_name")
        out["loras"] = [{"name": name, "strength": float(out.get("lora_strength", 1.0)), "enabled": True}] if name else []
    out.pop("lora_name", None)
    out.pop("lora_strength", None)
    clean = []
    for item in out.get("loras") or []:
        if isinstance(item, dict):
            clean.append({"name": str(item.get("name") or ""), "strength": float(item.get("strength", 1.0)),
                          "enabled": bool(item.get("enabled", True))})
    out["loras"] = clean
    return out


BRANCH_SET_KEYS = ("refs", "song", "width", "height", "ref_image_size")     # what a branch holds (no longer in the project settings)
DEFAULT_BRANCH_SIZE = (960, 544)        # 16:9, 0.5 megapixel as ComfyUI counts it (1 MP = 1024 × 1024)
REF_SIZES = ("match", "max")             # how H3 sizes the reference pictures (a branch setting, no longer in the plan)
DEFAULT_REF_SIZE = "max"


# latent upscale (branch setting): first pass at a lower size, latent upscale, second pass at the branch size
DEFAULT_UPSCALE = {
    "enabled": False,
    "start_mp": 0.2,                    # first pass, in megapixels as ComfyUI counts them (1 MP = 1024 x 1024)
    "pass1_mode": "split",              # "split": first steps of the normal schedule ; "manual": sigmas below
    "pass1_steps": 4,
    "pass1_sigmas": "0.9231, 0.8780, 0.8000, 0.6316",
    "pass2_mode": "manual",             # "manual": sigmas below ; "rest": the rest of the normal schedule
    "pass2_sigmas": "0.9035, 0.8000, 0.6316, 0.3158, 0",
    "upscaler": "lbh3d",                # "lbh3d" / "lbh2d" (LBH-123-AI nodes) or "builtin" (ComfyUI's node)
    "model": "",                        # upscale model file
    "sharpness": 1,                     # LBH 2D only
    "pass2_loras": None,                # None = the same LoRA as the first pass, else a list like settings["loras"]
    "pass2_sampler": "",                # "" = the same sampler
}
UPSCALE_KEYS = set(DEFAULT_UPSCALE)


def upscale_of(branch):
    return clean_upscale(branch.get("upscale"))


def clean_upscale(value):
    """A complete set of upscale settings: the known keys of value over the defaults."""
    if value is not None and not isinstance(value, dict):
        raise StudioError(_t("projects.upscale_invalid_settings"))
    out = json.loads(json.dumps(DEFAULT_UPSCALE))
    out.update({k: v for k, v in (value or {}).items() if k in UPSCALE_KEYS})
    return out


def start_size(mp, width, height):
    """First-pass size: same proportions as the branch, mp megapixels (1024 x 1024), multiples of 32."""
    ratio = width / height
    pixels = float(mp) * 1024 * 1024
    r32 = lambda v: max(64, int(round(v / 32)) * 32)
    return r32((pixels * ratio) ** 0.5), r32((pixels / ratio) ** 0.5)


def check_ref_size(value):
    if value not in REF_SIZES:
        raise StudioError(_t("projects.reference_size_match_or_max"))
    return value
BRANCH_COLORS = ["#4f8cff", "#e5a50a", "#2fbf71", "#d65db1", "#ff6b4a", "#00b5c8", "#9b7bff", "#b8b830"]


def strip_branch_keys(settings):
    return {k: v for k, v in settings.items() if k not in BRANCH_SET_KEYS}


def active_loras(settings):
    return [l for l in settings.get("loras") or [] if l.get("enabled") and l.get("name")]


# --------------------------------------------------------------------------- LoRA "en plus" and upscale per take
# Project LoRA stack (settings) is always used. On top of it: the branch's LoRA. A generation can also give its exact
# list (launch panel), which replaces the branch's. Upscale: the branch's settings, unless the generation gives its own
# (launch panel: the branch's settings changed for this take, « enabled » included).


def clean_loras(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise StudioError(_t("projects.lora_invalid_list"))
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise StudioError(_t("projects.lora_invalid_entry"))
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            strength = round(float(item.get("strength", 1.0)), 4)
        except (TypeError, ValueError):
            raise StudioError(_t("projects.lora_invalid_strength", name=name))
        out.append({"name": name, "strength": strength})
    return out


def merge_loras(*lists):
    """Later lists win for a file present in an earlier one (its strength replaces the earlier one, in place)."""
    out = []
    for items in lists:
        for item in items or []:
            same = next((x for x in out if x["name"] == item["name"]), None)
            if same:
                same["strength"] = item["strength"]
            else:
                out.append({"name": item["name"], "strength": item["strength"]})
    return out


def default_extra_loras(branch):
    """The LoRA a branch adds to its takes (on top of the project stack)."""
    return clean_loras(branch.get("loras"))


# --------------------------------------------------------------------------- default settings
# The Studio's own settings: a template copied into every new project (models, LoRA, sampling, previews)
# with the picture size of its first branch. They are used for nothing else.
def load_defaults(path: Path):
    out = dict(DEFAULT_SETTINGS)
    out["first_branch_size"] = list(DEFAULT_BRANCH_SIZE)
    out["first_branch_ref_size"] = DEFAULT_REF_SIZE
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        size = saved.pop("first_branch_size", None)
        ref_size = saved.pop("first_branch_ref_size", None)
        if ref_size in REF_SIZES:
            out["first_branch_ref_size"] = ref_size
        out.update(strip_branch_keys(migrate_settings(saved)))
        if isinstance(size, list) and len(size) == 2:
            out["first_branch_size"] = [int(size[0]), int(size[1])]
    except (OSError, ValueError, TypeError):
        pass
    return out


def save_defaults(path: Path, data):
    if not isinstance(data, dict):
        raise StudioError(_t("projects.invalid_settings"))
    current = load_defaults(path)
    size = data.get("first_branch_size", current["first_branch_size"])
    try:
        size = [int(size[0]), int(size[1])]
    except (TypeError, ValueError, IndexError) as exc:
        raise StudioError(_t("projects.invalid_first_branch_size")) from exc
    problem = plan_core.check_size(*size)
    if problem:
        raise StudioError(problem)
    ref_size = check_ref_size(data.get("first_branch_ref_size", current["first_branch_ref_size"]))
    settings = strip_branch_keys(migrate_settings({k: v for k, v in data.items() if k not in ("first_branch_size", "first_branch_ref_size")}))
    out = dict(current)
    out.update(settings)
    out["first_branch_size"] = size
    out["first_branch_ref_size"] = ref_size
    _write_json(path, out)
    return out


def save_config(path: Path, config):
    _write_json(path, config)


# --------------------------------------------------------------------------- helpers
def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check_name(name: str) -> str:
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        raise StudioError(_t("projects.invalid_project_name_letters_digits_and"))
    return name


def project_dir(root, name) -> Path:
    path = Path(root) / check_name(name)
    if not (path / "project.json").is_file():
        raise StudioError(_t("projects.project_does_not_exist_in", name=name, root=root))
    return path


def safe_join(base: Path, relative: str) -> Path:
    """A path inside base, refusing anything that would leave it."""
    base = base.resolve()
    target = (base / str(relative).replace("\\", "/").lstrip("/")).resolve()
    if base != target and base not in target.parents:
        raise StudioError(_t("projects.path_refused"))
    return target


def safe_filename(name: str) -> str:
    name = os.path.basename(str(name).replace("\\", "/")).strip()
    name = re.sub(r"[^\w.\- ()]+", "_", name, flags=re.UNICODE).strip(" .")
    if not name:
        raise StudioError(_t("projects.empty_file_name"))
    return name[:120]


# --------------------------------------------------------------------------- projects
def skeleton_plan(name: str, mode: str):
    plan = {"version": plan_core.PLAN_VERSION, "project": name, "mode": mode, "refs": {}, "context_frames": 39, "crossfade_frames": 0, "clips": []}
    if mode == "music_video":
        plan["song"] = {"file": "", "duration_seconds": 60}
    clip = {"name": "clip_001", "frames": 209, "continue": False, "refs": [],
            "prompt": "subject_definitions:\n\n\nsummary:\n[reference generation] \n\nretention_analysis:\n\n\n"
                      "detailed_description:\nThe target video is ...\n[Shot 1] \n\noverall_soundscape:\n\n\n"
                      "non_diegetic_music:\n" + ("None." if mode == "free" else "")}
    if mode == "free":
        clip["dialogue"] = []
    plan["clips"].append(clip)
    return plan


def create_project(root, name: str, mode: str, defaults=None):
    name = check_name(name)
    if mode not in ("free", "music_video"):
        raise StudioError(_t("projects.unknown_mode"))
    path = Path(root) / name
    if path.exists():
        raise StudioError(_t("projects.a_folder_already_exists_in", name=name, root=root))
    for sub in SUBDIRS:
        (path / sub).mkdir(parents=True, exist_ok=True)
    now = time.time()
    defaults = dict(defaults or DEFAULT_SETTINGS)
    first = defaults.pop("first_branch_size", list(DEFAULT_BRANCH_SIZE))
    first_ref = defaults.pop("first_branch_ref_size", DEFAULT_REF_SIZE)
    _write_json(path / "project.json", {"studio_version": STUDIO_VERSION, "created": now,
                                        "settings": strip_branch_keys(migrate_settings(defaults)),
                                        "first_branch_size": first, "first_branch_ref_size": first_ref,
                                        "legacy_ref_image_size": "match", "branches": [],
                                        "essence": {"mode": mode, "video": "none", "context_frames": plan_core.DEFAULT_CONTEXT},
                                        "song": ""})
    create_branch(root, name, master=skeleton_plan(name, mode))
    return read_project(root, name)


def list_projects(root):
    from . import plans
    root = Path(root)
    out = []
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not (child / "project.json").is_file():
            continue
        item = {"name": child.name, "mode": None, "clips": 0, "updated": 0}
        try:
            meta = _read_json(child / "project.json")
            first = (meta.get("branches") or [{}])[0].get("id")
            plan = plans.load(child)["masters"].get(first) or {}
            item["mode"] = plan_core.plan_mode(plan) if plan else None
            item["clips"] = len(plan.get("clips") or [])
            files = [child / "project.json", child / plans.FILE]
            item["updated"] = max(f.stat().st_mtime for f in files if f.is_file())
        except (OSError, ValueError, AttributeError):
            item["error"] = "projet illisible"
        out.append(item)
    return out


def read_meta(path: Path):
    """project.json (projects made before 0.42 are not read: they are recreated by importing their plan)."""
    meta = _read_json(path / "project.json")
    meta.setdefault("branches", [])
    for branch in meta["branches"]:
        if branch.get("ref_image_size") not in REF_SIZES:
            branch["ref_image_size"] = DEFAULT_REF_SIZE
        branch["song"] = meta.get("song") or ""        # 0.43: the song is the project's, the same in every branch
    return meta


# --------------------------------------------------------------------------- the essence of the project (0.43)
# What the video is: music video or free, made from no video, continuing one or editing one, and the context between
# clips. The same for every branch (the plans carry it in their header); it can change while the project has no take.
VIDEO_KINDS = ("none", "continue", "edit")


def plan_essence(plan):
    plan = plan or {}
    video = "continue" if plan.get("start_video") else "edit" if plan.get("edit_video") else "none"
    return {"mode": plan.get("mode") if plan.get("mode") in ("free", "music_video") else "free", "video": video,
            "context_frames": int(plan.get("context_frames", plan_core.DEFAULT_CONTEXT))}


def project_essence(path: Path, meta=None):
    from . import plans
    meta = meta or read_meta(path)
    if meta.get("essence"):
        return dict(meta["essence"])
    masters = plans.load(path)["masters"]
    first = masters.get(meta["branches"][0]["id"]) if meta["branches"] else None
    return plan_essence(first)


def apply_essence(plan, essence):
    """The plan with the project's mode, video and context (same changes as the plan editor makes)."""
    plan = json.loads(json.dumps(plan or {}))
    clips = [c for c in plan.get("clips") or [] if isinstance(c, dict)]
    mode = essence["mode"]
    if plan.get("mode") != mode:
        plan["mode"] = mode
        if mode == "free":
            plan.pop("song", None)
            for c in clips:
                if not isinstance(c.get("dialogue"), list):
                    c["dialogue"] = []
        else:
            plan.pop("audio_feather_ticks", None)
            plan.setdefault("song", {"file": "", "duration_seconds": 60})
    plan["context_frames"] = int(essence["context_frames"])
    current = plan_essence(plan)["video"]
    want = essence["video"] if not (essence["video"] == "edit" and mode != "free") else "none"
    if current != want:
        old = plan.get("start_video") or plan.get("edit_video")
        ref = (old or {}).get("ref")
        refs = dict(plan.get("refs") or {})
        if not ref:
            ref, k = "video", 2
            while ref in refs:
                ref, k = f"video_{k}", k + 1
        plan.pop("start_video", None)
        plan.pop("edit_video", None)
        if want == "none":
            refs.pop(ref, None)
            if clips:
                clips[0]["continue"] = False
        elif want == "continue":
            refs[ref] = _t("plan.start_video_ref_desc")
            plan["start_video"] = {"ref": ref, "start": (old or {}).get("start", 0), "end": (old or {}).get("end", 4)}
            if clips:
                clips[0]["continue"] = True
        else:
            refs[ref] = _t("plan.edit_video_ref_desc")
            plan["edit_video"] = {"ref": ref, "start": (old or {}).get("start", 0), "end": (old or {}).get("end", 10)}
            if clips:
                clips[0]["continue"] = False
        plan["refs"] = refs
    return plan


def _propagate_essence(path: Path, meta, essence, skip=None):
    from . import plans
    data = plans.load(path)
    for branch_id, master in list(data["masters"].items()):
        if branch_id != skip:
            data["masters"][branch_id] = apply_essence(master, essence)
    plans.save(path, data)
    meta["essence"] = essence
    _write_json(path / "project.json", meta)


def fit_essence(path: Path, plan, branch_id=None, meta=None):
    """A plan saved or imported: while the project has no take, its mode, video and context become the project's
    (every master plan follows); after, the project's are imposed on it."""
    meta = meta or read_meta(path)
    if branches_with_takes(path, meta):
        return apply_essence(plan, project_essence(path, meta))
    essence = plan_essence(plan)
    if essence != project_essence(path, meta):
        _propagate_essence(path, meta, essence, skip=branch_id)
    return plan


def set_essence(root, name, changes):
    """« Réglages du projet »: mode, video (none, continue, edit), context, song, video file. Refused once the
    project has takes."""
    path = project_dir(root, name)
    meta = read_meta(path)
    essence = project_essence(path, meta)
    new = dict(essence)
    if "mode" in changes:
        if changes["mode"] not in ("free", "music_video"):
            raise StudioError(_t("projects.unknown_mode"))
        new["mode"] = changes["mode"]
    if "video" in changes:
        if changes["video"] not in VIDEO_KINDS:
            raise StudioError(_t("projects.unknown_video_kind"))
        new["video"] = changes["video"]
    if new["video"] == "edit" and new["mode"] != "free":
        new["video"] = "none"
    if "context_frames" in changes:
        new["context_frames"] = int(changes["context_frames"])
    song = changes.get("song", meta.get("song") or "")
    if song and not (safe_join(path, song)).is_file():
        raise StudioError(_t("engine.song_not_found", v0=song))
    if branches_with_takes(path, meta) and (new != essence or (song or "") != (meta.get("song") or "")):
        raise StudioError(_t("projects.project_frozen"))
    meta["song"] = song or ""
    if new != essence:
        _propagate_essence(path, meta, new)
    else:
        meta["essence"] = new
        _write_json(path / "project.json", meta)
    if "video_file" in changes:
        set_start_video_file(root, name, changes["video_file"])
    return read_project(root, name)


def read_project(root, name):
    """The project, with the plan of the selected twig (or the master plan of the selected branch)."""
    from . import plans
    path = project_dir(root, name)
    meta = read_meta(path)
    saved = meta.get("settings") or {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update(strip_branch_keys(migrate_settings(saved)) if saved else {})
    twig = selected_plan(path, meta)
    errors, warnings = plan_core.validate(json.loads(json.dumps(twig["plan"]))) if twig["plan"] else (["no plan"], [])
    return {"name": path.name, "path": str(path), "plan": twig["plan"], "plan_locked": twig["locked"],
            "plan_branch": twig["branch"], "plan_leaf": twig["leaf"], "plan_takes": twig["takes"],
            "settings": settings, "branches": meta["branches"],
            "branches_with_takes": sorted(branches_with_takes(path, meta)),
            "branch_states": branch_states(path, meta),
            "essence": project_essence(path, meta), "song": meta.get("song") or "",
            "project_has_takes": bool(branches_with_takes(path, meta)),
            "segments": {bid: (m or {}).get("start_video") or (m or {}).get("edit_video")
                         for bid, m in plans.load(path)["masters"].items()},
            "masters": {bid: len((m or {}).get("clips") or []) for bid, m in plans.load(path)["masters"].items()},
            "legacy_ref_image_size": meta.get("legacy_ref_image_size") or "match",
            "start_video_file": meta.get("start_video_file") or None,
            "resources": list_resources(root, name), "validation": {"errors": errors, "warnings": warnings}}


def selected_plan(path: Path, meta=None):
    """{"plan", "locked", "branch", "leaf", "takes"} of the selection: the twig it holds, or the master plan of
    its branch (or of the first branch) when no take is chosen."""
    from . import plans
    meta = meta or read_meta(path)
    selection = takes.read_selection(path)
    branch = selection.get("branch") or (meta["branches"][0]["id"] if meta["branches"] else None)
    _index, leaf = takes.leaf(selection)
    if branch is None:
        return {"plan": None, "locked": 0, "branch": None, "leaf": None, "takes": {}}
    try:
        twig = plans.plan_of(path, branch, leaf, project_name=path.name)
    except StudioError:
        leaf = None
        twig = plans.plan_of(path, branch, None, project_name=path.name)
    return {"plan": twig["plan"], "locked": twig["locked"], "branch": branch, "leaf": leaf,
            "takes": {str(k): v for k, v in twig["takes"].items()}}


def branches_with_takes(path: Path, meta=None):
    """Branches having takes: their own, or clips taken over from another branch (duplication)."""
    meta = meta or read_meta(path)
    own = {takes.take_branch(r, None) for records in takes.list_takes(path).values() for r in records} - {None}
    return own | {b["id"] for b in meta["branches"] if branch_base(b)}


def branch_base(branch):
    """[take id of clip 1, …, of clip k]: the clips a duplicated branch takes over from another one (by reference)."""
    return list(((branch or {}).get("base") or {}).get("takes") or [])


def refs_used(path: Path, branch_id, meta=None):
    """The reference names the takes of a branch use (its own takes and the ones it takes over): their files can
    no longer change in this branch."""
    meta = meta or read_meta(path)
    branch = next((b for b in meta["branches"] if b["id"] == branch_id), None)
    base = set(branch_base(branch))
    used = set()
    for records in takes.list_takes(path).values():
        for r in records:
            if takes.take_branch(r, None) == branch_id or r["id"] in base:
                clip = (((r.get("studio") or {}).get("portion") or {}).get("clip") or {})
                used.update(str(n) for n in clip.get("refs") or [])
                used.update((r.get("studio") or {}).get("files", {}).keys())
    return used


def branch_states(path: Path, meta=None):
    """{branch id: {"has_takes", "refs_used": [names], "base": [take ids]}}: what the branch settings grey out."""
    meta = meta or read_meta(path)
    with_takes = branches_with_takes(path, meta)
    return {b["id"]: {"has_takes": b["id"] in with_takes, "refs_used": sorted(refs_used(path, b["id"], meta)),
                      "base": branch_base(b), "base_from": (b.get("base") or {}).get("from")}
            for b in meta["branches"]}


# --------------------------------------------------------------------------- start video
# The video a plan starts from (start_video) is one file for the whole project, chosen in the plan settings;
# every branch uses it, as if each one had it as the file of the plan's start_video reference.
def set_start_video_file(root, name, rel):
    path = project_dir(root, name)
    meta = read_meta(path)
    if (rel or None) != (meta.get("start_video_file") or None) and branches_with_takes(path, meta):
        raise StudioError(_t("projects.branch_frozen", what=_t("takes.the_start_video")))
    if rel:
        file = safe_join(path, rel)
        if not rel.startswith("refs/videos/") or not file.is_file():
            raise StudioError(_t("projects.start_video_file_not_found", file=rel))
        meta["start_video_file"] = rel
    else:
        meta.pop("start_video_file", None)
    _write_json(path / "project.json", meta)
    return {"start_video_file": meta.get("start_video_file")}


plan_video = takes.plan_video


def effective_refs(path: Path, branch, plan):
    """The references of a branch, with the project's video for the plan's start_video / edit_video reference."""
    refs = dict(branch.get("refs") or {})
    spec = plan_video(plan)
    file = read_meta(path).get("start_video_file") if spec else None
    if spec and spec.get("ref"):
        refs[spec["ref"]] = {"image": None, "voice": None, "video": file or None}
    return refs


# --------------------------------------------------------------------------- branches
# A branch starts at clip 1 and holds its own set: the reference files (image, voice) and the song.
def find_branch(branches, branch_id):
    for branch in branches:
        if branch["id"] == branch_id:
            return branch
    raise StudioError(_t("projects.unknown_branch", branch_id=branch_id))


def _branch_number(branch_id):
    return int(branch_id[1:]) if isinstance(branch_id, str) and branch_id[1:].isdigit() else 0


def next_branch_number(path: Path, meta):
    """A number never used before in the project (deleted branches included)."""
    used = [int(meta.get("branch_seq") or 0)] + [_branch_number(b["id"]) for b in meta["branches"]]
    return max(used + [0]) + 1


def create_branch(root, name, master=None, source=None, take_over=None, label=None):
    """A new branch. Its settings and its master plan are copies of `source` (default: the last branch created);
    master: its master plan instead (a plan file). take_over: [take ids of clips 1..k] of a twig of the source
    branch the new branch takes over (duplication with clips: by reference, nothing is copied); its master plan is
    then the plan of that twig (`master`, composed by the caller)."""
    from . import plans
    path = project_dir(root, name)
    meta = read_meta(path)
    branches = meta["branches"]
    number = next_branch_number(path, meta)
    meta["branch_seq"] = number
    last = max(branches, key=lambda b: b.get("created", 0)) if branches else None
    if source:
        last = find_branch(branches, source)
    branch = {"id": f"b{number}", "name": _t("projects.branch", number=number), "color": BRANCH_COLORS[(number - 1) % len(BRANCH_COLORS)],
              "refs": json.loads(json.dumps(last["refs"])) if last else {}, "song": last["song"] if last else "",
              "width": int(last.get("width", DEFAULT_BRANCH_SIZE[0])) if last else int((meta.get("first_branch_size") or DEFAULT_BRANCH_SIZE)[0]),
              "height": int(last.get("height", DEFAULT_BRANCH_SIZE[1])) if last else int((meta.get("first_branch_size") or DEFAULT_BRANCH_SIZE)[1]),
              "ref_image_size": (last.get("ref_image_size") if last else meta.get("first_branch_ref_size")) or DEFAULT_REF_SIZE,
              "upscale": json.loads(json.dumps(last.get("upscale") or DEFAULT_UPSCALE)) if last else json.loads(json.dumps(DEFAULT_UPSCALE)),
              "loras": clean_loras(last.get("loras")) if last else [],
              "created": time.time()}
    if label and str(label).strip():
        branch["name"] = str(label).strip()[:60]
    if take_over:
        branch["base"] = {"from": last["id"], "takes": list(take_over)}
    branches.append(branch)
    _write_json(path / "project.json", meta)
    if master is None:
        master = (plans.master(path, last["id"]) if last else None) or skeleton_plan(path.name, "free")
    master = strip_seeds(master)
    master["project"] = path.name
    plans.set_master(path, branch["id"], master)
    return {"branch": branch, "branches": branches, "copied_from": last["id"] if last else None}


def update_branch(root, name, branch_id, changes):
    path = project_dir(root, name)
    meta = read_meta(path)
    branch = find_branch(meta["branches"], branch_id)
    if branch_id in branches_with_takes(path, meta):
        frozen = []
        if "refs" in changes and isinstance(changes["refs"], dict):
            used = refs_used(path, branch_id, meta)
            for ref, files in (branch.get("refs") or {}).items():
                new = changes["refs"].get(ref) or {}
                if ref in used and any((files or {}).get(k) and (new.get(k) or None) != files.get(k) for k in ("image", "voice")):
                    frozen.append(ref)
        if any(k in changes and int(changes[k]) != int(branch.get(k) or 0) for k in ("width", "height")):
            frozen.append(_t("projects.frozen_size"))
        if frozen:
            raise StudioError(_t("projects.branch_frozen", what=", ".join(frozen)))
    if "name" in changes:
        label = str(changes["name"] or "").strip()
        if not label:
            raise StudioError(_t("projects.empty_branch_name"))
        branch["name"] = label[:60]
    if "refs" in changes:
        if not isinstance(changes["refs"], dict):
            raise StudioError(_t("projects.invalid_references"))
        branch["refs"] = {str(k): {"image": (v or {}).get("image") or None, "voice": (v or {}).get("voice") or None}
                          for k, v in changes["refs"].items()}
    if "ref_image_size" in changes:
        branch["ref_image_size"] = check_ref_size(changes["ref_image_size"])
    if "upscale" in changes:                 # a generation setting: no take becomes invalid
        value = changes["upscale"]
        if not isinstance(value, dict):
            raise StudioError(_t("projects.upscale_invalid_settings"))
        merged = upscale_of(branch)
        merged.update({k: v for k, v in value.items() if k in UPSCALE_KEYS})
        branch["upscale"] = merged
    if "loras" in changes:                  # a generation setting too: no take becomes invalid
        branch["loras"] = clean_loras(changes["loras"])
    if "width" in changes or "height" in changes:
        width, height = int(changes.get("width", branch.get("width"))), int(changes.get("height", branch.get("height")))
        problem = plan_core.check_size(width, height)
        if problem:
            raise StudioError(problem)
        branch["width"], branch["height"] = width, height
    _write_json(path / "project.json", meta)
    return {"branch": branch, "branches": meta["branches"]}


def save_plan(root, name, plan, branch_id, leaf_id=None):
    """Saves the master plan of a branch (no leaf) or what can change in the plan of a twig (its suite)."""
    from . import plans
    path = project_dir(root, name)
    meta = read_meta(path)
    find_branch(meta["branches"], branch_id)
    if not isinstance(plan, dict) or not isinstance(plan.get("clips"), list):
        raise StudioError(_t("projects.the_plan_must_be_a_json"))
    plan = json.loads(json.dumps(plan))
    plan["project"] = path.name
    plan["version"] = plan_core.PLAN_VERSION
    plan.pop("ref_image_size", None)
    plan = fit_essence(path, plan, branch_id, meta)
    problems = plans.frozen_problems(path, branch_id, plan, branch_id in branches_with_takes(path))
    if problems:
        raise StudioError(_t("projects.plan_frozen", what=", ".join(problems)))
    plans.save_twig_plan(path, branch_id, leaf_id, plan)
    errors, warnings = plan_core.validate(json.loads(json.dumps(plan)))
    return {"plan": plan, "validation": {"errors": errors, "warnings": warnings}}


def save_settings(root, name, settings):
    """« Réglages du projet »: models, sampling, LoRA stack, previews (the essence has its own route: set_essence)."""
    path = project_dir(root, name)
    if not isinstance(settings, dict):
        raise StudioError(_t("projects.invalid_settings"))
    settings = strip_branch_keys(migrate_settings(settings))
    meta = read_meta(path)
    meta["settings"] = settings
    _write_json(path / "project.json", meta)
    return {"settings": settings}


def use_twig_plan(root, name, branch_id, leaf, target="master", label=None, pending=None):
    """« Utiliser ce plan… »: the plan of a twig (its generated clips as they were made, then what follows) becomes
    the master plan of its branch (target "master": the master plan it had goes to the trash) or of a new branch with
    the settings of that branch (target "new"; the current branch does not change)."""
    from . import plans, trash
    path = project_dir(root, name)
    meta = read_meta(path)
    branch = find_branch(meta["branches"], branch_id)
    if not leaf:
        raise StudioError(_t("projects.duplicate_needs_a_selection"))
    twig = plans.plan_of(path, branch_id, leaf, pending=pending, project_name=path.name)
    plan = strip_seeds(twig["plan"])
    if target == "new":
        out = create_branch(root, name, master=plan, source=branch_id, label=label)
    else:
        master = plans.master(path, branch_id) or {}
        new = plans.head(master) if master else plans.head(plan)
        new["refs"], new["clips"] = plan.get("refs") or {}, plan["clips"]
        trash.replace_master(path, branch_id, new, _t("trash.label_master", name=branch["name"]))
        out = {"branch": branch}
    out["project"] = read_project(root, name)
    return out


def strip_seeds(plan):
    """A seed belongs to a take, never to a plan."""
    plan = json.loads(json.dumps(plan))
    plan.pop("seed", None)
    for clip in plan.get("clips") or []:
        if isinstance(clip, dict):
            clip.pop("seed", None)
    return plan


def read_plan_file(data: bytes, filename: str):
    try:
        plan = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise StudioError(_t("projects.is_not_a_readable_json_file", filename=filename, exc=exc)) from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("clips"), list):
        raise StudioError(_t("projects.does_not_look_like_an_h3", filename=filename))
    return strip_seeds(plan)


def new_branch(root, name, how="empty", source=None, leaf=None, upto=None, data: bytes = None, filename="plan.json",
               label=None):
    """« + nouvelle branche »: how = "empty" (settings and master plan of the last branch), "file" (data: a plan
    file as master plan), "copy" (settings and master plan of `source`, no clip), "clips" (the clips 1..upto of
    the twig of `source` ending with `leaf` are taken over; master plan: the plan of that twig)."""
    from . import plans
    path = project_dir(root, name)
    if how == "file":
        return create_branch(root, name, master=fit_essence(path, read_plan_file(data or b"", filename)), label=label)
    if how == "copy":
        return create_branch(root, name, source=source, label=label)
    if how == "clips":
        meta = read_meta(path)
        find_branch(meta["branches"], source)
        if not leaf:
            raise StudioError(_t("projects.duplicate_needs_a_selection"))
        twig = plans.plan_of(path, source, leaf, project_name=path.name)
        upto = int(upto or len(twig["chain"]))
        if not 1 <= upto <= len(twig["chain"]):
            raise StudioError(_t("projects.duplicate_upto_invalid", n=len(twig["chain"])))
        master = twig["plan"]
        master["clips"] = [dict(c) for c in master["clips"]]
        return create_branch(root, name, master=master, source=source, take_over=twig["chain"][:upto], label=label)
    return create_branch(root, name, label=label)


def import_plan(root, name, data: bytes, filename: str = "plan.json", branch_id=None):
    """A plan file becomes the master plan of a branch without takes (a branch with takes refuses it: a new branch is
    made from the file instead, see new_branch)."""
    path = project_dir(root, name)
    plan = read_plan_file(data, filename)
    meta = read_meta(path)
    if not branch_id:          # the selected branch, else the first one
        branch_id = takes.read_selection(path).get("branch") or (meta["branches"][0]["id"] if meta["branches"] else None)
    branch = next((b for b in meta["branches"] if b["id"] == branch_id), None)
    if not branch:
        raise StudioError(_t("server.plan_branch_missing"))
    if branch_id in branches_with_takes(path):
        raise StudioError(_t("projects.import_branch_has_takes", branch=branch["name"]))
    result = save_plan(root, name, plan, branch_id)
    takes.write_selection(path, {"branch": branch_id})
    result.update(imported_from=filename, branch=branch_id)
    return result


# --------------------------------------------------------------------------- deleting a branch
def _branch_exports(path: Path, branch_id):
    out = []
    for meta in (path / "exports").glob("*.json"):
        if meta.name.endswith(".infos.json"):
            continue
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("branch") == branch_id:
                out.append(meta)
        except (OSError, ValueError):
            continue
    return out


def delete_branch(root, name, branch_id, confirm=False):
    """Deletes a branch into the trash (trash.delete_branch); the project as it is now comes with the answer."""
    from . import trash
    out = trash.delete_branch(root, name, branch_id, confirm)
    if out.get("deleted"):
        out["project"] = read_project(root, name)
    return out


# --------------------------------------------------------------------------- resources
JPEG_ALIASES = (".jfif", ".jfi", ".jpe", ".pjpeg", ".pjp")


def image_format(data: bytes) -> str:
    """Real format read from the first bytes ('' if not a supported image)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    return ""


def normalize_image(filename: str, data: bytes) -> str:
    """Check the content and save JPEG variants (.jfif, .jpe…) as .jpg (bytes unchanged)."""
    stem, ext = os.path.splitext(filename)
    ext = ext.lower()
    real = image_format(data)
    if not real:
        raise StudioError(_t("projects.is_not_a_png_jpeg_webp", filename=filename))
    expected = {"jpeg": (".jpg", ".jpeg") + JPEG_ALIASES, "png": (".png",), "webp": (".webp",), "bmp": (".bmp",)}[real]
    if ext not in expected:
        raise StudioError(_t("projects.is_actually_a_picture_rename_it", filename=filename, v1=real.upper(), v2=expected[0]))
    if ext in JPEG_ALIASES:
        return stem + ".jpg"
    return filename


def add_resource_stream(root, name, kind: str, filename: str, stream, length: int, chunk: int = 1024 * 1024):
    """Copy an image, a voice, a song or a video into the project. Same content = same file (no duplicate).
    The file is written to the disk as it arrives, never held whole in memory; a transfer cut short leaves
    nothing behind."""
    path = project_dir(root, name)
    if kind not in RESOURCE_KINDS:
        raise StudioError(_t("projects.unknown_resource_type"))
    filename = safe_filename(filename)
    folder = path / "refs" / kind
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / f".upload_{uuid.uuid4().hex}.part"
    sha = hashlib.sha256()
    head = b""
    try:
        with open(part, "wb") as handle:
            remaining = int(length)
            while remaining > 0:
                data = stream.read(min(chunk, remaining))
                if not data:
                    raise StudioError(_t("projects.upload_interrupted"))
                if len(head) < 16:
                    head += data[:16]
                handle.write(data)
                sha.update(data)
                remaining -= len(data)
        if kind == "images":
            filename = normalize_image(filename, head)
        if not filename.lower().endswith(RESOURCE_KINDS[kind]):
            raise StudioError(_t("projects.format_not_accepted_for", filename=filename, kind=kind, v2=', '.join(RESOURCE_KINDS[kind])))
        digest = sha.hexdigest()
        for other in folder.iterdir():           # the same content already imported: keep that file
            if other.is_file() and other.suffix != ".part" and other.stat().st_size == length and takes.file_sha(other) == digest:
                return {"path": other.relative_to(path).as_posix(), "reused": True}
        target = folder / filename
        stem, ext = os.path.splitext(filename)
        number = 2
        while target.exists():
            target = folder / f"{stem}_{number}{ext}"
            number += 1
        os.replace(part, target)
        return {"path": target.relative_to(path).as_posix(), "reused": False}
    finally:
        if part.exists():
            part.unlink()


def list_resources(root, name):
    path = project_dir(root, name)
    out = {}
    for kind, extensions in RESOURCE_KINDS.items():
        folder = path / "refs" / kind
        items = []
        if folder.is_dir():
            for file in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                if file.is_file() and file.name.lower().endswith(extensions):
                    items.append({"path": file.relative_to(path).as_posix(), "name": file.name, "size": file.stat().st_size,
                                  "sha": takes.file_sha(file)})
        out[kind] = items
    return out
