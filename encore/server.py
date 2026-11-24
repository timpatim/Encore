"""Encore - local web server (standard library only).

Serves the interface (web/index.html) and a small JSON API on 127.0.0.1. ComfyUI is reached
through its HTTP API at the address of the configuration.
"""
from __future__ import annotations

from . import i18n
from .i18n import t as _t
import argparse
import json
import mimetypes
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import mdpage, engine as engine_mod, comfy_setup, downloads, exports
from . import folders, plan_core, plans, previews, projects, resources, takeplan, takes, trash
from .projects import StudioError

STUDIO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = STUDIO_ROOT / "web"
CONFIG_PATH = STUDIO_ROOT / "config.json"
MAX_UPLOAD = 2 * 1024 ** 3
MAX_RESOURCE = 256 * 1024 ** 3      # imported files are written as they arrive, never held in memory
_LOCK = threading.RLock()


class ComfyWatch:
    """Checks every few seconds whether ComfyUI answers. `epoch` grows at each reconnection, so the page knows when to
    read again the lists of nodes and models (ComfyUI may have been restarted with new custom nodes)."""
    PERIOD = 3.0

    def __init__(self, studio):
        self.studio = studio
        self.state = {"ok": None, "since": time.time(), "version": None, "url": None, "error": None, "epoch": 0, "checked": 0}
        self.wake = threading.Event()
        threading.Thread(target=self._loop, daemon=True, name="encore-comfywatch").start()

    def _probe(self):
        url = self.studio.config["comfy_url"]
        try:
            with urllib.request.urlopen(url + "/system_stats", timeout=2.5) as response:
                stats = json.loads(response.read().decode("utf-8"))
            version = ((stats.get("system") or {}).get("comfyui_version")) or None
            return True, version, None, url
        except Exception as exc:  # noqa: BLE001
            return False, None, str(getattr(exc, "reason", exc)), url

    def _loop(self):
        while True:
            ok, version, error, url = self._probe()
            st = self.state
            if ok != st["ok"] or url != st["url"]:
                st.update(since=time.time())
                if ok:
                    st["epoch"] += 1
                    engine = self.studio._engine
                    if engine is not None:
                        engine.info = None          # node lists may have changed (restart)
            st.update(ok=ok, version=version, error=error, url=url, checked=time.time())
            self.wake.wait(self.PERIOD)
            self.wake.clear()

    def check_now(self):
        self.wake.set()

    def public(self):
        st = dict(self.state)
        st["for_s"] = round(time.time() - st["since"])
        return st


def migrate_from_h3studio(config_path: Path):
    """Encore was called H3 Studio: on the first start of a new Encore folder, take over the settings, defaults and
    queue of an H3 Studio folder next to it (same parent folder). Projects stay where they are."""
    if config_path.exists():
        return
    for old in ("H3Studio", "H3 Studio", "h3studio"):
        folder = config_path.resolve().parent.parent / old
        if (folder / "config.json").is_file():
            import shutil
            for name in ("config.json", "defaults.json", "queue.json"):
                if (folder / name).is_file() and not (config_path.parent / name).exists():
                    shutil.copy2(folder / name, config_path.parent / name)
            print(_t("server.settings_taken_from", folder=folder))
            return


