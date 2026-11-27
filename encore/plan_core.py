"""H3 Clip Plan - plan parsing, validation and timing.

Pure Python on purpose (no torch, no ComfyUI import) so that the same code runs
inside the nodes, in the command-line checker and in the tests.
"""
from __future__ import annotations

import hashlib
import json
import re

FPS = 24
PLAN_VERSION = 7
ACCEPTED_VERSIONS = (7,)   # no older format: a plan without subjects must be rewritten
MODES = ("music_video", "free")
MAX_CLIPS = 64          # limit of the final assembler node
MAX_REFS = 9            # MiniMax H3 accepts at most 9 reference images
MAX_VOICES = 3          # ... at most 3 reference audio clips
MAX_REF_FILES = 12      # ... and at most 12 reference files in all
VOICE_MIN_SECONDS = 2.0
VOICE_TOTAL_SECONDS = 15.0
AUDIO_HZ = 40           # H3 audio latent steps per second
DEFAULT_FEATHER = 8     # audio feather of a free-mode continuation, in audio steps (0.2 s)
MAX_WORDS_PER_SECOND = 3.0
SOFT_MAX_FRAMES = 243   # about 10 s; longer clips work but are slow
HARD_MAX_FRAMES = 1195  # sanity bound only
DEFAULT_CONTEXT = 39
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")       # file names (they name ComfyUI reference nodes)
SUBJECT_NAME_RE = re.compile(r"^[^\W_](?:[\w-]*\w)?$")     # subject names: any letters, digits, '_' and '-'
MENTION_RE = re.compile(r"(?<![\w@])@([^\W_](?:[\w-]*\w)?)")
_PROMPT_SECTIONS = (
    "subject_definitions:", "summary:", "retention_analysis:",
    "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
)
_PLAN_KEYS = {
    "version", "project", "mode", "files", "subjects", "width", "height", "context_frames",
    "crossfade_frames", "audio_feather_ticks", "seed", "ref_image_size", "song", "clips", "notes", "start_video",
    "edit_video",
}
FILE_KINDS = ("image", "voice", "video")
SUBJECT_KINDS = ("person", "place", "object", "outfit", "style", "action", "pose")
KIND_WORDS = {"person": "a character", "place": "a place", "object": "an object", "outfit": "an outfit",
              "style": "a visual style", "action": "an action", "pose": "a pose"}
DEFAULT_ROLES = {"person": "appearance", "place": "scene", "object": "appearance", "outfit": "outfit",
                 "style": "visual style", "action": "motion", "pose": "pose"}
KEEP_MARKERS = {"identical": "fully_preserved", "partial": "partially_preserved",
                "attribute": "attribute_transfer", "loose": "weak_reference"}
VOICE_MARKERS = {"exact": "fully_copy", "partial": "partially_copy", "timbre": "reference", "loose": "weak_reference"}
DEFAULT_KEEP, DEFAULT_VOICE_KEEP = "identical", "timbre"
KEEP_REASONS = {"identical": "keep it exactly as defined while pose, expression and movement follow the scene",
                "partial": "keep its main traits; details may change",
                "attribute": "take only what its definition names from the reference",
                "loose": "a loose inspiration only"}
_FILE_KEYS = {"kind", "file", "note"}
_SUBJECT_KEYS = {"kind", "description", "pictures", "voice", "note"}
_USE_KEYS = {"name", "keep", "voice_keep", "note"}
_ANCHOR_KEYS = {"first", "last", "keyframes"}
_TEXT_KEYS = ("summary", "description", "soundscape", "music")
_START_VIDEO_KEYS = {"ref", "start", "end", "in_assembly", "song"}
START_SONG_CHOICES = ("with_video", "after_video")   # music_video: the song starts with the video, or after it
_EDIT_VIDEO_KEYS = {"ref", "start", "end", "sound", "instruction"}
EDIT_SOUND_CHOICES = ("original", "h3")   # the final video keeps the sound of the segment, or the one H3 made
EDIT_MIN_FRAMES = 48     # a reference video lasts 2 to 15 s
EDIT_MAX_FRAMES = 360
_VIDEO_TAG_RE = re.compile(r"<Video (\d+)>")
_CLIP_KEYS = {"name", "frames", "continue", "anchors", "subjects", "summary", "description", "soundscape", "music",
              "prompt_override", "defs", "seed", "lyrics", "dialogue", "notes"}
_DIALOGUE_KEYS = {"speaker", "text", "language"}
PLACEHOLDER_RE = re.compile(r"\{(picture|voice):([A-Za-z0-9][A-Za-z0-9_-]*)\}")   # in the composed prompt only
EDIT_AUDIO_MARK = "{edit_audio}"      # composed line kept only when the edited video has a sound (its <Audio 1>)
AUDIO_REUSE_MARK = "{+audio_reuse}"   # becomes " + audio reuse" in the task prefix in that case
SHOT_RE = re.compile(r"\[Shot (\d+)\]")
CONTINUE_SENTENCE = ("The incoming performer motion, camera trajectory, body momentum, facial state, lighting, environment "
                     "and object state continue uninterrupted from the protected video context.")
FREE_CONTINUE_SUFFIX = " The protected sound continues too; nothing in that context is repeated."
HIDDEN_LEADIN_FREE = "Hidden lead-in for the first 1.6 seconds: the scene is already fully established, nobody speaks."
HIDDEN_LEADIN_MUSIC = ("The first second and a half of this clip is a lead-in that overlaps the end of the previous song "
                       "phrase; the scene is already fully established from the first frame.")


class PlanError(ValueError):
    """Raised with every problem found, one per line."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("H3 Clip Plan: invalid plan\n- " + "\n- ".join(self.errors))


# --------------------------------------------------------------------------- frame grid
def is_h3_run(frames: int) -> bool:
    """True for a legal H3 clip length: 5, 22, 39, 56, ... (17k + 5)."""
    return isinstance(frames, int) and not isinstance(frames, bool) and frames >= 5 and (frames - 5) % 17 == 0


def largest_h3_run(frames: int) -> int:
    frames = int(frames)
    return 0 if frames < 5 else 5 + ((frames - 5) // 17) * 17


def nearest_h3_runs(frames: int):
    low = max(5, largest_h3_run(frames))
    return low, low + 17


def pixel_frames(latent_steps: int) -> int:
    """Pixel frames covered by an H3 video latent of ``latent_steps`` steps."""
    pattern = (1, 4, 4, 4, 4)
    return sum(pattern[k % 5] for k in range(int(latent_steps)))


def snap_context(requested: int, previous_frames: int, frames: int) -> int:
    """Overlap really used between two clips (same rule as the assembler)."""
    return largest_h3_run(min(int(requested), int(previous_frames), int(frames) - 1))


def is_av_boundary(frames: int) -> bool:
    """True when a frame count also falls on the 40 Hz audio grid (multiple of 3 frames)."""
    return (int(frames) * AUDIO_HZ) % FPS == 0


def av_context_values(limit: int = 243):
    """Context lengths usable in free mode: 39, 90, 141, 192, 243."""
    return [n for n in range(5, limit + 1, 17) if is_av_boundary(n)]


def cut_grid_seconds(count: int = 200):
    """Times at which a clip can end when clip 1 starts at 0: (5 + 17n) / 24."""
    return [(5 + 17 * n) / FPS for n in range(count)]


# --------------------------------------------------------------------------- loading
def parse_plan(text):
    """Parse JSON text (or accept an already parsed dict) and validate it."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8-sig")
    if isinstance(text, str):
        try:
            plan = json.loads(text.lstrip("﻿"))
        except json.JSONDecodeError as exc:
            raise PlanError([f"not valid JSON: {exc}"]) from exc
    else:
        plan = text
    errors, _warnings = validate(plan)
    if errors:
        raise PlanError(errors)
    return normalize(plan)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def plan_mode(plan) -> str:
    """'music_video' (the song is injected) or 'free' (H3 generates the sound)."""
    if isinstance(plan, dict) and plan.get("mode") in MODES:
        return plan["mode"]
    return "music_video"


