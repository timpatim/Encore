"""Light copies of the project's videos that the browser can play (H.264 MP4, at most 540 pixels high, sound kept).

Browsers play only a few formats (MP4 in H.264, WebM): an AVI, a ProRes MOV or an HEVC MP4 stays grey in the
player. When the browser fails to play a video, the page asks for its preview: ffmpeg makes it once in
previews/<path of the video>.mp4, in the background, with its progress. Only the player uses it: ComfyUI always
gets the original file. A preview older than its video is made again; deleting the video deletes its preview.

ffmpeg: the H3_FFMPEG environment variable, else the one of imageio-ffmpeg in ComfyUI's Python (the one the
plugin uses), else ffmpeg on the PATH."""
from __future__ import annotations

from .i18n import t as _t
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from . import comfy_setup, projects
from .projects import StudioError

PREVIEW_DIR = "previews"
HEIGHT = 540
_lock = threading.Lock()
_jobs = {}              # (project folder, rel) -> {"state", "progress", "error", "proc"}
_ffmpeg_cache = {}


def preview_rel(rel):
    return f"{PREVIEW_DIR}/{rel}.mp4"


def find_ffmpeg(config):
    path = os.environ.get("H3_FFMPEG", "").strip()
    if path:
        return path
    root = comfy_setup.comfy_root(config.get("comfy_dir"))
    python, _kind, _note = comfy_setup.find_python(root, config.get("comfy_python") or "")
    if python not in _ffmpeg_cache:
        found = ""
        if python:
            try:
                out = subprocess.run([python, "-c", "import imageio_ffmpeg, sys; sys.stdout.write(imageio_ffmpeg.get_ffmpeg_exe())"],
                                     capture_output=True, text=True, timeout=60, **_no_window())
                if out.returncode == 0 and out.stdout.strip() and Path(out.stdout.strip()).is_file():
                    found = out.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        _ffmpeg_cache[python] = found or shutil.which("ffmpeg") or ""
    return _ffmpeg_cache[python]


def _no_window():
    return {"creationflags": 0x08000000} if os.name == "nt" else {}       # no console window on Windows


def _video(root, name, rel):
    path = projects.project_dir(root, name)
    if not rel.startswith("refs/videos/"):
        raise StudioError(_t("previews.not_a_video"))
    file = projects.safe_join(path, rel)
    if not file.is_file():
        raise StudioError(_t("server.file_not_found"))
    return path, file


def status(root, name, rel):
    path, file = _video(root, name, rel)
    return _status(path, file, rel, preview_rel(rel))


def _status(path, file, key, out_rel):
    target = projects.safe_join(path, out_rel)
    with _lock:
        job = _jobs.get((str(path), key))
        if job and job["state"] in ("running", "error"):
            return {"state": job["state"], "progress": job["progress"], "error": job.get("error"), "path": out_rel}
    if target.is_file() and target.stat().st_mtime >= file.stat().st_mtime:
        return {"state": "done", "progress": 1, "path": out_rel}
    return {"state": "none", "progress": 0, "path": out_rel}


def start(root, name, rel, config):
    path, file = _video(root, name, rel)
    return _start(path, file, rel, preview_rel(rel), config, [], f"scale=-2:'min({HEIGHT},ih)':flags=bilinear", 26)


def _start(path, file, key, out_rel, config, cut, scale, crf):
    current = _status(path, file, key, out_rel)
    if current["state"] in ("running", "done"):
        return current
    ffmpeg = find_ffmpeg(config)
    if not ffmpeg:
        raise StudioError(_t("previews.no_ffmpeg"), code="no_ffmpeg")
    target = projects.safe_join(path, out_rel)
    job = {"state": "running", "progress": 0, "error": None, "proc": None}
    with _lock:
        _jobs[(str(path), key)] = job
    threading.Thread(target=_make, args=(ffmpeg, file, target, job, cut, scale, crf), daemon=True).start()
    return {"state": "running", "progress": 0, "path": out_rel}


# ---- the thumbnail of the start video's segment (Takes tab): only the segment, small, looping
THUMB_HEIGHT = 270


def thumb_rel(rel, start_frame, end_frame):
    return f"{PREVIEW_DIR}/thumbs/{rel}_{int(start_frame)}_{int(end_frame)}.mp4"


def _thumb_args(start_frame, end_frame):
    start_frame, end_frame = int(start_frame), int(end_frame)
    if start_frame < 0 or end_frame <= start_frame:
        raise StudioError(_t("previews.bad_segment"))
    return start_frame, end_frame