class Studio:
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = config_path
        self.host = "127.0.0.1"         # the address Encore listens on (main() sets it)
        migrate_from_h3studio(Path(config_path))
        self.config = projects.load_config(config_path)
        i18n.set_language(self.config.get("language", "en"))
        mdpage.THEME[0] = self.config.get("theme", "dark")
        self._engine = None
        self.watch = ComfyWatch(self)
        self.installer = comfy_setup.Installer()
        self.downloads = downloads.Downloads(self)

    @property
    def engine(self):
        if self._engine is None:
            self._engine = engine_mod.Engine(self)
        return self._engine

    @property
    def root(self):
        return Path(self.config["projects_root"])

    def set_config(self, changes):
        config = dict(self.config)
        if "projects_root" in changes:
            root = Path(str(changes["projects_root"]).strip()).expanduser()
            if not str(root).strip():
                raise StudioError(_t("server.empty_projects_folder"))
            try:
                root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise StudioError(_t("server.cannot_create", root=root, exc=exc)) from exc
            config["projects_root"] = str(root)
        if "comfy_url" in changes:
            url = str(changes["comfy_url"]).strip().rstrip("/")
            if not re.match(r"^https?://", url):
                raise StudioError(_t("server.invalid_comfyui_address_http_host_port"))
            config["comfy_url"] = url
            if getattr(self, "watch", None):
                self.watch.check_now()
        if "purge_comfy_copy" in changes:
            config["purge_comfy_copy"] = bool(changes["purge_comfy_copy"])
        if "configured" in changes:
            config["configured"] = bool(changes["configured"])
        if "comfy_dir" in changes:
            value = str(changes["comfy_dir"] or "").strip().strip('"')
            if value and comfy_setup.comfy_root(value) is None:
                raise StudioError(_t("server.is_not_a_comfyui_folder_it", value=value))
            config["comfy_dir"] = value
        if "comfy_python" in changes:
            config["comfy_python"] = str(changes["comfy_python"] or "").strip().strip('"')
            config.pop("comfy_python_check", None)
        if "comfy_python_check" in changes:
            config["comfy_python_check"] = changes["comfy_python_check"]
        if "setup_done" in changes:
            config["setup_done"] = bool(changes["setup_done"])
        if "theme" in changes:
            if changes["theme"] not in ("dark", "light"):
                raise StudioError(_t("server.unknown_theme"))
            config["theme"] = mdpage.THEME[0] = changes["theme"]
        if "language" in changes:
            code = str(changes["language"] or "en")
            if code not in {x["code"] for x in i18n.languages()}:
                raise StudioError(_t("server.unknown_language", code=code))
            config["language"] = i18n.set_language(code)
        for key in ("hf_token", "hf_endpoint"):
            if key in changes:
                config[key] = str(changes[key] or "").strip()
        projects.save_config(self.config_path, config)
        self.config = config
        return self.public_config()

    @property
    def defaults_path(self):
        return Path(self.config_path).resolve().parent / "defaults.json"

    def setup_status(self):
        comfy_ok = bool(self.watch.state.get("ok"))
        info = None
        if comfy_ok:
            try:
                info = self.engine._object_info()
            except Exception:  # noqa: BLE001
                comfy_ok = False
        out = comfy_setup.status(self.config, info, comfy_ok)
        out["install"] = self.installer.public()
        out["comfy"] = self.watch.public()
        return out

    def public_config(self):
        return {**self.config, "root_exists": self.root.is_dir(), "studio_version": projects.STUDIO_VERSION,
                "language": i18n.language(), "languages": i18n.languages()}

    # ------------------------------------------------------------------ ComfyUI
    def comfy(self, path, timeout=20):
        url = self.config["comfy_url"] + path
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise StudioError(_t("server.comfyui_unreachable_at", v0=self.config['comfy_url'], v1=getattr(exc, 'reason', exc))) from exc


