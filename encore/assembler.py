"""The final video made by Encore itself with ffmpeg, from the takes' previews (no new decoding of the latents,
no wait in ComfyUI's queue). It follows the plugin's assembly (H3 Plan - Assemble Final Video):

- picture: each clip after the first loses its first frames (the overlap with the clip before it: a copy of its end
  for a « continue » clip, a hidden lead-in for a new scene), or they are blended over ``crossfade_frames``;
  a start video « in the assembly » comes first, cut from its file and fitted to the size of the clips;
- sound: music video, the song on the timeline (the start video's own sound under it with « after the video »);
  free mode, the sound of each take joined like the picture (a « continue » clip keeps its own version of the
  overlap, a new scene keeps the previous clip's sound under its lead-in); an edited video with its original sound
  keeps that sound over the edited part.

Every take needs its preview, and ffmpeg (0.50: the plugin's assembly is not used any more)."""
from __future__ import annotations

import array
import os
import re
import subprocess
import threading
from pathlib import Path

from . import plan_core, previews, projects, takes
from .i18n import t as _t
from .projects import StudioError

FPS = plan_core.FPS
RATE = 48000


def previews_of(project: Path, job):
    """The preview of each take of the job, or None when one is missing."""
    out = []
    for index in range(1, int(job["clips"]) + 1):
        take = (job.get("takes") or {}).get(str(index))
        mp4 = takes.take_files(project, index, take)[2] if take else None
        if mp4 is None or not mp4.is_file():
            return None
        out.append(mp4)
    return out


