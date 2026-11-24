"""H3 Clip Plan - plan parsing, validation and timing.

Pure Python on purpose (no torch, no ComfyUI import) so that the same code runs
inside the nodes, in the command-line checker and in the tests.
"""
from __future__ import annotations

import hashlib
import json
import re

FPS = 24
PLAN_VERSION = 6
ACCEPTED_VERSIONS = (1, 2, 3, 4, 5, 6)   # older plans still load as music_video plans
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
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_PROMPT_SECTIONS = (
    "subject_definitions:", "summary:", "retention_analysis:",
    "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
)
_PLAN_KEYS = {
    "version", "project", "mode", "refs_dir", "refs", "width", "height", "context_frames",
    "crossfade_frames", "audio_feather_ticks", "seed", "ref_image_size", "song", "clips", "notes", "start_video",
    "edit_video",
}
_START_VIDEO_KEYS = {"ref", "start", "end", "in_assembly", "song"}
START_SONG_CHOICES = ("with_video", "after_video")   # music_video: the song starts with the video, or after it
_EDIT_VIDEO_KEYS = {"ref", "start", "end", "sound", "instruction"}
EDIT_MARK = "{edit}"     # replaced by edit_video.instruction, the edit common to the clips
EDIT_SOUND_CHOICES = ("original", "h3")   # the final video keeps the sound of the segment, or the one H3 made
EDIT_MIN_FRAMES = 48     # a reference video lasts 2 to 15 s
EDIT_MAX_FRAMES = 360
_VIDEO_TAG_RE = re.compile(r"<Video (\d+)>")
_CLIP_KEYS = {"name", "frames", "continue", "refs", "prompt", "seed", "lyrics", "dialogue", "notes"}
_DIALOGUE_KEYS = {"speaker", "text", "language"}
PLACEHOLDER_RE = re.compile(r"\{(picture|voice):([A-Za-z0-9][A-Za-z0-9_-]*)\}")
_ANY_BRACE_RE = re.compile(r"\{(picture|voice|image|audio)\s*:[^}]*\}", re.IGNORECASE)


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
    if "refs_dir" in plan:
        warnings.append("'refs_dir' is no longer used: reference images are now chosen in the workflow")
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

    refs_map = plan.get("refs", {})
    if not isinstance(refs_map, dict):
        errors.append("'refs' must be an object mapping a reference name to a short description")
        refs_map = {}
    for name, description in refs_map.items():
        if not _NAME_RE.match(str(name)):
            errors.append(f"reference name '{name}' may only contain letters, digits, '_' and '-'")
        if not isinstance(description, str):
            errors.append(f"reference '{name}': the description must be a string")

    start_video = plan.get("start_video")
    start_frames = None
    if start_video is not None:
        start_frames = _check_start_video(start_video, refs_map, free, context, errors, warnings)
    edit_video = plan.get("edit_video")
    edit_frames = None
    if edit_video is not None:
        if start_video is not None:
            errors.append("'start_video' and 'edit_video' cannot be used together: a plan continues a video or edits one")
        if not free:
            errors.append("'edit_video' needs free mode: the edited clips keep the sound of the video (or H3's), not a song")
        edit_frames = _check_edit_video(edit_video, refs_map, errors, warnings)
    instruction = edit_instruction(plan) if edit_video is not None else None

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

        refs = clip.get("refs", [])
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            errors.append(f"{label}: 'refs' must be an array of reference names")
            refs = []
        raw_prompt = clip.get("prompt")
        if isinstance(raw_prompt, str) and EDIT_MARK in raw_prompt and instruction is None:
            errors.append(f"{label}: the prompt uses {EDIT_MARK} but the plan has no common edit instruction "
                          "('instruction' of 'edit_video')")
        expanded_prompt, refs = expand_edit(raw_prompt, refs, instruction)
        if len(set(refs)) != len(refs):
            errors.append(f"{label}: the same reference is listed twice")
        limit = MAX_REF_FILES if free else MAX_REFS
        if len(refs) > limit:
            errors.append(f"{label}: at most {limit} references per clip (got {len(refs)})")
        for ref in refs:
            if not _NAME_RE.match(ref):
                errors.append(f"{label}: reference name '{ref}' may only contain letters, digits, '_' and '-'")
            elif refs_map and ref not in refs_map:
                errors.append(f"{label}: reference '{ref}' is not declared in the top-level 'refs' object")
        if not refs:
            warnings.append(f"{label}: no reference; the clip is generated from text only")

        prompt = expanded_prompt
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"{label}: 'prompt' must be a non-empty string")
            prompt = ""
        else:
            position = -1
            for section in _PROMPT_SECTIONS:
                found = prompt.find(section)
                if found < 0:
                    warnings.append(f"{label}: prompt has no '{section}' section")
                elif found < position:
                    warnings.append(f"{label}: prompt section '{section}' is out of order")
                position = max(position, found)
            placeholders = PLACEHOLDER_RE.findall(prompt)
            pictures = {n for kind, n in placeholders if kind == "picture"}
            voices = {n for kind, n in placeholders if kind == "voice"}
            for match in _ANY_BRACE_RE.finditer(prompt):
                if not PLACEHOLDER_RE.fullmatch(match.group(0)):
                    errors.append(f"{label}: '{match.group(0)}' is not a valid placeholder; write {{picture:NAME}} or {{voice:NAME}}")
            for ref in sorted(pictures | voices):
                if ref not in refs:
                    errors.append(f"{label}: the prompt uses a placeholder for '{ref}' but 'refs' of the clip does not list it")
            numbered = sorted({int(n) for n in re.findall(r"<Picture (\d+)>", prompt)})
            for number in numbered:
                if number < 1 or number > len(refs):
                    errors.append(f"{label}: prompt uses <Picture {number}> but the clip lists {len(refs)} reference(s)")
            if numbered and pictures:
                errors.append(f"{label}: do not mix <Picture N> and {{picture:NAME}} in one prompt; use {{picture:NAME}}")
            if len(pictures) > MAX_REFS:
                errors.append(f"{label}: at most {MAX_REFS} reference images per clip")
            if len(voices) > MAX_VOICES:
                errors.append(f"{label}: at most {MAX_VOICES} voices per clip (got {len(voices)}: {', '.join(sorted(voices))})")
            if len(pictures) + len(voices) > MAX_REF_FILES:
                errors.append(f"{label}: at most {MAX_REF_FILES} reference files (images + voices) per clip")
            for line in prompt.splitlines():
                if "{voice:" in line and ("{picture:" in line or "<Picture" in line):
                    errors.append(f"{label}: put each {{voice:NAME}} on its own line, without any picture on that line")
                    break
            videos = sorted({int(n) for n in _VIDEO_TAG_RE.findall(prompt)})
            if videos and edit_video is None:
                errors.append(f"{label}: the prompt uses <Video N> but the plan edits no video (set 'edit_video')")
            elif any(n != 1 for n in videos):
                errors.append(f"{label}: the edited video is <Video 1> (the only reference video of a clip)")
            if "<Audio " in prompt:
                if free:
                    errors.append(f"{label}: do not write <Audio N>; write {{voice:NAME}} on its own line and the node numbers it")
                else:
                    warnings.append(f"{label}: prompt mentions <Audio N>; the song is injected directly and must not be declared as an audio reference")
            if voices and not free:
                warnings.append(f"{label}: voices are ignored in music_video mode; the {{voice:...}} lines are removed")

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
            if not isinstance(speaker, str) or speaker not in refs:
                errors.append(f"{where}: 'speaker' must be one of the clip's refs (got {speaker!r})")
            if not isinstance(text, str) or not text.strip():
                errors.append(f"{where}: 'text' must be a non-empty string")
                continue
            words += len(text.split())
            if prompt and _squash(text) not in _squash(prompt):
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