def make_handler(studio: Studio):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Encore/" + projects.STUDIO_VERSION

        def log_message(self, fmt, *args):  # quieter console
            line = str(args[0]) if args else ""
            if "/favicon.ico" in line:                  # asked by every browser: not an error
                return
            if not str(args[1] if len(args) > 1 else "").startswith(("2", "3")):
                sys.stderr.write("Encore: " + fmt % args + "\n")

        # ---------------------------------------------------------- responses
        def send_json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_html(self, text):
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_page(self):
            """index.html with the chosen language and the locale files put in it"""
            theme = json.dumps(studio.config.get("theme", "dark"))
            html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("<!--__I18N__-->", i18n.page_script(), 1) \
                .replace("<!--__THEME__-->", f"<script>window.H3THEME = {theme};</script>", 1)
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path: Path, cache=False):
            if not path.is_file():
                return self.send_json({"error": _t("server.file_not_found")}, 404)
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix.lower() in (".md", ".json", ".txt"):
                ctype = ("application/json" if path.suffix.lower() == ".json" else "text/plain") + "; charset=utf-8"
            start, end = 0, size - 1
            ranged = False
            header = self.headers.get("Range")
            if header and header.startswith("bytes="):
                try:
                    first, _, last = header[6:].split(",")[0].partition("-")
                    if first:
                        start = int(first)
                        end = int(last) if last else size - 1
                    else:
                        start = max(0, size - int(last))
                    end = min(end, size - 1)
                    ranged = start <= end
                except ValueError:
                    ranged = False
            self.send_response(206 if ranged else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            if ranged:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            length = end - start + 1 if ranged else size
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with open(path, "rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except ConnectionError:      # the browser stopped reading (a video often does)
                        return
                    remaining -= len(chunk)

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                raise StudioError(_t("server.file_too_big"))
            return self.rfile.read(length) if length else b""

        def json_body(self):
            raw = self.body()
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError as exc:
                raise StudioError(_t("server.invalid_json_request")) from exc

        def twig_plan(self, name, branch, leaf):
            """The plan of a twig (or the master plan of a branch), with its validation and its timeline."""
            path = projects.project_dir(studio.root, name)
            if not branch:
                meta = projects.read_meta(path)
                known = plans.records_by_id(path)
                if leaf and leaf in known:
                    branch = takes.take_branch(known[leaf][1], None)
                branch = branch or (meta["branches"][0]["id"] if meta["branches"] else None)
            twig = plans.plan_of(path, branch, leaf, pending=studio.engine._pending_takes(name), project_name=name)
            errors, warnings = plan_core.validate(json.loads(json.dumps(twig["plan"])))
            return dict(twig, branch=branch, leaf=leaf, takes={str(k): v for k, v in twig["takes"].items()},
                        validation={"errors": errors, "warnings": warnings})

        def takes_listing(self, name):
            """The takes, with the clip names of the selected twig's plan for the column headers."""
            path = projects.project_dir(studio.root, name)
            names, selected = {}, None
            try:
                selected = projects.selected_plan(path)
                names = {i: c.get("name") for i, c in enumerate((selected["plan"] or {}).get("clips") or [], start=1)}
            except (StudioError, OSError, ValueError):
                pass
            out = takes.listing(path, names)
            out["twig"] = selected
            out["fits"] = plans.fits_map(path)
            return out

        # ---------------------------------------------------------- routing
        def _refused(self, method):
            """Another web page must not drive Encore: a page of another site can send a POST to 127.0.0.1 (CSRF),
            and a site whose name points to 127.0.0.1 can read the answers (DNS rebinding). Returns the reason or
            None."""
            host = (self.headers.get("Host") or "").strip().lower()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            exposed = studio.host not in ("127.0.0.1", "localhost", "::1")
            if not exposed and name not in ("127.0.0.1", "localhost", "[::1]"):
                return "host"
            origin = self.headers.get("Origin")
            if origin and origin != "null" and urllib.parse.urlparse(origin).netloc.lower() != host:
                return "origin"
            if method != "GET" and self.headers.get("X-Encore") != "1":
                return "header"          # a custom header: a page of another site cannot send it without CORS
            return None

        def handle_any(self, method):
            why = self._refused(method)
            if why:
                sys.stderr.write(_t("server.request_refused", why=why, path=self.path) + "\n")
                return self._answer_error({"error": _t("server.request_refused", why=why, path=self.path)}, 403)
            url = urllib.parse.urlparse(self.path)
            parts = [urllib.parse.unquote(p) for p in url.path.split("/") if p]
            query = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
            try:
                with _LOCK if method != "GET" else _NoLock():
                    return self.route(method, parts, query)
            except ConnectionError:
                return None                     # the browser closed the connection: nothing to answer
            except StudioError as exc:
                return self._answer_error({"error": str(exc), **({"code": exc.code} if exc.code else {})}, 400)
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(_t("server.encore_internal_error", v0=f"{exc!r}"))
                return self._answer_error({"error": _t("server.internal_error", exc=exc)}, 500)

        def _answer_error(self, data, status):
            try:
                self.send_json(data, status)
            except ConnectionError:
                pass

        def handle(self):
            try:
                super().handle()
            except ConnectionError:
                pass

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

        def do_PUT(self):
            self.handle_any("PUT")

        def do_DELETE(self):
            self.handle_any("DELETE")

        def route(self, method, parts, query):
            root = studio.root
            if method == "GET" and (not parts or parts == ["index.html"]):
                return self.send_page()
            if parts[:1] == ["files"] and method == "GET" and len(parts) >= 3:
                path = projects.project_dir(root, parts[1])
                return self.send_file(projects.safe_join(path, "/".join(parts[2:])))
            if parts[:1] != ["api"]:
                return self.send_json({"error": _t("server.not_found")}, 404)
            api = parts[1:]
            if api == ["ping"]:
                return self.send_json({"app": "encore", "version": projects.STUDIO_VERSION})
            if api == ["queue"] and method == "GET":
                return self.send_json(dict(studio.engine.queue_state(), comfy=studio.watch.public()))
            if api == ["setup"] and method == "GET":
                return self.send_json(studio.setup_status())
            if api == ["setup", "config"] and method == "PUT":
                body = self.json_body() or {}
                studio.set_config({k: body[k] for k in ("comfy_dir", "comfy_python") if k in body})
                if body.get("check_python"):
                    root = comfy_setup.comfy_root(studio.config.get("comfy_dir"))
                    exe, _kind, note = comfy_setup.find_python(root, studio.config.get("comfy_python") or "")
                    ok, text = comfy_setup.check_python(exe) if exe else (False, note or _t("server.comfyui_s_python_unknown"))
                    studio.set_config({"comfy_python_check": {"python": exe, "ok": ok, "text": text}})
                return self.send_json(studio.setup_status())
            if api == ["setup", "install"] and method == "POST":
                body = self.json_body() or {}
                root = comfy_setup.comfy_root(studio.config.get("comfy_dir"))
                if root is None:
                    raise StudioError(_t("server.first_give_the_comfyui_folder"))
                exe, _kind, note = comfy_setup.find_python(root, studio.config.get("comfy_python") or "")
                if not exe:
                    raise StudioError(note or _t("server.comfyui_s_python_unknown"))
                studio.installer.start(root, exe, comfy_setup.find_git(), body.get("packs") or [])
                return self.send_json(studio.setup_status())
            if api == ["setup", "done"] and method == "POST":
                st = studio.setup_status()
                if not st["required_ok"]:
                    raise StudioError(_t("server.the_required_custom_nodes_are_not"))
                studio.set_config({"setup_done": True})
                return self.send_json(studio.setup_status())
            if api == ["models"] and method == "GET":
                root = comfy_setup.comfy_root(studio.config.get("comfy_dir"))
                return self.send_json({"comfy_root": str(root) if root else None,
                                       "items": studio.downloads.listing(root, with_sizes=query.get("sizes") == "1")})
            if api == ["models", "download"] and method == "POST":
                body = self.json_body() or {}
                root = comfy_setup.comfy_root(studio.config.get("comfy_dir"))
                return self.send_json({"jobs": studio.downloads.start(root, str(body.get("id") or ""))})
            if api == ["models", "cancel"] and method == "POST":
                body = self.json_body() or {}
                return self.send_json({"jobs": studio.downloads.cancel(str(body.get("id") or ""))})
            if api == ["comfy", "status"] and method == "GET":
                return self.send_json(studio.watch.public())
            if api == ["comfy", "check"] and method == "POST":
                studio.watch.check_now()
                time.sleep(0.8)
                return self.send_json(studio.watch.public())
            if api[:1] == ["queue"] and len(api) == 2 and method == "POST":
                body = self.json_body() or {}
                action = api[1]
                if action == "pause":
                    return self.send_json(studio.engine.queue_pause("now" if body.get("mode") == "now" else "after"))
                if action == "resume":
                    return self.send_json(studio.engine.queue_resume())
                if action == "move":
                    return self.send_json(studio.engine.queue_move(body.get("group"), body.get("before")))
                if action == "suspend":
                    return self.send_json(studio.engine.queue_suspend(body.get("group"), bool(body.get("suspended", True))))
                if action == "cancel":
                    return self.send_json(studio.engine.queue_cancel(list(body.get("ids") or [])))
                raise StudioError(_t("server.unknown_queue_action"))
            if api == ["config"]:
                if method == "GET":
                    return self.send_json(studio.public_config())
                return self.send_json(studio.set_config(self.json_body()))
            if api == ["dirs"]:
                if method == "GET":
                    return self.send_json(folders.list_dirs(query.get("path", "")))
                body = self.json_body()
                return self.send_json(folders.make_dir(body.get("path", ""), body.get("name", "")))
            if api == ["defaults"]:
                if method == "GET":
                    return self.send_json(projects.load_defaults(studio.defaults_path))
                if method == "PUT":
                    return self.send_json(projects.save_defaults(studio.defaults_path, self.json_body()))
            if api == ["comfy", "ping"]:
                try:
                    stats = studio.comfy("/system_stats", timeout=5)
                    return self.send_json({"ok": True, "system": stats.get("system", {}), "devices": stats.get("devices", [])})
                except StudioError as exc:
                    return self.send_json({"ok": False, "error": str(exc)})
            if api == ["comfy", "object_info"]:
                return self.send_json(studio.comfy("/object_info", timeout=60))
            if api == ["projects"]:
                if method == "GET":
                    return self.send_json({"root": str(root), "projects": projects.list_projects(root)})
                body = self.json_body()
                root.mkdir(parents=True, exist_ok=True)
                return self.send_json(projects.create_project(root, body.get("name"), body.get("mode", "free"),
                                                              projects.load_defaults(studio.defaults_path)))
            if len(api) >= 2 and api[0] == "projects":
                name = api[1]
                rest = api[2:]
                if not rest and method == "GET":
                    return self.send_json(projects.read_project(root, name))
                if rest == ["plan"] and method == "GET":
                    # the plan of a twig (leaf = its last take) or the master plan of a branch (no leaf)
                    return self.send_json(self.twig_plan(name, query.get("branch"), query.get("leaf") or None))
                if rest == ["plan"] and method == "PUT":
                    body = self.json_body() or {}
                    branch = body.get("branch") or query.get("branch")
                    leaf = body.get("leaf", query.get("leaf")) or None
                    plan = body.get("plan") if isinstance(body.get("plan"), dict) else body
                    if not branch:          # no target: the plan of the selection (what GET /projects/<name> gives)
                        selected = projects.selected_plan(projects.project_dir(root, name))
                        branch, leaf = selected["branch"], selected["leaf"]
                    if not branch:
                        raise StudioError(_t("server.plan_branch_missing"))
                    out = projects.save_plan(root, name, plan, branch, leaf)
                    return self.send_json(dict(out, **self.twig_plan(name, branch, leaf)))
                if rest == ["settings"] and method == "PUT":
                    return self.send_json(projects.save_settings(root, name, self.json_body()))
                if rest == ["import-plan"] and method == "POST":
                    data = self.body()
                    filename = query.get("filename", "plan.json")
                    out = projects.import_plan(root, name, data, filename, query.get("branch") or None)
                    out["project"] = projects.read_project(root, name)
                    return self.send_json(out)
                if rest == ["takes"] and method == "GET":
                    path = projects.project_dir(root, name)
                    return self.send_json(self.takes_listing(name))
                if len(rest) == 3 and rest[0] == "jobs" and rest[2] == "plan" and method == "GET":
                    return self.send_json(studio.engine.job_plan(name, rest[1]))
                if len(rest) == 4 and rest[0] == "takes" and rest[3] == "plan" and method == "GET" and rest[1].isdigit():
                    return self.send_json(takeplan.take_plan(root, name, int(rest[1]), rest[2]))
                if rest == ["selection"] and method == "PUT":
                    path = projects.project_dir(root, name)
                    takes.save_selection(path, None, (self.json_body() or {}).get("selection") or {}, fits=plans.fits_map(path),
                                         pending=studio.engine._pending_takes(name))
                    return self.send_json(self.takes_listing(name))
                if rest == ["generate"] and method == "POST":
                    body = self.json_body() or {}
                    return self.send_json(studio.engine.generate(
                        name, body.get("clip"), after=body.get("after"), plan_from=body.get("plan_from"), entry=body.get("entry"),
                        seed=body.get("seed"), branch=body.get("branch"), loras=body.get("loras"),
                        upscale_settings=body.get("upscale_settings"), edit_instruction=body.get("edit_instruction")))
                if len(rest) == 3 and rest[0] == "branches" and rest[2] == "fill" and method == "POST":
                    body = self.json_body() or {}
                    return self.send_json(studio.engine.fill_twig(name, rest[1], leaf=body.get("leaf") or None,
                                                                  dry_run=bool(body.get("dry_run", True)),
                                                                  assemble=bool(body.get("assemble", True))))
                if rest == ["branches"] and method == "POST":
                    # « + nouvelle branche »: empty, from a plan file (?how=file&filename=…, the file as body), or a
                    # duplicate of a branch, with or without the clips of a twig ({how: copy|clips, source, leaf, upto})
                    if query.get("how") == "file":
                        out = projects.new_branch(root, name, "file", data=self.body(), filename=query.get("filename", "plan.json"),
                                                  label=query.get("name"))
                    else:
                        body = self.json_body() or {}
                        out = projects.new_branch(root, name, body.get("how") or "empty", source=body.get("source"),
                                                  leaf=body.get("leaf"), upto=body.get("upto"), label=body.get("name"))
                    out["project"] = projects.read_project(root, name)
                    return self.send_json(out)
                if len(rest) == 2 and rest[0] == "branches" and method == "PUT":
                    body = self.json_body() or {}
                    if any(k in body for k in ("refs", "song", "width", "height", "ref_image_size")):
                        meta = projects.read_meta(projects.project_dir(root, name))
                        branch = projects.find_branch(meta["branches"], rest[1])
                        default = meta["branches"][0]["id"]
                        changed = ("refs" in body and body["refs"] != branch.get("refs")) or ("song" in body and (body["song"] or "") != (branch.get("song") or "")) \
                            or any(k in body and int(body[k]) != int(branch.get(k) or 0) for k in ("width", "height")) \
                            or ("ref_image_size" in body and body["ref_image_size"] != branch.get("ref_image_size"))
                        if changed and studio.engine.active_in_branch(name, rest[1], default):
                            raise StudioError(_t("server.generations_of_this_branch_are_waiting"))
                    return self.send_json(projects.update_branch(root, name, rest[1], body))
                if len(rest) == 2 and rest[0] == "branches" and method == "DELETE":
                    meta = projects.read_meta(projects.project_dir(root, name))
                    projects.find_branch(meta["branches"], rest[1])
                    if studio.engine.active_in_branch(name, rest[1], meta["branches"][0]["id"]):
                        raise StudioError(_t("server.generations_or_an_assembly_of_this"))
                    return self.send_json(projects.delete_branch(root, name, rest[1], query.get("confirm") == "1"))
                if rest == ["infos"] and method == "GET":
                    rel = query.get("file", "")
                    if not rel.startswith("exports/") or not rel.endswith(".infos.md"):
                        raise StudioError(_t("server.invalid_info_sheet"))
                    file = projects.safe_join(projects.project_dir(root, name), rel)
                    if not file.is_file():
                        return self.send_json({"error": _t("server.info_sheet_not_found")}, 404)
                    base = f"/files/{name}/"
                    json_rel = rel[:-3] + ".json"
                    color = None
                    try:            # the colour of the video's branch, as in the Prises tab
                        info = json.loads(projects.safe_join(projects.project_dir(root, name), json_rel).read_text(encoding="utf-8"))
                        bid = (info.get("branch") or info.get("branche") or {}).get("id")      # "branche": before 0.25
                        color = next((b.get("color") for b in projects.read_meta(projects.project_dir(root, name))["branches"] if b["id"] == bid), None)
                    except (OSError, ValueError, StudioError):
                        pass
                    body = mdpage.page(file.read_text(encoding="utf-8"), file.name[:-9],
                                       source_url=base + rel + "?t=1",
                                       json_url=base + json_rel + "?t=1" if projects.safe_join(projects.project_dir(root, name), json_rel).is_file() else None,
                                       color=color)
                    return self.send_html(body)
                if rest == ["assemble"] and method == "POST":
                    body = self.json_body() or {}
                    if body.get("job"):
                        return self.send_json(studio.engine.assemble(name, None, None, job_id=body["job"]))
                    if not body.get("clip") or not body.get("take"):
                        raise StudioError(_t("server.assembly_give_the_last_take_of"))
                    return self.send_json(studio.engine.assemble(name, body["clip"], body["take"]))
                if rest == ["exports"] and method == "GET":
                    return self.send_json({"exports": exports.list_exports(projects.project_dir(root, name))})
                if rest == ["jobs"] and method == "GET":
                    projects.project_dir(root, name)
                    return self.send_json(studio.engine.list_jobs(name))
                if len(rest) == 3 and rest[0] == "jobs" and rest[2] == "preview" and method == "GET":
                    preview = studio.engine.preview(name, rest[1])
                    if not preview:
                        return self.send_json({"error": _t("server.no_preview")}, 404)
                    data, mime = preview
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "max-age=60")   # each version has its own address (?s=)
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                if rest == ["cancel"] and method == "POST":
                    return self.send_json(studio.engine.cancel(name, (self.json_body() or {}).get("ids") or []))
                if rest == ["remove-job"] and method == "POST":
                    return self.send_json(studio.engine.remove(name, (self.json_body() or {}).get("id")))
                # chantier A, A3: deleting a take (with the takes made after it) and the trash
                if rest == ["takes", "delete"] and method == "POST":
                    body = self.json_body() or {}
                    busy = set()
                    for j in studio.engine.active(name):
                        busy.update(x for x in (j.get("take_id"), (j.get("studio") or {}).get("predecessor")) if x)
                    out = trash.delete_take(root, name, str(body.get("take") or ""), bool(body.get("confirm")), busy)
                    if out.get("deleted"):
                        out["project"] = projects.read_project(root, name)
                    return self.send_json(out)
                if rest == ["use-plan"] and method == "POST":
                    body = self.json_body() or {}
                    return self.send_json(projects.use_twig_plan(root, name, body.get("branch"), body.get("leaf"), body.get("target") or "master",
                                                                 body.get("name"), pending=studio.engine._pending_takes(name)))
                if rest == ["trash"] and method == "GET":
                    return self.send_json(trash.listing(root, name))
                if rest == ["trash"] and method == "DELETE":
                    return self.send_json(trash.erase(root, name))
                if len(rest) == 3 and rest[0] == "trash" and rest[2] == "restore" and method == "POST":
                    return self.send_json(trash.restore(root, name, rest[1]))
                if len(rest) == 2 and rest[0] == "trash" and method == "DELETE":
                    return self.send_json(trash.erase(root, name, rest[1]))
                if rest == ["essence"] and method == "PUT":
                    if studio.engine.active(name):
                        raise StudioError(_t("server.generations_of_this_branch_are_waiting"))
                    return self.send_json(projects.set_essence(root, name, self.json_body() or {}))
                if rest == ["start-video"] and method == "PUT":
                    return self.send_json(projects.set_start_video_file(root, name, (self.json_body() or {}).get("file")))
                if rest == ["resources", "preview"]:
                    rel = query.get("path", "")
                    if method == "GET":
                        return self.send_json(previews.status(root, name, rel))
                    if method == "POST":
                        return self.send_json(previews.start(root, name, rel, studio.config))
                    if method == "DELETE":
                        return self.send_json(previews.cancel(root, name, rel))
                if rest == ["resources", "scenes"] and method == "GET":    # changes of shot in a segment
                    return self.send_json(previews.scene_cuts(root, name, query.get("path", ""), int(query.get("start") or 0),
                                                              int(query.get("end") or 0), studio.config))
                if rest == ["resources", "thumb"]:      # the start video's segment, small (Takes tab)
                    rel, first, last = query.get("path", ""), int(query.get("start") or 0), int(query.get("end") or 0)
                    if method == "GET":
                        return self.send_json(previews.thumb_status(root, name, rel, first, last))
                    if method == "POST":
                        return self.send_json(previews.thumb_start(root, name, rel, first, last, studio.config))
                if rest == ["resources", "usage"] and method == "GET":
                    return self.send_json(resources.usage(root, name, query.get("path", "")))
                if rest == ["resources"] and method == "DELETE":
                    out = resources.delete(root, name, query.get("path", ""), confirm=query.get("confirm") == "1",
                                           comfy_dir=studio.config.get("comfy_dir"))
                    if out.get("sha"):        # sent again if it is ever imported back
                        studio.engine.uploaded = {k: v for k, v in studio.engine.uploaded.items() if v != out["sha"]}
                    return self.send_json(out)
                if rest == ["resources"]:
                    if method == "GET":
                        return self.send_json(projects.list_resources(root, name))
                    if method == "POST":
                        length = int(self.headers.get("Content-Length") or 0)
                        if length > MAX_RESOURCE:
                            raise StudioError(_t("server.file_too_big"))
                        return self.send_json(projects.add_resource_stream(root, name, query.get("kind", ""), query.get("filename", ""),
                                                                           self.rfile, length))
            return self.send_json({"error": _t("server.not_found")}, 404)

    return Handler


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Encore")
    parser.add_argument("--port", type=int, default=8190)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args(argv)
    studio = Studio(Path(args.config))
    studio.host = args.host
    server = ThreadingHTTPServer((args.host, args.port), make_handler(studio))
    url = f"http://{args.host}:{args.port}/"
    print(f"Encore {projects.STUDIO_VERSION} : {url}")
    print(_t("server.projects_folder", root=studio.root))
    print(f"  ComfyUI : {studio.config['comfy_url']}")
    print(_t("server.ctrl_c_to_stop"))
    try:
        studio.engine           # the queue left at the last run starts again
    except Exception as exc:  # noqa: BLE001
        print(_t("server.generation_queue_not_reloaded", exc=exc))
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(_t("server.encore_stopped"))


if __name__ == "__main__":
    main()
