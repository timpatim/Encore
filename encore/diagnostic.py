"""Encore - preview diagnostic (config.json "diagnostic_preview": true).

Writes what ComfyUI sends on its websocket to diagnostic_apercu.log and keeps the first preview images.
Used by the engine (websocket events).
"""
from __future__ import annotations

from .i18n import t as _t
import json
import threading
import time
from pathlib import Path

from . import projects


# --------------------------------------------------------------------------- preview diagnostic
class Diagnostic:
    """While generations run, writes what ComfyUI sends on its websocket to diagnostic_apercu.log
    (next to Encore.bat), and keeps the first preview images in diagnostic_apercu/."""
    MAX_LINES = 20000
    MAX_IMAGES = 20

    def __init__(self, folder: Path):
        self.log_path = folder / "diagnostic_apercu.log"
        self.image_dir = folder / "diagnostic_apercu"
        self.lines = 0
        self.images = 0
        self.lock = threading.Lock()
        self.started = False

    def _write(self, text):
        with self.lock:
            if self.lines >= self.MAX_LINES:
                return
            try:
                if not self.started:
                    self.started = True
                    with open(self.log_path, "a", encoding="utf-8") as handle:
                        handle.write(f"\n===== Encore {projects.STUDIO_VERSION} - session {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
                with open(self.log_path, "a", encoding="utf-8") as handle:
                    handle.write(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {text}\n")
                self.lines += 1
            except OSError:
                pass

    def save_image(self, data: bytes, mime: str, label: str):
        with self.lock:
            if self.images >= self.MAX_IMAGES:
                return None
            self.images += 1
            number = self.images
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "video/mp4": ".mp4"}.get(mime, ".bin")
        try:
            self.image_dir.mkdir(exist_ok=True)
            name = f"{number:02d}_{label}{ext}"
            (self.image_dir / name).write_bytes(data)
            return name
        except OSError:
            return None

    @staticmethod
    def _short(value, depth=0):
        if isinstance(value, str):
            return value if len(value) <= 160 else f"{value[:60]}…[{len(value)} car.]"
        if isinstance(value, dict):
            return {k: Diagnostic._short(v, depth + 1) for k, v in list(value.items())[:40]}
        if isinstance(value, list):
            return [Diagnostic._short(v, depth + 1) for v in value[:20]] + ([_t("engine.items", v0=len(value))] if len(value) > 20 else [])
        return value

    def json_message(self, msg):
        kind = msg.get("type")
        self._write(f"JSON type={kind} data={json.dumps(self._short(msg.get('data')), ensure_ascii=False)[:1500]}")

    def binary_message(self, info, raw: bytes):
        meta = info.get("metadata")
        line = _t("engine.binary_event_size_start", v0=info.get('event'), v1=info.get('size'), v2=raw[:16].hex())
        if "image" in info:
            line += _t("engine.image_bytes", v0=info.get('mime'), v1=len(info['image']), v2=image_size(info['image']))
            saved = self.save_image(info["image"], info.get("mime"), f"binaire_e{info.get('event')}")
            if saved:
                line += f" -> {saved}"
        if meta is not None:
            line += _t("engine.metadata", v0=json.dumps(self._short(meta), ensure_ascii=False)[:600])
        self._write(line)

    def note(self, text):
        self._write(text)


def image_size(data: bytes) -> str:
    """'LxH' read from a PNG, JPEG, WebP or GIF header ('' if unknown)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            return f"{w}x{h}"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return f"{int.from_bytes(data[6:8], 'little')}x{int.from_bytes(data[8:10], 'little')}"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                return f"{int.from_bytes(data[24:27], 'little') + 1}x{int.from_bytes(data[27:30], 'little') + 1} (VP8X{' animé' if data[20] & 2 else ''})"
            if chunk == b"VP8 ":
                return f"{int.from_bytes(data[26:28], 'little') & 0x3FFF}x{int.from_bytes(data[28:30], 'little') & 0x3FFF}"
            if chunk == b"VP8L":
                b = data[21:25]
                return f"{((b[1] & 0x3F) << 8 | b[0]) + 1}x{((b[3] & 0xF) << 10 | b[2] << 2 | (b[1] & 0xC0) >> 6) + 1}"
        if data[:3] == b"\xff\xd8\xff":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    return f"{int.from_bytes(data[i + 7:i + 9], 'big')}x{int.from_bytes(data[i + 5:i + 7], 'big')}"
                i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    except (IndexError, ValueError):
        pass
    return ""
