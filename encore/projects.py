"""Encore - projects on disk (standard library only).

A project is a folder of the projects root:

    <root>/<name>/
        project.json     studio settings: models, sampling, picture size, which file is which reference
        plan.json        the H3 Clip Plan
        refs/images/     imported reference images
        refs/voices/     imported voice samples
        refs/songs/      imported songs
        refs/videos/     imported videos (a plan can start from a segment of one)
        takes/           generated takes (step 2)
        checkpoints/     saved states (step 3)
        store/           files kept once, by content hash (step 3)
        exports/         final videos (step 4)
"""
from __future__ import annotations

from .i18n import t as _t
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from . import plan_core, takes

STUDIO_VERSION = "0.40"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
RESOURCE_KINDS = {
    "images": (".png", ".jpg", ".jpeg", ".webp", ".bmp"),
    "voices": (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"),
    "songs": (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"),
    "videos": (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"),
}
SUBDIRS = ("refs/images", "refs/voices", "refs/songs", "refs/videos", "takes", "checkpoints", "store", "exports")
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
        "checkpoint_limit": 0,          # 0 = no limit (step 3)
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
# Project LoRA stack (settings) is always used. On top of it: the branch's LoRA and the clip's LoRA add up (same file at
# two levels: the clip's strength wins), unless the clip says "sans les LoRA de branche". A generation can also give its
# exact list, which replaces branch + clip. Upscale: the branch's settings, unless the generation gives its own (from the
# « tuned take » dialog: the branch's settings changed for this take, « enabled » included). Since 0.28 a clip (column)
# no longer has upscale settings: what earlier versions saved there is ignored.


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


def clip_default(meta_or_project, clip_name):
    value = (meta_or_project.get("clip_defaults") or {}).get(clip_name) or {}
    return {"loras": clean_loras(value.get("loras")), "no_branch_loras": bool(value.get("no_branch_loras"))}


def default_extra_loras(branch, clip_def):
    return merge_loras([] if clip_def["no_branch_loras"] else clean_loras(branch.get("loras")), clip_def["loras"])


def set_clip_default(root, name, clip_name, value):
    path = project_dir(root, name)
    meta = read_meta(path)
    clip_name = str(clip_name or "").strip()
    if not clip_name:
        raise StudioError(_t("projects.clip_without_a_name"))
    if not isinstance(value, dict):
        raise StudioError(_t("projects.invalid_clip_settings"))
    clean = {"loras": clean_loras(value.get("loras")), "no_branch_loras": bool(value.get("no_branch_loras"))}
    defaults = meta.setdefault("clip_defaults", {})
    if clean["loras"] or clean["no_branch_loras"]:
        defaults[clip_name] = clean
    else:
        defaults.pop(clip_name, None)
    _write_json(path / "project.json", meta)
    return {"clip_defaults": defaults}


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
                                        "legacy_ref_image_size": "match", "branches": []})
    _write_json(path / "plan.json", skeleton_plan(name, mode))
    return read_project(root, name)


def list_projects(root):
    root = Path(root)
    out = []
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not (child / "project.json").is_file():
            continue
        item = {"name": child.name, "mode": None, "clips": 0, "updated": 0}
        try:
            plan = _read_json(child / "plan.json")
            item["mode"] = plan_core.plan_mode(plan)
            item["clips"] = len(plan.get("clips") or [])
            item["updated"] = max((child / "plan.json").stat().st_mtime, (child / "project.json").stat().st_mtime)
        except (OSError, ValueError):
            item["error"] = "plan illisible"
        out.append(item)
    return out


def read_meta(path: Path):
    """project.json, upgraded if needed: references and song move from the settings to the branches."""
    meta = _read_json(path / "project.json")
    if "branches" not in meta:
        settings = meta.get("settings") or {}
        refs, song = settings.get("refs") or {}, settings.get("song") or ""
        has_takes = any((path / "takes").glob("clip_*/*.json"))
        meta["branches"] = ([{"id": "b1", "name": _t("projects.branch_1"), "color": BRANCH_COLORS[0], "refs": refs, "song": song,
                              "width": int(settings.get("width", 960)), "height": int(settings.get("height", 544)),
                              "created": time.time()}] if (refs or song or has_takes) else [])
        meta["settings"] = strip_branch_keys(settings)
        _write_json(path / "project.json", meta)
    for branch in meta["branches"]:          # branches of version 0.3: the picture size was global
        if "width" not in branch:
            settings = meta.get("settings") or {}
            branch["width"] = int(settings.get("width", 960))
            branch["height"] = int(settings.get("height", 544))
            meta["_dirty"] = True
    # 0.7: the size of the reference pictures moves from the plan to the branches; takes made before
    # (which did not record it) were made with the value of the plan at that time
    if "legacy_ref_image_size" not in meta:
        legacy = "match"
        try:
            plan = json.loads((path / "plan.json").read_text(encoding="utf-8-sig"))
            if plan.get("ref_image_size") in REF_SIZES:
                legacy = plan["ref_image_size"]
            if "ref_image_size" in plan:
                plan.pop("ref_image_size")
                _write_json(path / "plan.json", plan)
        except (OSError, ValueError):
            pass
        meta["legacy_ref_image_size"] = legacy
        meta["_dirty"] = True
    for branch in meta["branches"]:          # branches made before 0.7 (restored from a checkpoint, too)
        if branch.get("ref_image_size") not in REF_SIZES:
            branch["ref_image_size"] = meta["legacy_ref_image_size"]
            meta["_dirty"] = True
    if meta.pop("_dirty", False):
        meta["settings"] = strip_branch_keys(meta.get("settings") or {})
        _write_json(path / "project.json", meta)
    return meta


def read_project(root, name):
    path = project_dir(root, name)
    meta = read_meta(path)
    plan = _read_json(path / "plan.json")
    saved = meta.get("settings") or {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update(strip_branch_keys(migrate_settings(saved)) if saved else {})
    errors, warnings = plan_core.validate(plan)
    return {"name": path.name, "path": str(path), "plan": plan, "settings": settings, "branches": meta["branches"],
            "legacy_ref_image_size": meta.get("legacy_ref_image_size") or "match",
            "clip_defaults": meta.get("clip_defaults") or {},
            "start_video_file": meta.get("start_video_file") or None,
            "resources": list_resources(root, name), "validation": {"errors": errors, "warnings": warnings}}


# --------------------------------------------------------------------------- start video
# The video a plan starts from (start_video) is one file for the whole project, chosen in the plan settings;
# every branch uses it, as if each one had it as the file of the plan's start_video reference.
def set_start_video_file(root, name, rel):
    path = project_dir(root, name)
    meta = read_meta(path)
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
    """A number never used before in the project: not by a branch, a deleted one or one in a checkpoint."""
    used = [int(meta.get("branch_seq") or 0)] + [_branch_number(b["id"]) for b in meta["branches"]]
    for file in (path / "checkpoints").glob("cp_*.json"):
        try:
            cp = json.loads(file.read_text(encoding="utf-8"))
            used += [_branch_number(b.get("id")) for b in ((cp.get("state") or {}).get("meta") or {}).get("branches") or []]
        except (OSError, ValueError):
            continue
    return max(used + [0]) + 1


def create_branch(root, name):
    """A new, empty branch; its set is a copy of the last branch created."""
    path = project_dir(root, name)
    meta = read_meta(path)
    branches = meta["branches"]
    number = next_branch_number(path, meta)
    meta["branch_seq"] = number
    last = max(branches, key=lambda b: b.get("created", 0)) if branches else None
    branch = {"id": f"b{number}", "name": _t("projects.branch", number=number), "color": BRANCH_COLORS[(number - 1) % len(BRANCH_COLORS)],
              "refs": json.loads(json.dumps(last["refs"])) if last else {}, "song": last["song"] if last else "",
              "width": int(last.get("width", DEFAULT_BRANCH_SIZE[0])) if last else int((meta.get("first_branch_size") or DEFAULT_BRANCH_SIZE)[0]),
              "height": int(last.get("height", DEFAULT_BRANCH_SIZE[1])) if last else int((meta.get("first_branch_size") or DEFAULT_BRANCH_SIZE)[1]),
              "ref_image_size": (last.get("ref_image_size") if last else meta.get("first_branch_ref_size")) or DEFAULT_REF_SIZE,
              "upscale": json.loads(json.dumps(last.get("upscale") or DEFAULT_UPSCALE)) if last else json.loads(json.dumps(DEFAULT_UPSCALE)),
              "loras": clean_loras(last.get("loras")) if last else [],
              "created": time.time()}
    branches.append(branch)
    _write_json(path / "project.json", meta)
    return {"branch": branch, "branches": branches, "copied_from": last["id"] if last else None}


def update_branch(root, name, branch_id, changes):
    path = project_dir(root, name)
    meta = read_meta(path)
    branch = find_branch(meta["branches"], branch_id)
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
    if "song" in changes:
        branch["song"] = str(changes["song"] or "")
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


def read_plan(root, name):
    return _read_json(project_dir(root, name) / "plan.json")


def save_plan(root, name, plan):
    path = project_dir(root, name)
    if not isinstance(plan, dict):
        raise StudioError(_t("projects.the_plan_must_be_a_json"))
    notes = []
    if plan.get("project") != path.name:
        notes.append(_t("projects.the_project_name_in_the_plan", name=path.name))
        plan["project"] = path.name
    plan["version"] = plan_core.PLAN_VERSION
    if "ref_image_size" in plan:
        plan.pop("ref_image_size")
        notes.append(_t("projects.ref_image_size_is_removed_from"))
    _write_json(path / "plan.json", plan)
    errors, warnings = plan_core.validate(plan)
    return {"plan": plan, "notes": notes, "validation": {"errors": errors, "warnings": warnings}}


def save_settings(root, name, settings):
    path = project_dir(root, name)
    if not isinstance(settings, dict):
        raise StudioError(_t("projects.invalid_settings"))
    settings = strip_branch_keys(migrate_settings(settings))
    meta = read_meta(path)
    meta["settings"] = settings
    _write_json(path / "project.json", meta)
    return {"settings": settings}


def import_plan(root, name, data: bytes, filename: str = "plan.json"):
    """Copy a plan file into the project (the previous plan is kept as plan.previous.json)."""
    path = project_dir(root, name)
    try:
        plan = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise StudioError(_t("projects.is_not_a_readable_json_file", filename=filename, exc=exc)) from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("clips"), list):
        raise StudioError(_t("projects.does_not_look_like_an_h3", filename=filename))
    if (path / "plan.json").is_file():
        shutil.copy2(path / "plan.json", path / "plan.previous.json")
    result = save_plan(root, name, plan)
    result["imported_from"] = filename
    return result


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
