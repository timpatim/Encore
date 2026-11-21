"""Encore - talking to ComfyUI (standard library only).

* ComfyClient: the HTTP API (/prompt, /queue, /history, /interrupt, /upload/image, /view, ...).
* EventSocket: ComfyUI's websocket (/ws), read in a background thread, for the progress of the
  generations. A minimal client: text frames, ping/pong, close; binary frames (previews) ignored.
"""
from __future__ import annotations

from .i18n import t as _t
import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ComfyError(Exception):
    """ComfyUI refused a request or could not be reached. ``data`` holds its JSON answer, if any."""

    def __init__(self, message, data=None, status=None, unreachable=False):
        super().__init__(message)
        self.data = data
        self.status = status
        self.unreachable = unreachable          # no answer at all (not a refusal): worth trying again later


def describe_prompt_error(data) -> str:
    """Readable text for the answer of a refused /prompt."""
    if not isinstance(data, dict):
        return str(data)
    lines = []
    error = data.get("error")
    if isinstance(error, dict):
        lines.append(f"{error.get('message', '')} {error.get('details', '')}".strip())
    elif error:
        lines.append(str(error))
    for node_id, info in (data.get("node_errors") or {}).items():
        for err in info.get("errors") or []:
            text = err.get("message", "")
            if err.get("details"):
                text += f" — {err['details']}"
            lines.append(f"{info.get('class_type', '?')} ({node_id}) : {text}")
    return "\n".join(line for line in lines if line) or _t("comfy.request_refused_by_comfyui")


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ plumbing
    def _open(self, path, data=None, headers=None, method=None, timeout=None):
        request = urllib.request.Request(self.base + path, data=data, headers=headers or {}, method=method)
        try:
            return urllib.request.urlopen(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                payload = body.decode("utf-8", "replace")[:500]
            message = describe_prompt_error(payload) if isinstance(payload, dict) else str(payload)
            raise ComfyError(_t("comfy.comfyui_answered_to", code=exc.code, path=path, message=message), payload, exc.code) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ComfyError(_t("comfy.comfyui_unreachable_at", base=self.base, v1=getattr(exc, 'reason', exc)), unreachable=True) from exc

    def get(self, path, timeout=None):
        with self._open(path, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None

    def post(self, path, body, timeout=None):
        data = json.dumps(body).encode("utf-8")
        with self._open(path, data=data, headers={"Content-Type": "application/json"}, method="POST", timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None

    # ------------------------------------------------------------------ API
    def system_stats(self):
        return self.get("/system_stats", timeout=5)

    def object_info(self):
        return self.get("/object_info", timeout=60)

    def queue_prompt(self, prompt, client_id, extra):
        return self.post("/prompt", {"prompt": prompt, "client_id": client_id, "extra_data": {"h3studio": extra}})

    def queue_state(self):
        return self.get("/queue", timeout=10)

    def history(self, prompt_id):
        return self.get(f"/history/{urllib.parse.quote(prompt_id)}", timeout=10) or {}

    def interrupt(self, prompt_id=None):
        """Recent ComfyUI versions only interrupt `prompt_id` if it is the one running (older ones ignore it)."""
        return self.post("/interrupt", {"prompt_id": prompt_id} if prompt_id else {})

    def delete_queued(self, ids):
        return self.post("/queue", {"delete": list(ids)})

    def upload(self, data: bytes, filename: str, subfolder: str = "", kind: str = "input"):
        """Send a file with ComfyUI's upload route; returns its path as ComfyUI names it."""
        boundary = "----h3studio" + uuid.uuid4().hex
        parts = []
        for name, value in (("subfolder", subfolder), ("type", kind), ("overwrite", "true")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
        safe = filename.replace('"', "_")
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{safe}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8") + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))}
        with self._open("/upload/image", data=body, headers=headers, method="POST", timeout=max(self.timeout, 120)) as response:
            answer = json.loads(response.read().decode("utf-8"))
        sub = answer.get("subfolder") or ""
        return f"{sub}/{answer['name']}" if sub else answer["name"]

    def download(self, filename: str, subfolder: str, target: str, kind: str = "output"):
        """Copy a file of ComfyUI's output (or input) folder to ``target`` (written atomically)."""
        query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": kind})
        tmp = target + ".part"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with self._open(f"/view?{query}", timeout=max(self.timeout, 120)) as response, open(tmp, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        os.replace(tmp, target)
        return target

    # plugin routes (ComfyUI-H3-ClipPlan)
    def takes(self, plan_file):
        return self.get(f"/h3clipplan/takes?plan={urllib.parse.quote(plan_file)}")

    def save_selection(self, plan_file, selection):
        return self.post("/h3clipplan/selection", {"plan": plan_file, "selection": {str(k): v for k, v in selection.items()}})

    def delete_takes(self, plan_file, items):
        return self.post("/h3clipplan/delete_takes", {"plan": plan_file, "takes": items})


# --------------------------------------------------------------------------- websocket
class EventSocket(threading.Thread):
    """Reads ComfyUI's /ws and hands every JSON message to ``on_message``; reconnects by itself."""

    def __init__(self, base_url: str, client_id: str, on_message, on_state=None, on_binary=None):
        super().__init__(daemon=True, name="encore-ws")
        self.base = base_url.rstrip("/")
        self.client_id = client_id
        self.on_message = on_message
        self.on_state = on_state or (lambda connected: None)
        self.on_binary = on_binary or (lambda payload: None)
        self.connected = False
        self._stop = threading.Event()
        self._sock = None

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass

    def run(self):
        while not self._stop.is_set():
            try:
                self._session()
            except Exception:  # noqa: BLE001 - any failure: reconnect later
                pass
            if self.connected:
                self.connected = False
                self.on_state(False)
            self._stop.wait(2.0)

    # one connection, until it closes
    def _session(self):
        url = urllib.parse.urlparse(self.base)
        secure = url.scheme == "https"
        host = url.hostname or "127.0.0.1"
        port = url.port or (443 if secure else 80)
        path = (url.path.rstrip("/") or "") + f"/ws?clientId={urllib.parse.quote(self.client_id)}"
        sock = socket.create_connection((host, port), timeout=10)
        if secure:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        self._sock = sock
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        sock.sendall(request.encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket refused")
            head += chunk
            if len(head) > 65536:
                raise ConnectionError("bad websocket answer")
        header, rest = head.split(b"\r\n\r\n", 1)
        if b" 101" not in header.split(b"\r\n", 1)[0]:
            raise ConnectionError("websocket refused")
        sock.settimeout(30)
        reader = _FrameReader(sock, rest)
        self.connected = True
        self.on_state(True)
        message = b""
        while not self._stop.is_set():
            try:
                fin, opcode, payload = reader.frame()
            except socket.timeout:
                self._send(sock, 0x9, b"")      # keep-alive ping
                continue
            if opcode == 0x8:
                return
            if opcode == 0x9:
                self._send(sock, 0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                message = payload
                kind = opcode
            elif opcode == 0x0:
                message += payload
            else:
                continue
            if fin and kind == 0x2:
                try:
                    self.on_binary(message)
                except Exception:  # noqa: BLE001
                    pass
            if fin and kind == 0x1:
                try:
                    data = json.loads(message.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    data = None
                if isinstance(data, dict):
                    try:
                        self.on_message(data)
                    except Exception:  # noqa: BLE001 - a bad handler must not kill the socket
                        pass

    @staticmethod
    def _send(sock, opcode, payload: bytes):
        mask = os.urandom(4)
        length = len(payload)
        head = bytes([0x80 | opcode])
        if length < 126:
            head += bytes([0x80 | length])
        elif length < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", length)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        sock.sendall(head + mask + masked)


# ComfyUI's binary websocket messages (server.py BinaryEventTypes)
PREVIEW_IMAGE, UNENCODED_PREVIEW_IMAGE, TEXT, PREVIEW_IMAGE_WITH_METADATA = 1, 2, 3, 4
IMAGE_MIME = {1: "image/jpeg", 2: "image/png", 3: "image/webp"}


def parse_binary(payload: bytes):
    """{event, mime, image, metadata} for a preview message, or {event, size} for anything else."""
    if len(payload) < 4:
        return {"event": None, "size": len(payload)}
    event = struct.unpack(">I", payload[:4])[0]
    out = {"event": event, "size": len(payload)}
    if event == PREVIEW_IMAGE and len(payload) >= 8:
        kind = struct.unpack(">I", payload[4:8])[0]
        out.update(mime=IMAGE_MIME.get(kind, "application/octet-stream"), image=payload[8:], metadata=None)
    elif event == PREVIEW_IMAGE_WITH_METADATA and len(payload) >= 8:
        length = struct.unpack(">I", payload[4:8])[0]
        try:
            metadata = json.loads(payload[8:8 + length].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            metadata = {}
        image = payload[8 + length:]
        mime = (metadata or {}).get("image_type") or sniff_mime(image)
        out.update(mime=mime, image=image, metadata=metadata)
    return out


def sniff_mime(data: bytes):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


class _FrameReader:
    def __init__(self, sock, buffered=b""):
        self.sock = sock
        self.buf = buffered

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def frame(self):
        b1, b2 = self._read(2)
        fin = bool(b1 & 0x80)
        opcode = b1 & 0x0F
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        mask = self._read(4) if b2 & 0x80 else None
        payload = self._read(length) if length else b""
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload


def wait_until(predicate, timeout=5.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()
