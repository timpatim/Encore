"""Encore - the latent file of a take: H3's video and audio latents side by side in a .safetensors file, the format
ComfyUI-H3-Motion-Context-MultiRef saves and loads (MiniMaxH3MotionContextSaveLatent / LoadLatent).

Up to 0.49 the takes held a .pt file written by the ComfyUI-H3-ClipPlan plugin (torch.save of {"video", "audio",
"frames"}). ``convert_pt`` rewrites one as .safetensors: a plain rewriting of the file, with the standard library
only (no torch, no computation): the .pt is a zip archive holding a pickle and the raw bytes of each tensor.
"""
from __future__ import annotations

import collections
import json
import os
import pickle
import struct
import zipfile
from pathlib import Path

FORMAT = "h3_motion_context_av_v1"
# torch storage types → safetensors dtype, bytes per element
STORAGES = {"FloatStorage": ("F32", 4), "HalfStorage": ("F16", 2), "BFloat16Storage": ("BF16", 2),
            "DoubleStorage": ("F64", 8)}


class LatentError(ValueError):
    pass


# --------------------------------------------------------------------------- .safetensors
def write_safetensors(path: Path, tensors, metadata=None):
    """tensors: {name: (dtype, shape, raw little-endian bytes)}, written in name order."""
    header, offset, blobs = {}, 0, []
    if metadata:
        header["__metadata__"] = {str(k): str(v) for k, v in metadata.items()}
    for name in sorted(tensors):
        dtype, shape, data = tensors[name]
        header[name] = {"dtype": dtype, "shape": [int(x) for x in shape], "data_offsets": [offset, offset + len(data)]}
        offset += len(data)
        blobs.append(data)
    text = json.dumps(header, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 8)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(struct.pack("<Q", len(text)))
        handle.write(text)
        for blob in blobs:
            handle.write(blob)
    os.replace(tmp, path)


def read_header(path: Path):
    """The header of a .safetensors file: {name: {"dtype", "shape", "data_offsets"}, "__metadata__": {...}}."""
    with open(path, "rb") as handle:
        raw = handle.read(8)
        if len(raw) != 8:
            raise LatentError(f"{Path(path).name}: not a safetensors file")
        size = struct.unpack("<Q", raw)[0]
        if not 2 <= size <= 100 * 1024 * 1024:
            raise LatentError(f"{Path(path).name}: not a safetensors file")
        try:
            return json.loads(handle.read(size).decode("utf-8"))
        except ValueError as exc:
            raise LatentError(f"{Path(path).name}: not a safetensors file") from exc


def check_av(path: Path):
    """The file holds an H3 audio-video latent (its video and audio streams): returns the header."""
    header = read_header(path)
    if "video" not in header or "audio" not in header:
        raise LatentError(f"{Path(path).name}: no video and audio latents")
    data_size = Path(path).stat().st_size - 8 - struct.unpack("<Q", open(path, "rb").read(8))[0]
    end = max(int(v["data_offsets"][1]) for k, v in header.items() if k != "__metadata__")
    if end != data_size:
        raise LatentError(f"{Path(path).name}: truncated")
    return header


# --------------------------------------------------------------------------- the .pt of the plugin
class _Tensor:
    def __init__(self, dtype, shape, data):
        self.dtype, self.shape, self.data = dtype, shape, data


def _rebuild_tensor(storage, offset, size, stride, *_rest):
    kind, data = storage
    dtype, width = STORAGES[kind]
    shape = tuple(int(x) for x in size)
    count = 1
    for n in shape:
        count *= n
    want, step = [], 1
    for n in reversed(shape):           # a contiguous tensor (the plugin saved .contiguous() tensors)
        want.insert(0, step)
        step *= n
    if count > 1 and tuple(int(x) for x in stride) != tuple(want):
        raise LatentError("a tensor of the .pt file is not contiguous")
    start = int(offset) * width
    chunk = data[start:start + count * width]
    if len(chunk) != count * width:
        raise LatentError("a tensor of the .pt file is cut short")
    return _Tensor(dtype, shape, chunk)


