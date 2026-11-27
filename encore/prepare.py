"""Encore - the files a generation sends to ComfyUI, prepared beforehand with ffmpeg (0.50).

ComfyUI does all the inference; Encore only cuts and rewrites files, as the ComfyUI-H3-ClipPlan plugin did inside its
own node before:
- a voice cut to H3's limits (2 to 15 s each, 15 s in all);
- the song with silence before it, when it starts later than the plan;
- a piece of a video (the end of the start video, the slice an edited clip covers), at the branch size (resized to
  cover it, cropped in the middle), at 24 fps, with its sound.

Each prepared file is kept in the project (cache/comfy/), named after what made it: it is made once.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from . import plan_core
from .i18n import t as _t
from .projects import StudioError

FPS = plan_core.FPS
START_CONTEXT_SOURCE = 90      # frames of the start video given to continue it (17k + 5, on the audio grid)


def _no_window():
    import os
    return {"creationflags": 0x08000000} if os.name == "nt" else {}


def _run(cmd, what):
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=1800, **_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        raise StudioError(_t("prepare.ffmpeg_failed", what=what, error=str(exc))) from exc
    if done.returncode != 0:
        raise StudioError(_t("prepare.ffmpeg_failed", what=what, error=done.stderr.decode("utf-8", "replace").strip()[-300:]))
    return done


def _cache(project: Path, key, ext):
    folder = project / "cache" / "comfy"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:20] + ext)


def probe(ffmpeg, file: Path):
    """(duration in seconds or None, has sound)."""
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(file)], capture_output=True, text=True, errors="replace",
                             timeout=60, **_no_window())
    except (OSError, subprocess.SubprocessError):
        return None, False
    found = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr)
    duration = int(found.group(1)) * 3600 + int(found.group(2)) * 60 + float(found.group(3)) if found else None
    return duration, "Audio:" in out.stderr


def need_ffmpeg(ffmpeg, what):
    if not ffmpeg:
        raise StudioError(_t("prepare.no_ffmpeg", what=what))


def voices(ffmpeg, project: Path, items):
    """items: [(name, file, sha)] the clip's voices in order. Each one cut to H3's limits: at least 2 s, and its
    share of 15 s. Returns [(file to send, sha of that file)] and the notes."""
    if not items:
        return [], []
    need_ffmpeg(ffmpeg, _t("prepare.what_voices"))
    budget = plan_core.VOICE_TOTAL_SECONDS / len(items)
    out, notes = [], []
    for name, file, sha in items:
        seconds, _sound = probe(ffmpeg, file)
        if seconds is None:
            raise StudioError(_t("prepare.cannot_read", file=Path(file).name))
        if seconds < plan_core.VOICE_MIN_SECONDS:
            raise StudioError(_t("prepare.voice_too_short", name=name, seconds=f"{seconds:.1f}",
                                 minimum=f"{plan_core.VOICE_MIN_SECONDS:.0f}"))
        keep = min(seconds, budget)
        target = _cache(project, ("voice", sha, round(keep, 3)), ".wav")
        if not target.is_file():
            tmp = target.with_suffix(".part.wav")
            _run([ffmpeg, "-v", "error", "-y", "-i", str(file), "-t", f"{keep:.3f}", "-vn", "-ac", "2", "-c:a", "pcm_s16le",
                  str(tmp)], _t("prepare.what_voice", name=name))
            tmp.replace(target)
        if keep < seconds - 0.05:
            notes.append(_t("prepare.voice_cut", name=name, seconds=f"{keep:.1f}"))
        out.append(target)
    return out, notes


def shifted_song(ffmpeg, project: Path, song: Path, sha, offset_frames: int):
    """The song as heard on the timeline of the plan: offset_frames of silence first."""
    if offset_frames <= 0:
        return song
    need_ffmpeg(ffmpeg, _t("prepare.what_song"))
    target = _cache(project, ("song", sha, int(offset_frames)), ".wav")
    if not target.is_file():
        ms = int(round(offset_frames / FPS * 1000))
        tmp = target.with_suffix(".part.wav")
        _run([ffmpeg, "-v", "error", "-y", "-i", str(song), "-vn", "-ac", "2", "-af", f"adelay={ms}:all=1", "-c:a", "pcm_s16le",
              str(tmp)], _t("prepare.what_song"))
        tmp.replace(target)
    return target


def video_piece(ffmpeg, project: Path, video: Path, sha, start_frame: int, frames: int, width: int, height: int,
                sound: bool):
    """frames pictures of a video from start_frame (24 fps timeline), resized to cover width x height and cropped in
    the middle, with its sound (stereo) when asked; a .mkv file (lossless enough, any sound codec)."""
    need_ffmpeg(ffmpeg, _t("prepare.what_video"))
    target = _cache(project, ("video", sha, int(start_frame), int(frames), int(width), int(height), bool(sound)), ".mkv")
    if not target.is_file():
        tmp = target.with_suffix(".part.mkv")
        cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{start_frame / FPS:.6f}", "-i", str(video),
               "-vf", f"fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}",
               "-frames:v", str(int(frames)), "-c:v", "libx264", "-preset", "veryfast", "-crf", "8", "-pix_fmt", "yuv420p"]
        cmd += (["-t", f"{frames / FPS:.6f}", "-ac", "2", "-c:a", "pcm_s16le"] if sound else ["-an"])
        _run(cmd + [str(tmp)], _t("prepare.what_video"))
        tmp.replace(target)
    return target