def validate(plan, song_duration: float | None = None):
    """Return (errors, warnings). An empty error list means the plan is usable."""
    errors, warnings = [], []
    if not isinstance(plan, dict):
        return ["the plan must be a JSON object"], warnings

    for key in plan:
        if key not in _PLAN_KEYS and not key.startswith("_"):
            warnings.append(f"unknown top-level key '{key}' is ignored")
    version = plan.get("version")
    if version not in ACCEPTED_VERSIONS:
        errors.append(f"'version' must be {PLAN_VERSION}")
    if "mode" in plan and plan["mode"] not in MODES:
        errors.append(f"'mode' must be 'music_video' or 'free' (got {plan['mode']!r})")
    if version in (1, 2) and plan.get("mode") == "free":
        errors.append("'mode': 'free' needs 'version': 3")
    mode = plan_mode(plan)
    free = mode == "free"
    project = plan.get("project")
    if not isinstance(project, str) or not _NAME_RE.match(project):
        errors.append("'project' must be a short name made of letters, digits, '_' or '-'")
    for key in ("width", "height"):
        value = plan.get(key)
        if value is not None and (not _is_int(value) or value < 64 or value % 32 != 0):
            errors.append(f"'{key}' must be an integer multiple of 32 (got {value!r})")
    if (plan.get("width") is None) != (plan.get("height") is None):
        errors.append("'width' and 'height' must be given together, or both left out")
    context = plan.get("context_frames", DEFAULT_CONTEXT)
    if not is_h3_run(context):
        errors.append(f"'context_frames' must be 5, 22, 39, 56, ... (got {context!r}); use 39")
        context = DEFAULT_CONTEXT
    elif free and not is_av_boundary(context):
        errors.append(
            f"'context_frames' must be one of {', '.join(map(str, av_context_values()))} in free mode "
            f"(got {context}): the copied picture and sound must end on the same instant; use 39"
        )
        context = DEFAULT_CONTEXT
    crossfade = plan.get("crossfade_frames", 0)
    if not _is_int(crossfade) or not 0 <= crossfade <= context:
        errors.append(f"'crossfade_frames' must be an integer from 0 to context_frames (got {crossfade!r})")
    if "audio_feather_ticks" in plan:
        feather = plan["audio_feather_ticks"]
        if not free:
            warnings.append("'audio_feather_ticks' is only used in free mode")
        if not _is_int(feather) or not 0 <= feather <= 64:
            errors.append(f"'audio_feather_ticks' must be an integer from 0 to 64 (got {feather!r})")
    if "seed" in plan and (not _is_int(plan["seed"]) or plan["seed"] < 0):
        errors.append("'seed' must be a non-negative integer")
    if plan.get("ref_image_size", "match") not in ("match", "max"):
        errors.append("'ref_image_size' must be 'match' or 'max'")

    files_map = _check_files(plan.get("files", {}), "files", errors)
    subjects_map = _check_subjects(plan.get("subjects", {}), "subjects", files_map, errors)

    start_video = plan.get("start_video")
    start_frames = None
    if start_video is not None:
        start_frames = _check_start_video(start_video, files_map, free, context, errors, warnings)
    edit_video = plan.get("edit_video")
    edit_frames = None
    if edit_video is not None:
        if start_video is not None:
            errors.append("'start_video' and 'edit_video' cannot be used together: a plan continues a video or edits one")
        if not free:
            errors.append("'edit_video' needs free mode: the edited clips keep the sound of the video (or H3's), not a song")
        edit_frames = _check_edit_video(edit_video, files_map, subjects_map, errors, warnings)

    song = plan.get("song", {})
    if not isinstance(song, dict):
        errors.append("'song' must be an object")
        song = {}
    if free:
        if song:
            errors.append("free mode has no song: remove 'song' (H3 generates the sound of every clip)")
        song_duration = None
    elif song_duration is None and isinstance(song.get("duration_seconds"), (int, float)):
        song_duration = float(song["duration_seconds"])

    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        errors.append("'clips' must be a non-empty array")
        return errors, warnings
    if len(clips) > MAX_CLIPS:
        errors.append(f"at most {MAX_CLIPS} clips are supported (got {len(clips)})")

    names = set()
    frames_ok = True
    for index, clip in enumerate(clips, start=1):
        label = f"clip {index}"
        if not isinstance(clip, dict):
            errors.append(f"{label}: must be an object")
            frames_ok = False
            continue
        for key in clip:
            if key not in _CLIP_KEYS and not key.startswith("_"):
                warnings.append(f"{label}: unknown key '{key}' is ignored")
        name = clip.get("name", f"clip_{index:03d}")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            errors.append(f"{label}: 'name' may only contain letters, digits, '_' and '-'")
        elif name in names:
            errors.append(f"{label}: duplicate name '{name}'")
        names.add(name)

        frames = clip.get("frames")
        if not is_h3_run(frames):
            frames_ok = False
            if _is_int(frames) and frames > 0:
                low, high = nearest_h3_runs(frames)
                errors.append(f"{label}: 'frames' must be 17k + 5 (got {frames}; nearest legal values {low} and {high})")
            else:
                errors.append(f"{label}: 'frames' must be an integer of the form 17k + 5 (got {frames!r})")
        else:
            if frames <= context:
                errors.append(f"{label}: 'frames' ({frames}) must be greater than context_frames ({context})")
                frames_ok = False
            if frames > HARD_MAX_FRAMES:
                errors.append(f"{label}: 'frames' ({frames}) is unreasonably long")
            elif frames > SOFT_MAX_FRAMES:
                warnings.append(f"{label}: {frames} frames ({frames / FPS:.1f} s) is longer than {SOFT_MAX_FRAMES} frames; generation will be slow")

        cont = clip.get("continue", False)
        if not isinstance(cont, bool):
            errors.append(f"{label}: 'continue' must be true or false")
        elif cont and index == 1 and start_video is None:
            errors.append("clip 1: 'continue' must be false, there is no previous clip (or set 'start_video')")

        _check_clip_fields(clip, label, files_map, subjects_map, errors, warnings)
        lyrics = clip.get("lyrics", "")
        if lyrics and free:
            warnings.append(f"{label}: 'lyrics' is a music_video field; use 'dialogue' in free mode")
        dialogue = clip.get("dialogue", [])
        if dialogue and not free:
            warnings.append(f"{label}: 'dialogue' is only checked in free mode")
        if not isinstance(dialogue, list):
            errors.append(f"{label}: 'dialogue' must be an array of {{speaker, text, language}} objects")
            dialogue = []
        words = 0
        for number, line in enumerate(dialogue, start=1):
            where = f"{label}: dialogue line {number}"
            if not isinstance(line, dict):
                errors.append(f"{where}: must be an object with 'speaker' and 'text'")
                continue
            for key in line:
                if key not in _DIALOGUE_KEYS and not key.startswith("_"):
                    warnings.append(f"{where}: unknown key '{key}' is ignored")
            speaker, text = line.get("speaker"), line.get("text")
            if not isinstance(speaker, str) or not SUBJECT_NAME_RE.match(speaker):
                errors.append(f"{where}: 'speaker' must be the name of a subject (got {speaker!r})")
            if not isinstance(text, str) or not text.strip():
                errors.append(f"{where}: 'text' must be a non-empty string")
                continue
            words += len(text.split())
            said = " ".join(str(clip.get(k) or "") for k in _TEXT_KEYS) + " " + str(clip.get("prompt_override") or "")
            if _squash(text) not in _squash(said):
                warnings.append(f"{where}: this text is not found in the prompt; H3 only says what the prompt contains")
            if "language" in line and not isinstance(line["language"], str):
                errors.append(f"{where}: 'language' must be a string such as 'French'")
        if words and _is_int(frames) and is_h3_run(frames) and frames > context:
            speaking = (frames - (context if index > 1 else 0)) / FPS
            rate = words / speaking
            if rate > MAX_WORDS_PER_SECOND:
                warnings.append(
                    f"{label}: {words} words in {speaking:.1f} s of new picture ({rate:.1f} words/s); "
                    f"above {MAX_WORDS_PER_SECOND:.0f} words/s speech gets rushed or cut - lengthen the clip or shorten the lines"
                )
        if "seed" in clip and (not _is_int(clip["seed"]) or clip["seed"] < 0):
            errors.append(f"{label}: 'seed' must be a non-negative integer")

    if frames_ok and not errors:            # what depends on the composed prompt of each clip
        for clip in normalize(plan)["clips"]:
            errors += [f"clip {clip['index']}: {e}" for e in clip["compose"]["errors"]]
            warnings += [f"clip {clip['index']}: {w}" for w in clip["compose"]["warnings"]]
    if frames_ok and not errors and edit_frames:
        normal = normalize(plan)
        rows = timeline(normal)
        edited = edit_clip_count(normal)
        if not edited:
            errors.append(f"no clip ends before the end of the edited segment ({edit_frames / FPS:.3f} s): "
                          "clip 1 must end within it")
        for clip, row in zip(normal["clips"], rows):
            label = f"clip {row['index']}"
            if row["index"] <= edited:
                if not EDIT_MIN_FRAMES <= row["frames"] <= EDIT_MAX_FRAMES:
                    errors.append(f"{label}: a clip that edits a video lasts 2 to 15 s ({EDIT_MIN_FRAMES} to {EDIT_MAX_FRAMES} "
                                  f"frames), got {row['frames']}: H3 takes reference videos of that length")
            elif _VIDEO_TAG_RE.search(clip["prompt"]):
                errors.append(f"{label}: it ends after the edited segment, so it continues the video instead of editing it; "
                              "its prompt cannot use <Video 1>")
        if edited and edited < len(rows):
            row = rows[edited]
            if edit_frames - row["visible"] >= 17:
                warnings.append(f"clip {row['index']} ends {(row['end'] - edit_frames) / FPS:.2f} s after the end of the segment: "
                                f"it continues the video instead of editing it (the segment from {row['visible'] / FPS:.2f} s "
                                "is not edited)")
        elif edited and edit_frames - rows[-1]["end"] >= FPS:
            warnings.append(f"the clips cover {rows[-1]['end'] / FPS:.2f} s of the {edit_frames / FPS:.2f} s segment; "
                            "the rest is not edited")
    if frames_ok and not errors:
        normal = normalize(plan)
        rows = timeline(normal)
        offset = song_offset(normal) / FPS
        if song_duration is not None:
            for row in rows:
                if row["end_seconds"] - offset > song_duration + 1.0 / FPS:
                    errors.append(
                        f"clip {row['index']}: ends at {row['end_seconds']:.3f} s, after the end of the song "
                        f"({song_duration:.3f} s); shorten it or remove it"
                    )
            if rows[-1]["end_seconds"] - offset < song_duration - 1.0:
                warnings.append(
                    f"the plan ends at {rows[-1]['end_seconds'] - offset:.2f} s of the song but the song lasts {song_duration:.2f} s; "
                    "the end of the song has no picture"
                )
    return errors, warnings


