"""Encore - installing what ComfyUI needs: custom nodes (git clone + pip, without ComfyUI-Manager).

The user gives ComfyUI's folder once. Encore finds the Python ComfyUI runs with (portable build, venv, desktop app,
or a path given by hand), clones the missing packs into custom_nodes and installs their requirements with that
Python. ComfyUI must then be restarted: the packs count as installed only when their nodes appear in /object_info.
"""
from __future__ import annotations

from .i18n import t as _t
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .projects import StudioError

DATA = Path(__file__).resolve().parent / "data"
IS_WIN = os.name == "nt"


def catalog():
    path = Path(os.environ.get("ENCORE_NODE_PACKS") or DATA / "node_packs.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    packs = data.get("packs") or []
    for pack in packs if not os.environ.get("ENCORE_NODE_PACKS") else []:    # built-in list: in the current language
        pack["why"] = _t(f"packs.{pack.get('id')}.why", default=pack.get("why", ""))
    return data.get("core_nodes") or [], packs


# --------------------------------------------------------------------------- ComfyUI's folder and Python
def comfy_root(path) -> Path | None:
    """The folder that holds custom_nodes and models: the one given, or its ComfyUI sub-folder (portable build)."""
    if not path:
        return None
    base = Path(str(path).strip().strip('"')).expanduser()
    for candidate in (base, base / "ComfyUI"):
        if (candidate / "custom_nodes").is_dir() and (candidate / "models").is_dir():
            return candidate.resolve()
    return None


def _python_names():
    return ("python.exe",) if IS_WIN else ("python3", "python")


def python_candidates(root: Path):
    """Where ComfyUI's Python usually is, most specific first: (path, kind)."""
    out = []
    for folder, kind in ((root.parent / "python_embeded", "portable"), (root / "python_embeded", "portable"),
                         (root / ".venv", "venv"), (root / "venv", "venv"), (root.parent / ".venv", "venv"),
                         (root.parent / "venv", "venv")):
        for sub in (("",) if kind == "portable" else (("Scripts",) if IS_WIN else ("bin",))):
            for name in _python_names():
                exe = folder / sub / name if sub else folder / name
                if exe.is_file():
                    out.append((exe, kind))
    return out


def find_python(root: Path | None, override: str = ""):
    """(path, kind, note). kind: given / portable / venv / none."""
    if override:
        exe = Path(override.strip().strip('"')).expanduser()
        if exe.is_dir():
            for name in _python_names():
                if (exe / name).is_file():
                    exe = exe / name
                    break
        if exe.is_file():
            return str(exe), "given", ""
        return "", "none", _t("comfy_setup.the_given_python_cannot_be_found", override=override)
    if root is None:
        return "", "none", ""
    found = python_candidates(root)
    if found:
        exe, kind = found[0]
        return str(exe), kind, ""
    return "", "none", (_t("comfy_setup.comfyui_s_python_not_found_next"))


def check_python(exe: str):
    """Runs the Python once: is torch there (i.e. is this ComfyUI's environment)? -> (ok, text)."""
    try:
        out = subprocess.run([exe, "-c", "import sys; import torch; print(sys.version.split()[0], torch.__version__)"],
                             capture_output=True, text=True, timeout=180, **_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        return False, _t("comfy_setup.cannot_run", exe=exe, exc=exc)
    if out.returncode != 0:
        tail = (out.stderr or out.stdout).strip().splitlines()[-1:] or ["?"]
        return False, _t("comfy_setup.this_python_has_no_torch_it", v0=tail[0])
    version, torch_version = (out.stdout.split() + ["?", "?"])[:2]
    return True, f"Python {version}, torch {torch_version}"


def find_git():
    exe = shutil.which("git")
    if exe:
        return exe
    if IS_WIN:
        for guess in (r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files (x86)\Git\cmd\git.exe",
                      os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe")):
            if Path(guess).is_file():
                return guess
    return ""


def _no_window():
    return {"creationflags": 0x08000000} if IS_WIN else {}       # CREATE_NO_WINDOW: no console popping up


# --------------------------------------------------------------------------- what is installed
def _repo_key(url: str) -> str:
    """owner/name of a git URL, lowercase, without .git"""
    tail = url.rstrip("/").lower()
    tail = tail[:-4] if tail.endswith(".git") else tail
    return "/".join(tail.replace(":", "/").split("/")[-2:])


def find_pack_folder(root: Path, pack) -> Path | None:
    nodes_dir = root / "custom_nodes"
    if not nodes_dir.is_dir():
        return None
    wanted, key = pack["folder"].lower(), _repo_key(pack["url"])
    name_only = key.split("/")[-1]
    for child in nodes_dir.iterdir():
        if not child.is_dir():
            continue
        low = child.name.lower()
        if low.endswith(".disabled"):
            continue
        if low in (wanted, name_only):
            return child
        git_config = child / ".git" / "config"
        if git_config.is_file():
            try:
                if key in git_config.read_text(encoding="utf-8", errors="replace").lower():
                    return child
            except OSError:
                pass
    return None


def pack_states(root: Path | None, info: dict | None):
    """One line per pack: loaded (nodes in ComfyUI) / installed (folder there, nodes not loaded: restart or broken)
    / missing / unknown (no ComfyUI folder and ComfyUI does not answer)."""
    _core, packs = catalog()
    out = []
    for pack in packs:
        folder = find_pack_folder(root, pack) if root else None
        loaded = info is not None and all(n in info for n in pack["nodes"])
        if loaded:
            state = "loaded"
        elif folder is not None:
            state = "installed"
        elif root is None and info is None:
            state = "unknown"
        else:
            state = "missing"
        note = ""
        if pack["id"] == "h3clipplan" and loaded:
            clip = info.get("H3PlanClip") or {}
            if "take_token" not in ((clip.get("input") or {}).get("optional") or {}):
                state, note = "outdated", _t("comfy_setup.version_too_old_update_the_folder")
        if state == "installed" and info is not None:
            note = _t("comfy_setup.folder_present_but_nodes_not_loaded")
        out.append({**{k: pack[k] for k in ("id", "name", "url", "required", "why", "nodes")},
                    "state": state, "folder": str(folder) if folder else None, "note": note})
    return out


# --------------------------------------------------------------------------- installing
class Installer:
    """One installation at a time, in a thread; the page reads `state`."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False, "items": [], "log": [], "finished": None, "error": None}

    def public(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def _log(self, line):
        with self.lock:
            self.state["log"].append(line.rstrip())
            del self.state["log"][:-400]

    def _item(self, pid, **changes):
        with self.lock:
            for it in self.state["items"]:
                if it["id"] == pid:
                    it.update(changes)

    def start(self, root: Path, python: str, git: str, ids):
        _core, packs = catalog()
        chosen = [p for p in packs if p["id"] in set(ids)]
        if not chosen:
            raise StudioError(_t("comfy_setup.nothing_to_install"))
        if not git:
            raise StudioError(_t("comfy_setup.git_cannot_be_found_on_this"))
        if not python:
            raise StudioError(_t("comfy_setup.comfyui_s_python_unknown_give_it"))
        with self.lock:
            if self.state["running"]:
                raise StudioError(_t("comfy_setup.an_installation_is_already_running"))
            self.state = {"running": True, "finished": None, "error": None, "log": [],
                          "items": [{"id": p["id"], "name": p["name"], "status": "waiting", "error": None} for p in chosen]}
        threading.Thread(target=self._run, args=(root, python, git, chosen), daemon=True, name="encore-install").start()
        return self.public()

    def _stream(self, cmd, cwd=None):
        self._log("$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", **_no_window())
        for line in proc.stdout:
            if line.strip():
                self._log(line)
        return proc.wait()

    def _run(self, root, python, git, packs):
        failed = 0
        embedded = "python_embeded" in python.replace("\\", "/").lower()
        for pack in packs:
            pid = pack["id"]
            try:
                folder = find_pack_folder(root, pack)
                if folder is None:
                    self._item(pid, status="cloning")
                    folder = root / "custom_nodes" / pack["folder"]
                    code = self._stream([git, "clone", "--depth", "1", pack["url"], str(folder)])
                    if code != 0:
                        raise RuntimeError(_t("comfy_setup.git_clone_failed_code", code=code))
                requirements = folder / "requirements.txt"
                if requirements.is_file() and any(l.strip() and not l.strip().startswith("#")
                                                  for l in requirements.read_text(encoding="utf-8", errors="replace").splitlines()):
                    self._item(pid, status="pip")
                    cmd = [python] + (["-s"] if embedded else []) + ["-m", "pip", "install", "-r", str(requirements)]
                    code = self._stream(cmd, cwd=str(folder))
                    if code != 0:
                        raise RuntimeError(_t("comfy_setup.pip_install_failed_code", code=code))
                self._item(pid, status="done")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self._item(pid, status="error", error=str(exc))
                self._log(_t("comfy_setup.error", v0=pack['name'], exc=exc))
        with self.lock:
            self.state.update(running=False, finished=time.time(),
                              error=_t("comfy_setup.pack_s_failed", failed=failed) if failed else None)


def status(config, info, comfy_ok):
    """Everything the installation screen shows, and whether Encore can be used."""
    core, _packs = catalog()
    root = comfy_root(config.get("comfy_dir"))
    python, kind, note = find_python(root, config.get("comfy_python") or "")
    packs = pack_states(root, info if comfy_ok else None)
    core_missing = [n for n in core if info is not None and comfy_ok and n not in info]
    required_ok = bool(comfy_ok) and not core_missing and all(
        p["state"] == "loaded" for p in packs if p["required"])
    return {"comfy_dir": config.get("comfy_dir") or "", "comfy_root": str(root) if root else None,
            "comfy_dir_ok": root is not None, "python": python, "python_kind": kind, "python_note": note,
            "python_check": config.get("comfy_python_check"), "git": find_git(), "packs": packs,
            "core_missing": core_missing, "comfy_ok": bool(comfy_ok), "required_ok": required_ok,
            "setup_done": bool(config.get("setup_done")), "platform": sys.platform}