def thumb_status(root, name, rel, start_frame, end_frame):
    start_frame, end_frame = _thumb_args(start_frame, end_frame)
    path, file = _video(root, name, rel)
    out = thumb_rel(rel, start_frame, end_frame)
    return _status(path, file, out, out)


def thumb_start(root, name, rel, start_frame, end_frame, config):
    start_frame, end_frame = _thumb_args(start_frame, end_frame)
    path, file = _video(root, name, rel)
    out = thumb_rel(rel, start_frame, end_frame)
    cut = ["-ss", f"{start_frame / 24:.4f}", "-t", f"{(end_frame - start_frame) / 24:.4f}"]
    return _start(path, file, out, out, config, cut, f"scale=-2:'min({THUMB_HEIGHT},ih)':flags=bilinear", 28)


# ---- changes of shot in a segment (edited video: one new scene per shot)
SCENE_THRESHOLD = 0.35


def scene_cuts(root, name, rel, start_frame, end_frame, config):
    """Frames of the file (24 fps grid) where the picture changes at once, between start_frame and end_frame."""
    start_frame, end_frame = _thumb_args(start_frame, end_frame)
    _path, file = _video(root, name, rel)
    ffmpeg = find_ffmpeg(config)
    if not ffmpeg:
        raise StudioError(_t("previews.no_ffmpeg"), code="no_ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-ss", f"{start_frame / 24:.4f}", "-t", f"{(end_frame - start_frame) / 24:.4f}",
           "-i", str(file), "-an", "-vf", f"scale=320:-2,select='gt(scene,{SCENE_THRESHOLD})',showinfo", "-f", "null", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=1800, **_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        raise StudioError(_t("previews.scenes_failed", error=str(exc)[:300])) from exc
    cuts = []
    for found in re.finditer(r"pts_time:\s*([0-9.]+)", out.stderr):
        frame = start_frame + int(round(float(found[1]) * 24))
        if start_frame < frame < end_frame and (not cuts or frame - cuts[-1] > 2):
            cuts.append(frame)
    return {"cuts": cuts}


def cancel(root, name, rel):
    path = projects.project_dir(root, name)
    with _lock:
        job = _jobs.pop((str(path), rel), None)
    if job and job["state"] == "running":
        job["state"] = "cancelled"
        if job["proc"]:
            try:
                job["proc"].kill()
            except OSError:
                pass
    return {"state": "none"}


def remove(path: Path, rel):
    """Deletes the preview of a video and its segment thumbnails (the video was deleted)."""
    try:
        projects.safe_join(path, preview_rel(rel)).unlink()
    except (OSError, StudioError):
        pass
    try:
        thumbs = projects.safe_join(path, f"{PREVIEW_DIR}/thumbs/{rel}").parent
        prefix = Path(rel).name + "_"
        for item in thumbs.iterdir() if thumbs.is_dir() else ():
            if item.name.startswith(prefix) and item.name.endswith(".mp4"):
                item.unlink()
    except (OSError, StudioError):
        pass


def _duration(ffmpeg, file):
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(file)], capture_output=True, text=True, timeout=60,
                             errors="replace", **_no_window())
    except (OSError, subprocess.SubprocessError):
        return 0
    found = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr)
    return int(found[1]) * 3600 + int(found[2]) * 60 + float(found[3]) if found else 0


def _make(ffmpeg, file, target, job, cut, scale, crf):
    part = target.with_name(target.name[:-4] + ".part.mp4")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        total = float(cut[3]) if cut else _duration(ffmpeg, file)
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error", *cut[:2], "-i", str(file), *cut[2:], "-map", "0:v:0", "-map", "0:a:0?",
               "-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", str(part)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", **_no_window())
        job["proc"] = proc
        errors = []
        reader = threading.Thread(target=lambda: errors.extend(proc.stderr.readlines()), daemon=True)
        reader.start()
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and total > 0 and value.isdigit():
                job["progress"] = max(0.0, min(0.99, int(value) / 1e6 / total))
        proc.wait()
        reader.join(timeout=5)
        if job["state"] == "cancelled":
            return
        if proc.returncode != 0 or not part.is_file():
            raise RuntimeError("".join(errors[-5:]).strip() or f"ffmpeg {proc.returncode}")
        os.replace(part, target)
        job["progress"], job["state"] = 1, "done"
    except Exception as exc:  # noqa: BLE001 - reported to the page
        if job["state"] != "cancelled":
            job["state"], job["error"] = "error", _t("previews.failed", error=str(exc)[:400])
    finally:
        try:
            part.unlink()
        except OSError:
            pass