def _check_files(files, where, errors):
    """Check a 'files' object (name -> {kind, file}); return the valid entries."""
    if not isinstance(files, dict):
        errors.append(f"'{where}' must be an object mapping a file name to {{\"kind\", \"file\"}}")
        return {}
    out = {}
    for name, item in files.items():
        if not _NAME_RE.match(str(name)):
            errors.append(f"{where}: file name '{name}' may only contain letters, digits, '_' and '-'")
            continue
        if not isinstance(item, dict) or item.get("kind") not in FILE_KINDS:
            errors.append(f"{where}: file '{name}' must be an object whose 'kind' is one of {', '.join(FILE_KINDS)}")
            continue
        if "file" in item and not isinstance(item["file"], str):
            errors.append(f"{where}: file '{name}': 'file' must be a path")
        out[name] = item
    return out


def _check_subjects(subjects, where, files_map, errors):
    """Check a 'subjects' object (name -> definition); return the valid entries."""
    if not isinstance(subjects, dict):
        errors.append(f"'{where}' must be an object mapping a subject name to its definition")
        return {}
    out = {}
    for name, item in subjects.items():
        label = f"{where}: subject '{name}'"
        if not SUBJECT_NAME_RE.match(str(name)):
            errors.append(f"{label}: a name may only contain letters, digits, '_' and '-'")
            continue
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        if item.get("kind", "person") not in SUBJECT_KINDS:
            errors.append(f"{label}: 'kind' must be one of {', '.join(SUBJECT_KINDS)}")
        if not isinstance(item.get("description", ""), str):
            errors.append(f"{label}: 'description' must be a text")
        pictures = item.get("pictures", [])
        if not isinstance(pictures, list):
            errors.append(f"{label}: 'pictures' must be an array of {{\"file\", \"role\"}}")
            pictures = []
        for k, pic in enumerate(pictures, start=1):
            file = pic.get("file") if isinstance(pic, dict) else None
            if file not in files_map or files_map[file].get("kind") != "image":
                errors.append(f"{label}: picture {k} must name an image of 'files' (got {file!r})")
            elif not isinstance(pic.get("role", ""), str):
                errors.append(f"{label}: picture {k}: 'role' must be a text")
        voice = item.get("voice")
        if voice is not None and (voice not in files_map or files_map[voice].get("kind") != "voice"):
            errors.append(f"{label}: 'voice' must name a voice of 'files' (got {voice!r})")
        out[name] = item
    return out


def clip_definitions(plan, clip):
    """(files, subjects) a clip sees: the plan's, with the clip's own 'defs' on top (a clip already generated
    keeps what it was made with)."""
    defs = clip.get("defs") if isinstance(clip.get("defs"), dict) else {}
    files = dict(plan.get("files") or {})
    files.update(defs.get("files") or {})
    subjects = dict(plan.get("subjects") or {})
    subjects.update(defs.get("subjects") or {})
    return files, subjects


def _check_clip_fields(clip, label, plan_files, plan_subjects, errors, warnings):
    """The v7 fields of a clip (texts, subjects used, anchors, own definitions). What depends on the
    composition (unknown @, limits, a prompt written by hand) is checked when the plan is composed."""
    defs = clip.get("defs")
    files_map, subjects_map = dict(plan_files), dict(plan_subjects)
    if defs is not None:
        if not isinstance(defs, dict):
            errors.append(f"{label}: 'defs' must be an object with 'files' and 'subjects'")
        else:
            for key in defs:
                if key not in ("files", "subjects", "edit_instruction") and not key.startswith("_"):
                    warnings.append(f"{label}: defs: unknown key '{key}' is ignored")
            if defs.get("edit_instruction") is not None and not isinstance(defs["edit_instruction"], str):
                errors.append(f"{label}: defs.edit_instruction must be a text or null")
            files_map.update(_check_files(defs.get("files", {}), f"{label}: defs.files", errors))
            subjects_map.update(_check_subjects(defs.get("subjects", {}), f"{label}: defs.subjects", files_map, errors))
    for key in _TEXT_KEYS:
        if not isinstance(clip.get(key, ""), str):
            errors.append(f"{label}: '{key}' must be a text")
    override = clip.get("prompt_override")
    if override is not None and not isinstance(override, str):
        errors.append(f"{label}: 'prompt_override' must be a text or null")
    if not override and not str(clip.get("summary") or "").strip() and not str(clip.get("description") or "").strip():
        errors.append(f"{label}: write at least a 'summary' or a 'description'")
    uses = clip.get("subjects", [])
    if not isinstance(uses, list):
        errors.append(f"{label}: 'subjects' must be an array of {{\"name\", \"keep\", ...}}")
        uses = []
    seen = set()
    for use in uses:
        if not isinstance(use, dict) or not isinstance(use.get("name"), str):
            errors.append(f"{label}: every item of 'subjects' must be an object with a 'name'")
            continue
        for key in use:
            if key not in _USE_KEYS and not key.startswith("_"):
                warnings.append(f"{label}: subject '{use['name']}': unknown key '{key}' is ignored")
        if use["name"] in seen:
            errors.append(f"{label}: subject '{use['name']}' is set twice")
        seen.add(use["name"])
        if use["name"] not in subjects_map:
            errors.append(f"{label}: subject '{use['name']}' is not defined in 'subjects'")
        if use.get("keep", DEFAULT_KEEP) not in KEEP_MARKERS:
            errors.append(f"{label}: subject '{use['name']}': 'keep' must be one of {', '.join(KEEP_MARKERS)}")
        if use.get("voice_keep", DEFAULT_VOICE_KEEP) not in VOICE_MARKERS:
            errors.append(f"{label}: subject '{use['name']}': 'voice_keep' must be one of {', '.join(VOICE_MARKERS)}")
        if not isinstance(use.get("note", ""), str):
            errors.append(f"{label}: subject '{use['name']}': 'note' must be a text")
    anchors = clip.get("anchors", {})
    if not isinstance(anchors, dict):
        errors.append(f"{label}: 'anchors' must be an object with 'first', 'last' and 'keyframes'")
        return
    for key in anchors:
        if key not in _ANCHOR_KEYS and not key.startswith("_"):
            warnings.append(f"{label}: anchors: unknown key '{key}' is ignored")
    image = lambda f: f in files_map and files_map[f].get("kind") == "image"  # noqa: E731
    for key in ("first", "last"):
        if anchors.get(key) is not None and not image(anchors[key]):
            errors.append(f"{label}: anchors.{key} must name an image of 'files' (got {anchors[key]!r})")
    keyframes = anchors.get("keyframes", [])
    if not isinstance(keyframes, list):
        errors.append(f"{label}: anchors.keyframes must be an array of {{\"at\", \"file\"}}")
        return
    seconds = clip.get("frames") / FPS if _is_int(clip.get("frames")) else None
    for k, item in enumerate(keyframes, start=1):
        if not isinstance(item, dict) or not image(item.get("file")):
            errors.append(f"{label}: keyframe {k} must name an image of 'files'")
            continue
        at = item.get("at")
        if not isinstance(at, (int, float)) or isinstance(at, bool) or at <= 0 or (seconds is not None and at >= seconds):
            errors.append(f"{label}: keyframe {k}: 'at' must be a number of seconds inside the clip"
                          + (f" (0 to {seconds:.3f})" if seconds else ""))