def _check_start_video(spec, refs_map, free, context, errors, warnings):
    """Check 'start_video'; return the number of frames of the segment, or None."""
    if not isinstance(spec, dict):
        errors.append("'start_video' must be an object: {\"ref\": NAME, \"start\": seconds, \"end\": seconds}")
        return None
    for key in spec:
        if key not in _START_VIDEO_KEYS and not key.startswith("_"):
            warnings.append(f"start_video: unknown key '{key}' is ignored")
    ref = spec.get("ref")
    if not isinstance(ref, str) or not _NAME_RE.match(ref):
        errors.append("start_video: 'ref' must be a reference name")
    elif ref not in refs_map:
        errors.append(f"start_video: reference '{ref}' is not declared in the top-level 'refs' object")
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


def _check_edit_video(spec, refs_map, errors, warnings):
    """Check 'edit_video'; return the number of frames of the segment, or None."""
    if not isinstance(spec, dict):
        errors.append("'edit_video' must be an object: {\"ref\": NAME, \"start\": seconds, \"end\": seconds}")
        return None
    for key in spec:
        if key not in _EDIT_VIDEO_KEYS and not key.startswith("_"):
            warnings.append(f"edit_video: unknown key '{key}' is ignored")
    ref = spec.get("ref")
    if not isinstance(ref, str) or not _NAME_RE.match(ref):
        errors.append("edit_video: 'ref' must be a reference name")
    elif ref not in refs_map:
        errors.append(f"edit_video: reference '{ref}' is not declared in the top-level 'refs' object")
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
            if EDIT_MARK in instruction:
                errors.append(f"edit_video: the instruction cannot contain {EDIT_MARK}")
            for match in _ANY_BRACE_RE.finditer(instruction):
                if not PLACEHOLDER_RE.fullmatch(match.group(0)):
                    errors.append(f"edit_video: '{match.group(0)}' in the instruction is not a valid placeholder")
            for _kind, name in PLACEHOLDER_RE.findall(instruction):
                if refs_map and name not in refs_map:
                    errors.append(f"edit_video: the instruction names '{name}', which is not declared in 'refs'")
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