def _pcm(ffmpeg, path, start=0.0, duration=None):
    """The sound of a file as stereo float samples at RATE (silence if it has none)."""
    cmd = [ffmpeg, "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.6f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.6f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "2", "-ar", str(RATE), "-f", "f32le", "-"]
    done = subprocess.run(cmd, capture_output=True, **previews._no_window())
    samples = array.array("f")
    if done.returncode == 0:
        samples.frombytes(done.stdout[: len(done.stdout) // 4 * 4])
    return samples


def _fit(samples, frames_count):
    """Exactly ``frames_count`` stereo samples (cut, or padded with silence)."""
    want = 2 * frames_count
    if len(samples) >= want:
        return samples[:want]
    return samples + array.array("f", bytes(4 * (want - len(samples))))


def _at(frame):
    """Sample index of a timeline frame."""
    return int(round(frame / FPS * RATE))


def _put(buffer, start, samples):
    """Write stereo samples into the buffer from sample ``start`` (what passes its end is dropped)."""
    start = max(0, start)
    end = min(len(buffer) // 2, start + len(samples) // 2)
    if end > start:
        buffer[2 * start:2 * end] = samples[: 2 * (end - start)]


def build(project: Path, job, ffmpeg, target: Path, on_progress=None, procs=None):
    """Make the final video of an assembly job in ``target``; returns the report."""
    spec = job["spec"]
    plan = plan_core.normalize(spec["raw"])
    count = int(job["clips"])
    rows = plan_core.timeline(plan)[:count]
    files = previews_of(project, job)
    if files is None:
        raise StudioError(_t("assembler.preview_missing"))
    width, height = (int(v) for v in job["size"])
    first_frame = plan_core.final_start(plan)
    end_frame = rows[-1]["end"]
    total = end_frame - first_frame
    crossfade = int(plan.get("crossfade_frames") or 0)
    report = [f"assembled clips 1 to {count} of {len(plan['clips'])} with ffmpeg, from the takes' previews; takes: "
              + ", ".join(f"{i}={job['takes'][str(i)]}" for i in range(1, count + 1))]

    # ---- picture: the pieces, each with the frames it shows
    inputs, pieces = [], []          # pieces: (input index, first local frame, end local frame, needs fitting)
    sv = spec.get("start_video")
    start_spec = plan.get("start_video") if sv else None
    if start_spec:
        source = projects.safe_join(project, sv["video"])
        inputs.append(["-ss", f"{start_spec['start_frame'] / FPS:.6f}", "-t", f"{start_spec['frames'] / FPS + 1:.6f}", "-i", str(source)])
        pieces.append((0, 0, start_spec["frames"], True))
        report.append(f"starts with {start_spec['frames'] / FPS:.2f} s of the video '{start_spec['ref']}'")
    for row, mp4 in zip(rows, files):
        inputs.append(["-i", str(mp4)])
        skip = row["visible"] - row["raw_start"] if (pieces or row["index"] > 1) else 0
        pieces.append((len(inputs) - 1, skip, row["frames"], False))
    graph, labels = [], []
    for k, (inp, a, b, fit) in enumerate(pieces):
        if k and crossfade and a >= crossfade:
            a -= crossfade                      # shown earlier, blended with the end of the piece before
        head = f"fps={FPS}," if fit else ""
        graph.append(f"[{inp}:v]{head}scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                     f"trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[v{k}]")
        labels.append((f"v{k}", b - a))
    if crossfade:
        current, length = labels[0]
        for k, (label, frames) in enumerate(labels[1:], start=1):
            blended = pieces[k][1] >= crossfade
            if blended:
                graph.append(f"[{current}][{label}]xfade=transition=fade:duration={crossfade / FPS:.6f}:"
                             f"offset={(length - crossfade) / FPS:.6f}[x{k}]")
                length += frames - crossfade
            else:
                graph.append(f"[{current}][{label}]concat=n=2:v=1:a=0[x{k}]")
                length += frames
            current = f"x{k}"
        video_out = current
        report.append(f"crossfades of {crossfade} frames")
    else:
        graph.append("".join(f"[{label}]" for label, _n in labels) + f"concat=n={len(labels)}:v=1:a=0[vout]")
        video_out = "vout"

    # ---- sound, at RATE, over the timeline from first_frame
    if plan["mode"] == "free":
        buffer = array.array("f", bytes(4 * 2 * _at(end_frame)))
        start_sound = None
        if start_spec:
            source = projects.safe_join(project, sv["video"])
            start_sound = _fit(_pcm(ffmpeg, source, start_spec["start_frame"] / FPS, start_spec["frames"] / FPS),
                               _at(start_spec["frames"]))
        for row, mp4 in zip(rows, files):
            begin, end = _at(row["raw_start"]), _at(row["end"])
            own = _fit(_pcm(ffmpeg, mp4), end - begin)
            if row["index"] == 1 and start_sound is not None:
                _put(buffer, 0, start_sound)
            if row["context"] and not row["continue"]:
                skip = _at(row["visible"]) - begin
                _put(buffer, begin + skip, own[2 * skip:])
            else:
                _put(buffer, begin, own)
        sound = buffer[2 * _at(first_frame):]
        edit = plan.get("edit_video")
        if edit and spec.get("edit_video"):
            edited = plan_core.edit_clip_count(plan)
            edit_end = min(plan_core.timeline(plan)[edited - 1]["end"], end_frame) if edited else 0
            if edit_end > first_frame:
                source = projects.safe_join(project, spec["edit_video"]["video"])
                original = _fit(_pcm(ffmpeg, source, (edit["start_frame"] + first_frame) / FPS, (edit_end - first_frame) / FPS),
                                _at(edit_end) - _at(first_frame))
                _put(sound, 0, original)
                report.append(f"sound: the original sound of the video '{edit['ref']}'"
                              + (f" until {edit_end / FPS:.2f} s, then the generated sound" if edited < count else ""))
        if "sound:" not in " ".join(report):
            report.append("sound: the sound of the takes")
    else:
        song = projects.safe_join(project, spec.get("song") or "")
        if not song.is_file():
            raise StudioError(_t("engine.song_not_found", v0=spec.get("song")))
        begin = (first_frame - plan_core.song_offset(plan)) / FPS
        sound = array.array("f", bytes(4 * 2 * _at(total)))
        lead = _at(-begin * FPS) if begin < 0 else 0
        _put(sound, lead, _pcm(ffmpeg, song, max(0.0, begin), total / FPS - lead / RATE))
        if start_spec and start_spec.get("song") == "after_video":
            source = projects.safe_join(project, sv["video"])
            _put(sound, 0, _fit(_pcm(ffmpeg, source, start_spec["start_frame"] / FPS, start_spec["frames"] / FPS),
                                _at(start_spec["frames"])))
        report.append("sound: the song")
    sound = _fit(sound, _at(total))

    # ---- one encoding
    target.parent.mkdir(parents=True, exist_ok=True)
    raw_audio = target.with_name(target.name + ".pcm")
    part = target.with_name(target.stem + ".part.mp4")
    raw_audio.write_bytes(sound.tobytes())
    crf = int(job.get("crf") or (spec.get("settings") or {}).get("crf") or 19)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error"]
    for item in inputs:
        cmd += item
    cmd += ["-f", "f32le", "-ar", str(RATE), "-ac", "2", "-i", str(raw_audio),
            "-filter_complex", ";".join(graph), "-map", f"[{video_out}]", "-map", f"{len(inputs)}:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(part)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                                **previews._no_window())
        if procs is not None:
            procs[job["id"]] = proc
        errors = []
        reader = threading.Thread(target=lambda: errors.extend(proc.stderr.readlines()), daemon=True)
        reader.start()
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and value.isdigit() and on_progress:
                on_progress(min(0.99, int(value) / 1e6 / max(0.001, total / FPS)))
        proc.wait()
        reader.join(timeout=5)
        if proc.returncode != 0 or not part.is_file():
            raise StudioError(_t("assembler.failed", error=("".join(errors[-6:]).strip() or f"ffmpeg {proc.returncode}")[:600]))
        os.replace(part, target)
    finally:
        if procs is not None:
            procs.pop(job["id"], None)
        for leftover in (raw_audio, part):
            try:
                leftover.unlink()
            except OSError:
                pass
    report.append(f"{total} frames ({total / FPS:.2f} s), {width}x{height}, crf {crf}")
    return "; ".join(report)


def ready_for(project: Path, job, config):
    """(ffmpeg, None) when Encore can assemble this job, else (None, why) (0.50: it is the only way)."""
    ffmpeg = previews.find_ffmpeg(config)
    if not ffmpeg:
        return None, _t("assembler.no_ffmpeg")
    if previews_of(project, job) is None:
        return None, _t("assembler.take_without_preview")
    if not re.match(r"^[0-9]+x[0-9]+$", f"{job['size'][0]}x{job['size'][1]}"):
        return None, _t("assembler.unknown_size")
    return ffmpeg, None