def _check_start_video(spec, files_map, free, context, errors, warnings):
    """Check 'start_video'; return the number of frames of the segment, or None."""
    if not isinstance(spec, dict):
        errors.append("'start_video' must be an object: {\"ref\": NAME, \"start\": seconds, \"end\": seconds}")
        return None
    for key in spec:
        if key not in _START_VIDEO_KEYS and not key.startswith("_"):
            warnings.append(f"start_video: unknown key '{key}' is ignored")
    ref = spec.get("ref")
    if not isinstance(ref, str) or (files_map.get(ref) or {}).get("kind") != "video":
        errors.append(f"start_video: 'ref' must name a video of 'files' (got {ref!r})")
    start, end = spec.get("start", 0), spec.get("end")
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    if not number(start) or start < 0:
        errors.append("start_video: 'start' must be a number of seconds, 0 or more")
        return None
    if not number(end) or end <= start:
        errors.append("start_video: 'end' must be a number of seconds after 'start'")
        return None
    frames = start_video_frames(spec)
    if frames <= context:
        errors.append(
            f"start_video: the segment lasts {frames} usable frames; it must be longer than context_frames "
            f"({context}), that is at least {(context + 17) / FPS:.2f} s"
        )
        return None
    if not isinstance(spec.get("in_assembly", True), bool):
        errors.append("start_video: 'in_assembly' must be true or false")
    song = spec.get("song", "with_video")
    if song not in START_SONG_CHOICES:
        errors.append(f"start_video: 'song' must be one of {', '.join(START_SONG_CHOICES)} (got {song!r})")
    elif free and "song" in spec:
        warnings.append("start_video: 'song' is only used in music_video mode")
    return frames


def _check_edit_video(spec, files_map, subjects_map, errors, warnings):
    """Check 'edit_video'; return the number of frames of the segment, or None."""
    if not isinstance(spec, dict):
        errors.append("'edit_video' must be an object: {\"ref\": NAME, \"start\": seconds, \"end\": seconds}")
        return None
    for key in spec:
        if key not in _EDIT_VIDEO_KEYS and not key.startswith("_"):
            warnings.append(f"edit_video: unknown key '{key}' is ignored")
    ref = spec.get("ref")
    if not isinstance(ref, str) or (files_map.get(ref) or {}).get("kind") != "video":
        errors.append(f"edit_video: 'ref' must name a video of 'files' (got {ref!r})")
    start, end = spec.get("start", 0), spec.get("end")
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    if not number(start) or start < 0:
        errors.append("edit_video: 'start' must be a number of seconds, 0 or more")
        return None
    if not number(end) or end <= start:
        errors.append("edit_video: 'end' must be a number of seconds after 'start'")
        return None
    instruction = spec.get("instruction")
    if instruction is not None:
        if not isinstance(instruction, str):
            errors.append("edit_video: 'instruction' must be a text")
        else:
            for name in MENTION_RE.findall(instruction):
                if name not in subjects_map:
                    errors.append(f"edit_video: the instruction names @{name}, which is not defined in 'subjects'")
    if spec.get("sound", "original") not in EDIT_SOUND_CHOICES:
        errors.append(f"edit_video: 'sound' must be one of {', '.join(EDIT_SOUND_CHOICES)} (got {spec.get('sound')!r})")
    frames = edit_video_frames(spec)
    if frames < EDIT_MIN_FRAMES:
        errors.append(f"edit_video: the segment lasts {frames / FPS:.2f} s; at least 2 s are needed")
        return None
    return frames


def edit_video_frames(spec) -> int:
    """Frames of the edited segment: from 'start' to 'end' on the 24 fps grid of the file."""
    return int(round(float(spec["end"]) * FPS)) - int(round(float(spec.get("start", 0)) * FPS))


def edit_slice(plan, index: int):
    """(first frame in the file, frames) of the source that clip ``index`` edits, or None."""
    spec = plan.get("edit_video")
    if not spec:
        return None
    row = timeline(plan)[index - 1]
    if row["end"] > spec["frames"]:
        return None              # after the segment: this clip continues the video
    return spec["start_frame"] + row["raw_start"], row["frames"]


def edit_instruction(plan):
    """The common edit instruction of an edited video, or None."""
    spec = plan.get("edit_video")
    if isinstance(spec, dict) and isinstance(spec.get("instruction"), str):
        return spec["instruction"]
    return None


def edit_clip_count(plan) -> int:
    """How many clips edit the video (normalized plan): those ending before the end of the segment. The
    clips after them continue the video instead (no <Video 1>)."""
    spec = plan.get("edit_video")
    if not spec:
        return 0
    return sum(1 for row in timeline(plan) if row["end"] <= spec["frames"])


def start_video_frames(spec) -> int:
    """Frames of the start video segment that are used: the longest 17k + 5 run that ends at 'end'."""
    end_frame = int(round(float(spec["end"]) * FPS))
    start_frame = int(round(float(spec.get("start", 0)) * FPS))
    return largest_h3_run(end_frame - start_frame)


def _squash(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def normalize(plan):
    """Return a copy with every default filled in. Call only on a valid plan."""
    out = {
        "version": PLAN_VERSION,
        "project": plan["project"],
        "mode": plan_mode(plan),
        "files": dict(plan.get("files") or {}),
        "subjects": dict(plan.get("subjects") or {}),
        "width": int(plan["width"]) if plan.get("width") is not None else None,
        "height": int(plan["height"]) if plan.get("height") is not None else None,
        "context_frames": int(plan.get("context_frames", DEFAULT_CONTEXT)),
        "crossfade_frames": int(plan.get("crossfade_frames", 0)),
        "audio_feather_ticks": int(plan.get("audio_feather_ticks", DEFAULT_FEATHER)),
        "ref_image_size": plan.get("ref_image_size", "match"),
        "song": dict(plan.get("song", {})),
        "start_video": None,
        "edit_video": None,
        "clips": [],
    }
    edit = plan.get("edit_video")
    if isinstance(edit, dict):
        first = int(round(float(edit.get("start", 0)) * FPS))
        out["edit_video"] = {
            "ref": edit["ref"],
            "start_frame": first,
            "end_frame": first + edit_video_frames(edit),
            "frames": edit_video_frames(edit),
            "sound": edit.get("sound", "original"),
            "instruction": edit.get("instruction") if isinstance(edit.get("instruction"), str) else None,
        }
    spec = plan.get("start_video")
    if isinstance(spec, dict):
        frames = start_video_frames(spec)
        end_frame = int(round(float(spec["end"]) * FPS))
        out["start_video"] = {
            "ref": spec["ref"],
            "frames": frames,
            "start_frame": end_frame - frames,   # 'start' moved forward onto the frame grid
            "end_frame": end_frame,
            "in_assembly": bool(spec.get("in_assembly", True)),
            "song": spec.get("song", "with_video"),
        }
    base_seed = plan.get("seed")
    for index, clip in enumerate(plan["clips"], start=1):
        seed = clip.get("seed")
        if seed is None:
            seed = (int(base_seed) + index) if base_seed is not None else stable_seed(plan["project"], index)
        out["clips"].append({
            "index": index,
            "name": clip.get("name", f"clip_{index:03d}"),
            "frames": int(clip["frames"]),
            "continue": bool(clip.get("continue", False)),
            "seed": int(seed),
            "lyrics": clip.get("lyrics", ""),
            "dialogue": [dict(line) for line in clip.get("dialogue", []) if isinstance(line, dict)],
        })
    for clip, raw in zip(out["clips"], plan["clips"]):
        made = compose_clip(out, raw, clip["index"])
        clip.update(prompt=made["prompt"], refs=made["refs"], compose=made)
    return out


# --------------------------------------------------------------------------- the composed prompt
def _seconds_text(seconds: float) -> str:
    """MM:SS.mmm, as H3's shot times."""
    millis = int(round(float(seconds) * 1000))
    return f"{millis // 60000:02d}:{millis % 60000 // 1000:02d}.{millis % 1000:03d}"


def _shot_start(body: str) -> float:
    match = re.match(r"\s*At (\d+):(\d+(?:\.\d+)?)", body)
    return int(match.group(1)) * 60 + float(match.group(2)) if match else 0.0


def split_shots(text: str):
    """(text before [Shot 1], [body of each shot]). A text without any [Shot N] is the body of shot 1."""
    pieces = SHOT_RE.split(str(text or ""))
    if len(pieces) == 1:
        return "", [pieces[0].strip()]
    return pieces[0].strip(), [pieces[k].strip() for k in range(2, len(pieces), 2)]


def mentioned_subjects(clip, instruction=None):
    """Subject names a raw clip mentions with @, in order of first mention (the edit instruction first, then
    summary, description, soundscape, music; or only its prompt written by hand), then the speakers of its
    dialogue."""
    names = []
    texts = ([instruction] if instruction else []) + [str(clip.get(k) or "") for k in _TEXT_KEYS]
    if isinstance(clip.get("prompt_override"), str) and clip["prompt_override"].strip():
        texts = [clip["prompt_override"]]         # a prompt written by hand: its own subjects only
    for text in texts:
        for name in MENTION_RE.findall(text or ""):
            if name not in names:
                names.append(name)
    for line in clip.get("dialogue") or []:
        speaker = line.get("speaker") if isinstance(line, dict) else None
        if isinstance(speaker, str) and speaker not in names:
            names.append(speaker)
    return names


SPEAKER_RE = re.compile(r"(?<![\w@])@([^\W_](?:[\w-]*\w)?)(\s*\(S\d*\))?")
SPEECH_RE = re.compile(r"<d>(.*?)</d>", re.S)
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s)|\n|</d>|\]")