def expand_edit(prompt, refs, instruction):
    """A clip's prompt with {edit} replaced by the common instruction, and its references with those the
    instruction names added at the end (so a picture named once in the instruction is in every clip)."""
    if instruction is None or not isinstance(prompt, str) or EDIT_MARK not in prompt:
        return prompt, list(refs)
    refs = list(refs)
    for _kind, name in PLACEHOLDER_RE.findall(instruction):
        if name not in refs:
            refs.append(name)
    return prompt.replace(EDIT_MARK, instruction), refs


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
        "refs": dict(plan.get("refs", {})),
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
    instruction = (out["edit_video"] or {}).get("instruction")
    for index, clip in enumerate(plan["clips"], start=1):
        seed = clip.get("seed")
        if seed is None:
            seed = (int(base_seed) + index) if base_seed is not None else stable_seed(plan["project"], index)
        out["clips"].append({
            "index": index,
            "name": clip.get("name", f"clip_{index:03d}"),
            "frames": int(clip["frames"]),
            "continue": bool(clip.get("continue", False)),
            **dict(zip(("prompt", "refs"), expand_edit(clip["prompt"], clip.get("refs", []), instruction))),
            "seed": int(seed),
            "lyrics": clip.get("lyrics", ""),
            "dialogue": [dict(line) for line in clip.get("dialogue", []) if isinstance(line, dict)],
        })
    return out


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
    """Every reference name used by the plan: declared ones first, then first use order."""
    names = list(plan.get("refs", {}))
    for clip in plan["clips"]:
        for name in clip["refs"]:
            if name not in names:
                names.append(name)
    return names


def reference_kinds(plan, name):
    """What a normalized plan needs for a reference: 'video' (start video), 'image', 'voice'."""
    kinds = []
    if (plan.get("start_video") or {}).get("ref") == name or (plan.get("edit_video") or {}).get("ref") == name:
        kinds.append("video")
    for clip in plan["clips"]:
        if name not in clip["refs"]:
            continue
        found = {kind for kind, ref in PLACEHOLDER_RE.findall(clip["prompt"]) if ref == name}
        if "picture" in found or ("<Picture" in clip["prompt"] and not PLACEHOLDER_RE.search(clip["prompt"])):
            if "image" not in kinds:
                kinds.append("image")
        if "voice" in found and plan.get("mode") == "free" and "voice" not in kinds:
            kinds.append("voice")
    return kinds


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
    audio_offset  <Audio N> labels taken before the voices (the sound of the edited video is <Audio 1>)

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
