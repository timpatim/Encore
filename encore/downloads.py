"""Encore - downloading the default model files into ComfyUI/models (Hugging Face).

Before a download starts: its real size is read from the Hugging Face API and compared with the free space of the
disk (with a margin, and counting the downloads already running). Files are written as <name>.part and renamed at the
end; an interrupted download resumes where it stopped.
"""
from __future__ import annotations

from .i18n import t as _t
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .projects import StudioError

DATA = Path(__file__).resolve().parent / "data"
MARGIN = 2 * 1024 ** 3          # free space kept on the disk after a download
CHUNK = 4 * 1024 * 1024


def catalog():
    path = Path(os.environ.get("ENCORE_MODELS") or DATA / "models.json")
    models = json.loads(path.read_text(encoding="utf-8")).get("models") or []
    if not os.environ.get("ENCORE_MODELS"):     # the built-in list: labels in the current language
        for model in models:
            model["label"] = _t(f"models.{model.get('id')}", default=model.get("label", ""))
    return models


def human(n):
    if n is None:
        return "?"
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if abs(n) < 1024 or unit == "To":
            return (f"{n:.1f} {unit}" if unit not in ("o", "Ko") else f"{n:.0f} {unit}").replace(".", ",")
        n /= 1024


def free_space(folder: Path):
    probe = folder
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


class Downloads:
    def __init__(self, studio):
        self.studio = studio
        self.lock = threading.Lock()
        self.jobs = {}              # id -> state
        self.trees = {}             # repo -> {basename: (path, size)}

    # ------------------------------------------------------------------ Hugging Face
    def _endpoint(self):
        return (self.studio.config.get("hf_endpoint") or "https://huggingface.co").rstrip("/")

    def _request(self, url, headers=None, method=None):
        headers = dict(headers or {})
        token = (self.studio.config.get("hf_token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("User-Agent", "Encore")
        return urllib.request.Request(url, headers=headers, method=method)

    def _tree(self, repo):
        if repo in self.trees:
            return self.trees[repo]
        url = f"{self._endpoint()}/api/models/{repo}/tree/main?recursive=1"
        try:
            with urllib.request.urlopen(self._request(url), timeout=30) as response:
                entries = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise StudioError(_t("downloads.hugging_face_refuses_access_to_protected", repo=repo)) from exc
            raise StudioError(_t("downloads.hugging_face_unreadable", repo=repo, code=exc.code)) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise StudioError(_t("downloads.hugging_face_unreachable", reason=getattr(exc, 'reason', exc))) from exc
        files = {}
        for e in entries:
            if e.get("type") == "file":
                size = (e.get("lfs") or {}).get("size") or e.get("size")
                files.setdefault(e["path"].split("/")[-1], (e["path"], size))
        self.trees[repo] = files
        return files

    def locate(self, model):
        files = self._tree(model["repo"])
        if model["file"] not in files:
            raise StudioError(_t("downloads.is_not_in_repository", v0=model['file'], v1=model['repo']))
        path, size = files[model["file"]]
        url = f"{self._endpoint()}/{model['repo']}/resolve/main/{urllib.parse.quote(path)}"
        return url, size

    # ------------------------------------------------------------------ state
    def target(self, root: Path, model):
        return root / "models" / model["folder"] / model["file"]

    def listing(self, root: Path | None, with_sizes=False):
        items = []
        for model in catalog():
            item = dict(model, present=False, path=None, size=None, partial=0, error=None)
            if root:
                dest = self.target(root, model)
                item["path"] = str(dest)
                item["present"] = dest.is_file()
                part = dest.with_name(dest.name + ".part")
                item["partial"] = part.stat().st_size if part.is_file() else 0
                item["free"] = free_space(dest.parent)
            if with_sizes and not item["present"]:
                try:
                    item["size"] = self.locate(model)[1]
                except StudioError as exc:
                    item["error"] = str(exc)
            with self.lock:
                job = self.jobs.get(model["id"])
                item["job"] = dict(job) if job else None
            items.append(item)
        return items

    def public(self):
        with self.lock:
            return {k: dict(v) for k, v in self.jobs.items()}

    # ------------------------------------------------------------------ downloading
    def start(self, root: Path | None, model_id):
        if root is None:
            raise StudioError(_t("downloads.first_give_the_comfyui_folder_installation"))
        model = next((m for m in catalog() if m["id"] == model_id), None)
        if model is None:
            raise StudioError(_t("downloads.unknown_model"))
        dest = self.target(root, model)
        if dest.is_file():
            raise StudioError(_t("downloads.is_already_there", v0=model['file']))
        with self.lock:
            job = self.jobs.get(model_id)
            if job and job["status"] in ("checking", "running"):
                raise StudioError(_t("downloads.this_download_is_already_running"))
        url, size = self.locate(model)
        part = dest.with_name(dest.name + ".part")
        have = part.stat().st_size if part.is_file() else 0
        need = (size or 0) - have
        with self.lock:
            reserved = sum(max(0, (j.get("size") or 0) - (j.get("done") or 0)) for j in self.jobs.values()
                           if j["status"] == "running" and j["id"] != model_id)
        free = free_space(dest.parent)
        if size and need + reserved + MARGIN > free:
            raise StudioError(_t("downloads.not_enough_disk_space_for_needed", v0=model['file'], v1=human(need + reserved), v2=human(MARGIN), v3=human(free), parent=dest.parent))
        state = {"id": model_id, "file": model["file"], "status": "running", "size": size, "done": have,
                 "speed": 0, "error": None, "started": time.time(), "cancel": False, "dest": str(dest)}
        with self.lock:
            self.jobs[model_id] = state
        threading.Thread(target=self._run, args=(model_id, url, dest, part), daemon=True, name=f"encore-dl-{model_id}").start()
        return self.public()

    def cancel(self, model_id):
        with self.lock:
            job = self.jobs.get(model_id)
            if job and job["status"] == "running":
                job["cancel"] = True
        return self.public()

    def _set(self, model_id, **changes):
        with self.lock:
            self.jobs[model_id].update(changes)

    def _run(self, model_id, url, dest, part):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            have = part.stat().st_size if part.is_file() else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            with urllib.request.urlopen(self._request(url, headers), timeout=60) as response:
                if have and response.status != 206:          # the server ignored the range: start again
                    have = 0
                mode = "ab" if have else "wb"
                total = self.jobs[model_id].get("size")
                if not total:
                    length = response.headers.get("Content-Length")
                    total = int(length) + have if length else None
                    self._set(model_id, size=total)
                last_t, last_n = time.time(), have
                with open(part, mode) as handle:
                    while True:
                        if self.jobs[model_id]["cancel"]:
                            self._set(model_id, status="cancelled", done=have)
                            return
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        have += len(chunk)
                        now = time.time()
                        if now - last_t >= 1:
                            self._set(model_id, done=have, speed=(have - last_n) / (now - last_t))
                            last_t, last_n = now, have
            if total and have < total:
                raise StudioError(_t("downloads.download_interrupted_of_start_it_again", v0=human(have), v1=human(total)))
            os.replace(part, dest)
            self._set(model_id, status="done", done=have, speed=0)
        except urllib.error.HTTPError as exc:
            self._set(model_id, status="error", error=f"HTTP {exc.code}" + (" : jeton Hugging Face requis" if exc.code in (401, 403) else ""))
        except Exception as exc:  # noqa: BLE001
            self._set(model_id, status="error", error=str(getattr(exc, "reason", exc)))