def mark_speakers(text, number, dialogue, ids):
    """Finds who says each line <d>…</d> of a text and marks that mention @name (Sk): the subject written
    @name (S) in the sentence of the line, else the speaker of the clip's `dialogue` line with that text, else the
    first subject the sentence names (a second line in the same sentence: the same speaker). `ids` ({name: k},
    shared by the texts of a clip) numbers the speakers S1, S2… in the order they first speak."""
    text = str(text or "")
    edits, last_speaker, last_end = [], None, -1
    for m in SPEECH_RE.finditer(text):
        cut = 0
        for b in _SENTENCE_END_RE.finditer(text, 0, m.start()):
            cut = b.end()
        seg = text[cut:m.start()]
        found = [x for x in SPEAKER_RE.finditer(seg) if x.group(1) in number]
        explicit = [x for x in found if x.group(2)]
        speaker = explicit[-1].group(1) if explicit else None
        if speaker is None:
            said = _squash(m.group(1))
            for line in dialogue or []:
                who, words = (line or {}).get("speaker"), _squash(str((line or {}).get("text") or ""))
                if who in number and words and words in said:
                    speaker = who
                    break
        if speaker is None and found:
            speaker = found[0].group(1)
        if speaker is None and cut == last_end:
            speaker = last_speaker
        if speaker:
            ids.setdefault(speaker, len(ids) + 1)
            spot = explicit[-1] if explicit else next((x for x in found if x.group(1) == speaker), None)
            if spot:
                edits.append((cut + spot.start(), cut + spot.end(), f"@{speaker} (S{ids[speaker]})"))
        last_speaker, last_end = speaker, m.end()
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text


def mention_text(text, number, ids=None):
    """@name -> <Subject N> for the subjects of the clip (``number``: name -> N); @name (Sk) -> <Subject N> (Sk),
    the speaker mark of a line (see mark_speakers; a bare (S) takes the speaker's number, or the next one). Any other
    @name loses its @."""
    def one(match):
        name, speaker = match.group(1), match.group(2)
        if name in number:
            mark = ""
            if speaker:
                digits = re.search(r"\d+", speaker)
                if digits:
                    k = digits.group(0)
                elif ids is not None:
                    k = ids.setdefault(name, len(ids) + 1)
                else:
                    k = number[name]
                mark = f" (S{k})"
            return f"<Subject {number[name]}>" + mark
        return name + (speaker or "")
    return SPEAKER_RE.sub(one, str(text or ""))