def read_pt(path: Path):
    """{key: value} of the dictionary a .pt file holds; tensors as (dtype, shape, bytes)."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise LatentError(f"{Path(path).name}: not a torch archive") from exc
    with archive:
        names = archive.namelist()
        pkl = next((n for n in names if n.endswith("/data.pkl")), None)
        if pkl is None:
            raise LatentError(f"{Path(path).name}: not a torch archive")
        prefix = pkl[:-len("data.pkl")]
        order = next((n for n in names if n == prefix + "byteorder"), None)
        if order and archive.read(order).strip() not in (b"little", b""):
            raise LatentError(f"{Path(path).name}: big-endian tensors")

        class Reader(pickle.Unpickler):
            def find_class(self, module, name):
                if module == "torch._utils" and name in ("_rebuild_tensor_v2", "_rebuild_tensor"):
                    return _rebuild_tensor
                if module == "torch" and name in STORAGES:
                    return name
                if module == "collections" and name == "OrderedDict":
                    return collections.OrderedDict
                if module == "torch" and name == "Size":
                    return tuple
                raise LatentError(f"{Path(path).name}: unexpected content ({module}.{name})")

            def persistent_load(self, pid):
                # ('storage', storage type, key, location, number of elements)
                if not isinstance(pid, tuple) or not pid or pid[0] != "storage":
                    raise LatentError(f"{Path(path).name}: unexpected storage")
                kind = pid[1]
                if kind not in STORAGES:
                    raise LatentError(f"{Path(path).name}: unsupported tensor type {kind}")
                return kind, archive.read(f"{prefix}data/{pid[2]}")

        import io
        value = Reader(io.BytesIO(archive.read(pkl))).load()
    if not isinstance(value, dict):
        raise LatentError(f"{Path(path).name}: not a dictionary")
    return value


def convert_pt(pt: Path):
    """Rewrites the .pt latent of a take as .safetensors beside it, checks what was written, then removes the
    .pt. Returns the new file."""
    pt = Path(pt)
    target = pt.with_suffix(".safetensors")
    data = read_pt(pt)
    streams = {}
    for key in ("video", "audio"):
        tensor = data.get(key)
        if not isinstance(tensor, _Tensor):
            raise LatentError(f"{pt.name}: no {key} latent")
        streams[key] = (tensor.dtype, tensor.shape, tensor.data)
    write_safetensors(target, streams, {"format": FORMAT})
    header = check_av(target)
    for key, (dtype, shape, blob) in streams.items():
        got = header[key]
        if got["dtype"] != dtype or tuple(got["shape"]) != tuple(shape) or got["data_offsets"][1] - got["data_offsets"][0] != len(blob):
            target.unlink(missing_ok=True)
            raise LatentError(f"{pt.name}: the converted file does not match")
    pt.unlink()
    return target


# --------------------------------------------------------------------------- converting a project (once, in 0.50)
_STATE = {}          # project folder → {"total", "done", "failed": [names], "running"}


def conversion(project: Path):
    """Where the conversion of a project's old latents stands."""
    from . import takes
    project = Path(project)
    state = _STATE.get(str(project))
    if state is None or not state["running"]:
        left = len(takes.old_latents(project))
        if state is None or left:
            state = {"total": left, "done": 0, "failed": list((state or {}).get("failed") or []), "running": False}
    return dict(state)


def start_conversion(project: Path):
    """Converts the .pt latents of a project's takes in the background (see conversion for its progress). A file
    that cannot be converted stays: its take is shown and assembled, but cannot be continued."""
    import threading
    from . import takes
    project = Path(project)
    key = str(project)
    if (_STATE.get(key) or {}).get("running"):
        return conversion(project)
    files = takes.old_latents(project)
    state = {"total": len(files), "done": 0, "failed": [], "running": bool(files)}
    _STATE[key] = state

    def run():
        try:
            for pt in files:
                try:
                    convert_pt(pt)
                except (LatentError, OSError, pickle.UnpicklingError, EOFError, AttributeError, TypeError, KeyError) as exc:
                    state["failed"].append(f"{pt.parent.name}/{pt.name}: {exc}")
                state["done"] += 1
        finally:
            state["running"] = False
    if files:
        threading.Thread(target=run, daemon=True, name="encore-latents").start()
    return dict(state)