def compose_clip(plan, raw, index):
    """The H3 prompt of clip ``index`` (normalized plan ``plan``, raw clip ``raw``), with {picture:FILE} and
    {voice:FILE} placeholders that resolve_prompt numbers. Returns
      prompt    the text (the clip's own prompt_override when written by hand, turned into placeholders)
      refs      the files it uses, in order: images (subjects', then anchors'), then voices
      legend    {"subjects": [names], "pictures": [files], "audio": [files, "<video sound>" first when the clip
                 edits a video], "video": bool}: the numbers <Subject N>, <Picture N>, <Audio N> of this clip
      errors, warnings, tasks
    """
    free = plan["mode"] == "free"
    files, subjects = clip_definitions(plan, raw)
    errors, warnings = [], []
    edit = plan.get("edit_video") if edit_slice(plan, index) else None
    instruction = (edit or {}).get("instruction")
    own = raw.get("defs") if isinstance(raw.get("defs"), dict) else {}
    if edit and "edit_instruction" in own:          # a clip already generated keeps the instruction it was made with
        instruction = own["edit_instruction"] if isinstance(own["edit_instruction"], str) else None
    continues = bool(raw.get("continue")) and (index > 1 or plan.get("start_video") is not None)
    uses = {u["name"]: u for u in raw.get("subjects") or [] if isinstance(u, dict) and isinstance(u.get("name"), str)}
    names = mentioned_subjects(raw, instruction)
    for name in names:
        if name not in subjects:
            errors.append(f"@{name} is not a subject of the plan")
    names = [n for n in names if n in subjects]
    for name in uses:
        if name not in names and name in subjects:
            warnings.append(f"subject '{name}' has settings but the clip does not mention @{name}: it is not used")
    number = {name: k for k, name in enumerate(names, start=1)}

    ids = {}                     # speakers: S1, S2… in the order they first speak (the shots, then the summary)
    dialogue = raw.get("dialogue") or []
    marked = {k: mark_speakers(raw.get(k) or "", number, dialogue, ids) for k in ("description", "summary")}

    def mention(text):
        return mention_text(text, number, ids)

    pictures, voices = [], []
    for name in names:
        for pic in subjects[name].get("pictures") or []:
            if pic.get("file") not in pictures:
                pictures.append(pic["file"])
    anchors = raw.get("anchors") or {}
    first, last = anchors.get("first"), anchors.get("last")
    keyframes = sorted((k for k in anchors.get("keyframes") or [] if isinstance(k, dict)), key=lambda k: k.get("at", 0))
    if first and continues:
        errors.append("a clip that continues the previous one cannot have a first-frame anchor: its first frames "
                      "are those of the previous clip")
    for file in [first] + [k.get("file") for k in keyframes] + [last]:
        if file and file not in pictures:
            pictures.append(file)
    for name in names:
        voice = subjects[name].get("voice")
        if voice and not free:
            warnings.append(f"the voice of @{name} is ignored in music_video mode")
        elif voice and voice not in voices:
            voices.append(voice)
    audio = (["<video sound>"] if edit else []) + voices
    if len(pictures) > MAX_REFS:
        errors.append(f"uses {len(pictures)} images; MiniMax H3 accepts at most {MAX_REFS}")
    if len(voices) > MAX_VOICES:
        errors.append(f"uses {len(voices)} voices; MiniMax H3 accepts at most {MAX_VOICES}")
    if len(pictures) + len(voices) + (1 if edit else 0) > MAX_REF_FILES:
        errors.append(f"uses more than {MAX_REF_FILES} reference files")

    tasks = []
    if edit:
        tasks.append("video editing")
    if continues:
        tasks.append("video continuation")
    if first or last or keyframes:
        tasks.append("keyframe completion")
    if any(subjects[n].get("pictures") for n in names):
        tasks.append("reference generation")
    if voices:
        tasks.append("audio reference")
    legend = {"subjects": names, "pictures": pictures, "audio": audio, "video": bool(edit)}

    # ---- detailed_description: the opening sentence and the anchors placed in their shots
    style, shots = split_shots(marked["description"])
    opening = ""
    if continues:
        opening = CONTINUE_SENTENCE + (FREE_CONTINUE_SUFFIX if free else "")
    elif index > 1 or plan.get("start_video") is not None:
        opening = HIDDEN_LEADIN_FREE if free else HIDDEN_LEADIN_MUSIC
    head = " ".join(x for x in (opening, f"The shot begins from {{picture:{first}}}." if first else "") if x)
    if head:
        shots[0] = (head + " " + shots[0]).strip()
    starts = [0.0] + [_shot_start(b) for b in shots[1:]]
    key_shot = []
    for key in keyframes:
        k = max(i for i, t in enumerate(starts) if t <= key["at"] or i == 0)
        key_shot.append(k)
        shots[k] = (shots[k] + f" At {_seconds_text(key['at'])}, the shot's keyframe corresponds to {{picture:{key['file']}}}.").strip()
    if last:
        shots[-1] = (shots[-1] + f" The shot ends on {{picture:{last}}}.").strip()
    description = "\n".join(([mention(style)] if style else []) + [f"[Shot {i + 1}] {mention(b)}".rstrip() for i, b in enumerate(shots)])

    # ---- subject_definitions
    defs = []
    for name in names:
        sub, use = subjects[name], uses.get(name) or {}
        kind = sub.get("kind", "person")
        line = f"<Subject {number[name]}> is {KIND_WORDS[kind]}"
        desc = mention(sub.get("description") or "").strip().rstrip(".")
        if desc:
            line += f": {desc}"
        if str(use.get("note") or "").strip():
            line += f"; in this clip: {mention(use['note']).strip().rstrip('.')}"
        cites = [f"{(pic.get('role') or '').strip() or DEFAULT_ROLES[kind]} from {{picture:{pic['file']}}}"
                 for pic in sub.get("pictures") or []]
        if cites:
            line += "; " + ", ".join(cites)
        defs.append(line + ".")
    if first:
        defs.append(f"{{picture:{first}}} is the first frame of [Shot 1].")
    for key, k in zip(keyframes, key_shot):
        defs.append(f"{{picture:{key['file']}}} is a keyframe of [Shot {k + 1}] at {_seconds_text(key['at'])}.")
    if last:
        defs.append(f"{{picture:{last}}} is the last frame of [Shot {len(shots)}].")
    if edit:
        defs.append("<Video 1> is the source video for the target video edit.")
        defs.append(f"{EDIT_AUDIO_MARK}<Audio 1> is the synchronized audio track of <Video 1> and is reused in the target video.")
    for name in names:
        voice = subjects[name].get("voice")
        if voice in voices:
            ids.setdefault(name, len(ids) + 1)        # a voice that does not speak in this clip: the next number
            defs.append(f"{{voice:{voice}}} is the voice-timbre reference for <Subject {number[name]}> (S{ids[name]}).")

    # ---- summary
    summary = mention(marked["summary"]).strip()
    if edit:
        summary = " ".join(x for x in ("The target video is an edited version of <Video 1>.",
                                        mention(instruction).strip() if instruction else "", summary) if x)
    if tasks:
        summary = f"[{' + '.join(tasks)}{AUDIO_REUSE_MARK if edit else ''}] {summary}".strip()

    # ---- retention_analysis
    retention = []
    for name in names:
        use = uses.get(name) or {}
        seen = [f"[Shot {i + 1}]" for i, b in enumerate(shots) if re.search(rf"(?<![\w@])@{re.escape(name)}(?![\w-])", b)]
        scope = f" (appears in {', '.join(seen)})" if seen else ""
        keep = use.get("keep", DEFAULT_KEEP)
        why = mention(use.get("note") or "").strip() or KEEP_REASONS[keep]
        retention.append(f"<Subject {number[name]}>{scope}: {KEEP_MARKERS[keep]} - {why}")
    if first:
        retention.append(f"{{picture:{first}}} ([Shot 1] first frame): fully_preserved - the shot begins exactly on this frame.")
    for key, k in zip(keyframes, key_shot):
        retention.append(f"{{picture:{key['file']}}} ([Shot {k + 1}] keyframe at {_seconds_text(key['at'])}): fully_preserved - "
                         "the picture matches this frame at that moment.")
    if last:
        retention.append(f"{{picture:{last}}} ([Shot {len(shots)}] last frame): fully_preserved - the shot ends exactly on this frame.")
    if edit:
        retention.append("<Video 1> (source of the edit): partially_preserved - everything the edit does not change stays as in <Video 1>.")
        retention.append(f"{EDIT_AUDIO_MARK}<Audio 1>: " + ("fully_copy - the sound of <Video 1> is kept as it is."
                                                           if edit.get("sound") == "original" else
                                                           "reference - the new sound follows the sound of <Video 1>."))
    for name in names:
        voice = subjects[name].get("voice")
        if voice in voices:
            marker = VOICE_MARKERS[(uses.get(name) or {}).get("voice_keep", DEFAULT_VOICE_KEEP)]
            retention.append(f"{{voice:{voice}}}: {marker} - <Subject {number[name]}> speaks with this voice.")

    parts = ["\n".join(defs), summary, "\n".join(retention), description,
             mention(raw.get("soundscape") or "").strip(), mention(raw.get("music") or "").strip() or ("None." if free else "")]
    prompt = "\n\n".join(f"{section}\n{text}".rstrip() for section, text in zip(_PROMPT_SECTIONS, parts))
    override = raw.get("prompt_override")
    if isinstance(override, str) and override.strip():
        ids = {}
        prompt = _from_override(mark_speakers(override, number, dialogue, ids), number, legend, errors, warnings, ids)
    return {"prompt": prompt, "refs": pictures + voices, "legend": legend, "tasks": tasks,
            "speakers": sorted(([n, k] for n, k in ids.items()), key=lambda x: x[1]),
            "files": {n: dict(files[n]) for n in pictures + voices if n in files},
            "errors": errors, "warnings": warnings, "override": bool(isinstance(override, str) and override.strip())}


def snapshot_defs(raw_plan, plan, index):
    """What a clip about to be generated is made with, to keep in it as 'defs': the definitions of its subjects,
    their files and its anchors' files, and the edit instruction it uses."""
    raw = raw_plan["clips"][index - 1]
    files, subjects = clip_definitions(raw_plan, raw)
    made = plan["clips"][index - 1]["compose"]
    subs = {n: subjects[n] for n in made["legend"]["subjects"]}
    names = set(made["refs"])
    for sub in subs.values():
        names.update(p.get("file") for p in sub.get("pictures") or [])
        if sub.get("voice"):
            names.add(sub["voice"])
    out = json.loads(json.dumps({"subjects": subs, "files": {n: files[n] for n in sorted(names) if n in files}}))
    edit = plan.get("edit_video")
    if edit and edit_slice(plan, index):
        own = raw.get("defs") if isinstance(raw.get("defs"), dict) else {}
        out["edit_instruction"] = own["edit_instruction"] if "edit_instruction" in own else edit.get("instruction")
    return out


def preview(raw):
    """What the plan screen shows: {"errors", "warnings", "clips": [{"index", "prompt" (the text H3 gets, every file
    provided, the edited video's sound counted), "legend", "tasks", "override", "errors", "warnings"}]}. "clips" is
    empty when the plan cannot be read far enough to be composed."""
    errors, warnings = validate(json.loads(json.dumps(raw)))
    out = {"errors": errors, "warnings": warnings, "clips": []}
    try:
        plan = normalize(json.loads(json.dumps(raw)))
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return out
    free = plan["mode"] == "free"
    for clip in plan["clips"]:
        made = clip["compose"]
        files = made["files"]
        try:
            text = resolve_prompt(clip["prompt"], clip["refs"], {n for n, f in files.items() if f.get("kind") == "image"},
                                  {n for n, f in files.items() if f.get("kind") == "voice"}, use_voices=free,
                                  audio_offset=1 if made["legend"]["video"] else 0)[0]
        except PlanError:
            text = clip["prompt"]
        out["clips"].append({"index": clip["index"], "prompt": text, "legend": made["legend"], "tasks": made["tasks"],
                             "speakers": made.get("speakers") or [],
                             "override": made["override"], "errors": made["errors"], "warnings": made["warnings"]})
    return out


def _from_override(text, number, legend, errors, warnings, ids=None):
    """A prompt written by hand: @name, <Picture N> and <Audio N> (numbers of the clip's legend) turned into
    what resolve_prompt numbers again."""
    pictures, audio = legend["pictures"], legend["audio"]

    for name in MENTION_RE.findall(text):
        if name not in number:
            errors.append(f"the prompt written by hand names @{name}, which the clip does not use")
    text = mention_text(text, number, ids)
    for n in sorted({int(x) for x in re.findall(r"<Subject (\d+)>", text)}):
        if not 1 <= n <= len(number):
            errors.append(f"the prompt written by hand uses <Subject {n}> but the clip has {len(number)} subject(s)")

    def one_picture(match):
        n = int(match.group(1))
        if 1 <= n <= len(pictures):
            return f"{{picture:{pictures[n - 1]}}}"
        errors.append(f"the prompt written by hand uses <Picture {n}> but the clip has {len(pictures)} image(s)")
        return match.group(0)
    text = re.sub(r"<Picture (\d+)>", one_picture, text)

    def one_audio(match):
        n = int(match.group(1))
        if 1 <= n <= len(audio):
            return match.group(0) if audio[n - 1] == "<video sound>" else f"{{voice:{audio[n - 1]}}}"
        errors.append(f"the prompt written by hand uses <Audio {n}> but the clip has {len(audio)} sound(s)")
        return match.group(0)
    text = re.sub(r"<Audio (\d+)>", one_audio, text)
    if _VIDEO_TAG_RE.search(text) and not legend["video"]:
        errors.append("the prompt written by hand uses <Video 1> but the clip edits no video")
    position = -1
    for section in _PROMPT_SECTIONS:
        found = text.find(section)
        if found < 0:
            warnings.append(f"the prompt written by hand has no '{section}' section")
        elif found < position:
            warnings.append(f"the prompt written by hand: section '{section}' is out of order")
        position = max(position, found)
    for line in text.splitlines():
        if "{voice:" in line and "{picture:" in line:
            errors.append("the prompt written by hand: put each voice (<Audio N>) on a line without any <Picture N>")
            break
    return text


def stable_seed(project: str, index: int) -> int:
    digest = hashlib.sha256(f"{project}:{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:6], "big")


# --------------------------------------------------------------------------- timing
def timeline(plan):
    """Per-clip timing of a normalized plan.

    raw_start    first frame generated by the clip on the song timeline
    context      frames shared with the end of the previous clip (0 for clip 1)
    visible      first frame of the clip that reaches the final video
    end          frame after the last one
    """
    rows = []
    previous = start_row(plan)   # the start video segment acts as the clip before clip 1
    for clip in plan["clips"]:
        frames = clip["frames"]
        if previous is None:
            context, raw_start = 0, 0
        else:
            context = snap_context(plan["context_frames"], previous["frames"], frames)
            raw_start = previous["end"] - context
        row = {
            "index": clip["index"],
            "name": clip["name"],
            "frames": frames,
            "continue": clip["continue"],
            "context": context,
            "raw_start": raw_start,
            "visible": raw_start + context,
            "end": raw_start + frames,
        }
        row["raw_start_seconds"] = row["raw_start"] / FPS
        row["visible_seconds"] = row["visible"] / FPS
        row["end_seconds"] = row["end"] / FPS
        rows.append(row)
        previous = row
    return rows


def start_row(plan):
    """Timing of the start video segment (frames 0 to its length on the timeline), or None."""
    spec = plan.get("start_video")
    if not spec:
        return None
    return {"index": 0, "frames": spec["frames"], "raw_start": 0, "visible": 0, "end": spec["frames"], "context": 0}


def final_start(plan) -> int:
    """First timeline frame of the assembled video.

    With a start video kept out of the assembly, the video starts where clip 1 starts: its first
    frames are the regenerated end of the segment (or the lead-in of a new scene).
    """
    spec = plan.get("start_video")
    if not spec or spec["in_assembly"]:
        return 0
    return timeline(plan)[0]["raw_start"]


def song_offset(plan) -> int:
    """Timeline frame at which the song starts (music_video mode).

    No start video, or one kept in the video with 'with_video': the song starts with the timeline.
    'after_video': the segment keeps its own sound, the song starts when clip 1 shows.
    Start video kept out of the video: the song starts with the assembled video.
    """
    spec = plan.get("start_video")
    if not spec or plan.get("mode") == "free":
        return 0
    if not spec["in_assembly"]:
        return final_start(plan)
    return 0 if spec["song"] == "with_video" else spec["frames"]


def segment_chunks(frames: int, context: int, limit: int = SOFT_MAX_FRAMES):
    """Split a start video segment of ``frames`` (17k + 5) into pieces the assembler can join like clips:
    [(first frame, length), ...], each piece overlapping the previous one by ``context`` frames."""
    pieces = []
    start = 0
    while True:
        length = min(frames - start, limit)
        length = largest_h3_run(length)
        if length <= context:
            raise ValueError(f"cannot split {frames} frames into pieces overlapping by {context}")
        pieces.append((start, length))
        if start + length >= frames:
            return pieces
        start = start + length - context


def total_frames(plan) -> int:
    return timeline(plan)[-1]["end"]


def clip_fingerprint(plan, index: int) -> str:
    """Changes whenever something that affects this clip's pixels changes."""
    clip = plan["clips"][index - 1]
    row = timeline(plan)[index - 1]
    payload = {
        "frames": clip["frames"], "continue": clip["continue"], "refs": clip["refs"],
        "prompt": clip["prompt"], "seed": clip["seed"], "raw_start": row["raw_start"],
        "context": row["context"],
    }
    if plan.get("mode", "music_video") != "music_video":
        payload["mode"] = plan["mode"]   # keeps music_video fingerprints identical to plan v2
    payload.update(_start_video_payload(plan, index))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def format_timeline(plan) -> str:
    lines = [
        f"project {plan['project']} - {plan.get('mode', 'music_video')} mode - {len(plan['clips'])} clips - "
        f"{'%dx%d' % (plan['width'], plan['height']) if plan['width'] else 'size set in the workflow'} - "
        f"context {plan['context_frames']} frames - crossfade {plan['crossfade_frames']} frames",
        "clip  name                      frames  raw start  visible     end     shown  type      refs",
    ]
    spec = plan.get("start_video")
    if spec:
        lines.append(
            f"   0  start video '{spec['ref']}' {spec['start_frame'] / FPS:.3f}-{spec['end_frame'] / FPS:.3f} s of the file: "
            f"{spec['frames']} frames, {'in' if spec['in_assembly'] else 'not in'} the final video"
            + (f", song from timeline {song_offset(plan) / FPS:.3f} s" if plan.get("mode") != "free" else "")
        )
    edit = plan.get("edit_video")
    if edit:
        lines.append(
            f"   edits the video '{edit['ref']}' {edit['start_frame'] / FPS:.3f}-{edit['end_frame'] / FPS:.3f} s of the file "
            f"({edit['frames']} frames), {'original' if edit['sound'] == 'original' else 'generated'} sound in the final video"
        )
    for clip, row in zip(plan["clips"], timeline(plan)):
        lines.append(
            f"{row['index']:>4}  {row['name'][:24]:<24}  {row['frames']:>6}  {row['raw_start_seconds']:>9.3f}  "
            f"{row['visible_seconds']:>7.3f}  {row['end_seconds']:>7.3f}  "
            f"{(row['end'] - row['visible']) / FPS:>6.2f}s  {'continue' if row['continue'] else 'new     '}  "
            f"{', '.join(clip['refs']) or '-'}"
        )
    shown = total_frames(plan) - final_start(plan)
    lines.append(f"final video: {shown} frames = {shown / FPS:.3f} s")
    return "\n".join(lines)


def reference_names(plan):
    """Every file name the plan uses: those declared first, then the files clips use."""
    names = list(plan.get("files", {}))
    for clip in plan["clips"]:
        for name in clip["refs"]:
            if name not in names:
                names.append(name)
    return names


def reference_kinds(plan, name):
    """What a normalized plan needs for a file: 'video', 'image' or 'voice' (one kind per file in v7)."""
    kinds = []
    if (plan.get("start_video") or {}).get("ref") == name or (plan.get("edit_video") or {}).get("ref") == name:
        kinds.append("video")
    for clip in plan["clips"]:
        if name in clip["refs"]:
            kind = "voice" if f"{{voice:{name}}}" in clip["prompt"] else "image"
            if kind not in kinds:
                kinds.append(kind)
    return kinds


def file_of(plan, name, clip=None):
    """The declared entry {kind, file} of a file name (the clip's own 'defs' first), or {}."""
    if clip is not None:
        own = ((clip.get("defs") or {}).get("files") or {}) if isinstance(clip.get("defs"), dict) else {}
        if name in own:
            return own[name]
    return (plan.get("files") or {}).get(name) or {}


def check_size(width, height):
    """Return an error message, or None if the picture size is usable by H3."""
    for label, value in (("width", width), ("height", height)):
        if not _is_int(value) or value < 64 or value % 32 != 0:
            return f"{label} must be a multiple of 32 (got {value!r})"
    return None


# --------------------------------------------------------------------------- prompt placeholders
def resolve_prompt(prompt: str, refs, has_image, has_voice, use_voices: bool = True, audio_offset: int = 0):
    """Turn {picture:NAME} / {voice:NAME} placeholders into H3's <Picture N> / <Audio N>.

    refs       the clip's reference names, in order
    has_image  names for which the workflow provides an image
    has_voice  names for which the workflow provides a voice
    use_voices False in music_video mode (the song is injected, voices cannot be used)
    audio_offset  <Audio N> labels taken before the voices (the sound of the edited video is <Audio 1>); without
               it, the composed lines about that sound are removed

    Images are numbered in the order of ``refs`` among the names that have an image.
    Voices are numbered in the order of ``refs`` among the names whose voice is used.
    A line that holds {voice:NAME} is removed when that voice is not used, so H3
    picks a voice of its own for that character.

    Returns (text, image_names, voice_names, notes). Raises PlanError when the prompt
    asks for an image the workflow does not provide.
    """
    images = [name for name in refs if name in has_image]
    used = {name for kind, name in PLACEHOLDER_RE.findall(prompt) if kind == "voice"}
    voices = [name for name in refs if name in used and name in has_voice and use_voices]
    notes = []
    missing_pictures = sorted({name for kind, name in PLACEHOLDER_RE.findall(prompt)
                               if kind == "picture" and name not in has_image})
    if missing_pictures:
        raise PlanError([f"the prompt shows {{picture:{name}}} but no reference image is named '{name}'"
                         for name in missing_pictures])
    for name in refs:
        if name in has_voice and name not in voices:
            if not use_voices:
                notes.append(f"voice '{name}' ignored (music_video mode)")
            elif name not in used:
                notes.append(f"voice '{name}' not used: the prompt has no {{voice:{name}}} line")
    lines = []
    for line in prompt.split("\n"):
        if line.startswith(EDIT_AUDIO_MARK):     # the sound of the edited video: only when it has one
            if not audio_offset:
                continue
            line = line[len(EDIT_AUDIO_MARK):]
        line = line.replace(AUDIO_REUSE_MARK, " + audio reuse" if audio_offset else "")
        dropped = [name for kind, name in PLACEHOLDER_RE.findall(line) if kind == "voice" and name not in voices]
        if dropped:
            for name in dropped:
                if use_voices:
                    notes.append(f"no voice for '{name}': H3 chooses one")
            continue
        lines.append(line)
    text = "\n".join(lines)

    def number(match):
        kind, name = match.group(1), match.group(2)
        if kind == "picture":
            return f"<Picture {images.index(name) + 1}>"
        return f"<Audio {audio_offset + voices.index(name) + 1}>"

    return PLACEHOLDER_RE.sub(number, text), images, voices, notes


# --------------------------------------------------------------------------- takes
def take_fingerprint(plan, index: int) -> str:
    """Like clip_fingerprint, without the seed: two takes of a clip differ only by their seed."""
    clip = plan["clips"][index - 1]
    row = timeline(plan)[index - 1]
    payload = {
        "frames": clip["frames"], "continue": clip["continue"], "refs": clip["refs"],
        "prompt": clip["prompt"], "raw_start": row["raw_start"], "context": row["context"],
        "mode": plan.get("mode", "music_video"),
    }
    payload.update(_start_video_payload(plan, index))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _start_video_payload(plan, index: int):
    """What a start video adds to a fingerprint (nothing without one, so older fingerprints stay the same):
    the segment for clip 1 when it continues it, and where the song lies under the clips."""
    edit = plan.get("edit_video")
    if edit:      # with raw_start: the slice of the file (the clips after the segment have none)
        return {"edit_video": [edit["ref"], edit["start_frame"]]} if edit_slice(plan, index) else {}
    spec = plan.get("start_video")
    if not spec:
        return {}
    extra = {}
    if index == 1 and plan["clips"][0]["continue"]:
        extra["start_video"] = [spec["ref"], spec["start_frame"], spec["end_frame"]]
    if plan.get("mode", "music_video") == "music_video":
        extra["song_offset"] = song_offset(plan)
    return extra


def resolve_takes(plan, takes, selection=None):
    """Decide which saved takes can be used, and which one each clip uses.

    takes      {clip index: [record, ...]}. A record is the metadata saved with a take:
               id, seed, saved_at, fingerprint (take_fingerprint), frames, width, height,
               refs {name: {"image": hash|None, "voice": hash|None}} (what the workflow provided),
               parent (id of the take of the previous clip it continues, or None).
    selection  {clip index: take id} chosen by the user (may be stale or missing).

    Returns {index: {"chosen": id or None, "takes": {id: (state, reason)}, "kinds": {id: kind}}} where
    kind tells why a stale take is stale: "plan", "size", "refs", "parent_missing" (the take it
    continues does not exist any more) or "parent_stale" (it exists but is stale). State is
      "ok"     usable: up to date and, for a continuation, built on the take chosen for the previous clip;
      "other"  up to date, but built on another take of the previous clip (usable if that one is chosen);
      "stale"  must be thrown away: its plan entry changed, it was made with other images, voices or
               picture size than the latest take, or the take it continues no longer exists.

    The "current" images, voices and picture size are those of the most recently saved take.
    A clip uses the selected take when it is "ok", otherwise its most recent "ok" take.
    """
    selection = {int(k): v for k, v in (selection or {}).items()}
    everything = [r for records in takes.values() for r in records]
    current_refs, current_size = {}, None
    for record in sorted(everything, key=lambda r: r.get("saved_at", 0)):
        for name, kinds in (record.get("refs") or {}).items():
            for kind in ("image", "voice", "video"):
                current_refs[(name, kind)] = (kinds or {}).get(kind)
        current_size = (record.get("width"), record.get("height"))

    result = {}
    for clip in plan["clips"]:
        index = clip["index"]
        fingerprint = take_fingerprint(plan, index)
        previous = result.get(index - 1)
        living_parents = {tid for tid, (state, _w) in (previous or {"takes": {}})["takes"].items() if state != "stale"}
        states, why_kind = {}, {}
        existing_parents = {r["id"] for r in takes.get(index - 1, [])}
        for record in sorted(takes.get(index, []), key=lambda r: r.get("saved_at", 0)):
            reason = kind = None
            if record.get("frames") != clip["frames"] or record.get("fingerprint") != fingerprint:
                reason, kind = "its entry in the plan changed", "plan"
            elif (record.get("width"), record.get("height")) != current_size:
                reason = (f"made at {record.get('width')}x{record.get('height')}, "
                          f"the latest take at {current_size[0]}x{current_size[1]}")
                kind = "size"
            else:
                for name, kinds in sorted((record.get("refs") or {}).items()):
                    for what in ("image", "voice", "video"):
                        if (kinds or {}).get(what) != current_refs.get((name, what)):
                            reason = f"the {what} of '{name}' changed since"
                            kind = "refs"
                            break
                    if reason:
                        break
            if reason:
                states[record["id"]] = ("stale", reason)
                why_kind[record["id"]] = kind
            elif clip["continue"] and index > 1:
                parent = record.get("parent")
                if parent not in living_parents:
                    if parent in existing_parents:
                        states[record["id"]] = ("stale", f"the take of clip {index - 1} it continues is stale")
                        why_kind[record["id"]] = "parent_stale"
                    else:
                        states[record["id"]] = ("stale", f"the take of clip {index - 1} it continues no longer exists")
                        why_kind[record["id"]] = "parent_missing"
                elif parent != previous["chosen"]:
                    states[record["id"]] = ("other", f"continues take {parent} of clip {index - 1}, not the chosen one")
                else:
                    states[record["id"]] = ("ok", "")
            else:
                states[record["id"]] = ("ok", "")
        usable = [tid for tid, (state, _w) in states.items() if state == "ok"]
        wanted = selection.get(index)
        chosen = wanted if wanted in usable else (usable[-1] if usable else None)
        result[index] = {"chosen": chosen, "takes": states, "kinds": why_kind}
    return result


AUTO_DELETE_KINDS = ("plan", "parent_missing")   # stale for sure: deleted automatically when asked to


def usable_prefix(plan, resolved, last_clip=0):
    """Number of clips that can be assembled from clip 1: stops at the first clip without a usable take."""
    limit = len(plan["clips"]) if not last_clip else min(int(last_clip), len(plan["clips"]))
    count = 0
    for index in range(1, limit + 1):
        if not resolved.get(index, {}).get("chosen"):
            break
        count = index
    return count
