"""latents.py: the .pt of the plugin (torch.save of {"video", "audio", "frames"}) rewritten as MultiRef's .safetensors,
without torch. The .pt is written here the way torch.save writes it (zip archive: data.pkl with persistent storages,
data/<key> with the raw bytes), with stand-ins for the torch classes."""
import collections
import io
import os
import pickle
import struct
import sys
import tempfile
import types
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from encore import latents  # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(label)


# stand-ins for torch, only to write a file the way torch.save does
torch = types.ModuleType("torch"); utils = types.ModuleType("torch._utils")
class FloatStorage:  # noqa: E302
    pass
FloatStorage.__module__ = "torch"; torch.FloatStorage = FloatStorage
def _rebuild_tensor_v2(*args):  # noqa: E302
    raise AssertionError("only written here")
_rebuild_tensor_v2.__module__ = "torch._utils"; utils._rebuild_tensor_v2 = _rebuild_tensor_v2
sys.modules.update({"torch": torch, "torch._utils": utils})


class Storage:
    def __init__(self, key, values):
        self.key, self.data = key, struct.pack(f"<{len(values)}f", *values)


class Tensor:
    def __init__(self, storage, shape, offset=0, stride=None):
        self.storage, self.shape, self.offset = storage, shape, offset
        if stride is None:
            stride, step = [], 1
            for n in reversed(shape):
                stride.insert(0, step); step *= n
        self.stride = tuple(stride)

    def __reduce__(self):
        return (_rebuild_tensor_v2, (self.storage, self.offset, tuple(self.shape), self.stride, False, collections.OrderedDict()))


class Saver(pickle.Pickler):
    def persistent_id(self, obj):
        if isinstance(obj, Storage):
            return ("storage", FloatStorage, obj.key, "cpu", len(obj.data) // 4)
        return None


def torch_save(path, value, storages):
    buf = io.BytesIO()
    Saver(buf, protocol=2).dump(value)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("take/data.pkl", buf.getvalue())
        z.writestr("take/byteorder", "little")
        z.writestr("take/version", "3\n")
        for st in storages:
            z.writestr(f"take/data/{st.key}", st.data)


tmp = Path(tempfile.mkdtemp())
video = Storage("0", [float(i) for i in range(2 * 3 * 4)])
audio = Storage("1", [0.5, -0.25, 1.0, 2.0, 3.0, 4.0])
pt = tmp / "s1_abcdef12.pt"
torch_save(pt, {"video": Tensor(video, [1, 2, 3, 4]), "audio": Tensor(audio, [1, 1, 2, 2], offset=2), "frames": 5}, [video, audio])

data = latents.read_pt(pt)
check("the .pt is read without torch", data["frames"] == 5 and data["video"].shape == (1, 2, 3, 4) and data["video"].dtype == "F32")
check("…a tensor at an offset of its storage", data["audio"].data == struct.pack("<4f", 1.0, 2.0, 3.0, 4.0))
st = latents.convert_pt(pt)
header = latents.check_av(st)
check("converted to .safetensors, the .pt removed", st.suffix == ".safetensors" and st.is_file() and not pt.exists())
check("…video and audio with their shapes, MultiRef's format", header["video"]["shape"] == [1, 2, 3, 4] and header["audio"]["shape"] == [1, 1, 2, 2]
      and header["__metadata__"]["format"] == "h3_motion_context_av_v1")
raw = st.read_bytes()
n = struct.unpack("<Q", raw[:8])[0]
body = raw[8 + n:]
a, b = header["video"]["data_offsets"]
check("…the bytes as they were", body[a:b] == video.data and (8 + n) % 8 == 0)

# a tensor that is not contiguous is refused (the plugin saved contiguous ones), and the .pt stays
bad = tmp / "s2_abcdef12.pt"
st2 = Storage("0", [0.0] * 6)
torch_save(bad, {"video": Tensor(st2, [2, 3], stride=[1, 2]), "audio": Tensor(Storage("1", [0.0]), [1]), "frames": 1}, [st2, Storage("1", [0.0])])
try:
    latents.convert_pt(bad)
    check("a non-contiguous tensor is refused", False)
except latents.LatentError:
    check("a non-contiguous tensor is refused, the .pt kept", bad.exists() and not bad.with_suffix(".safetensors").exists())

# something else than tensors and plain values is refused (nothing is executed)
evil = tmp / "s3_abcdef12.pt"
buf = io.BytesIO(); pickle.dump({"video": os.getcwd}, buf, protocol=2)
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("take/data.pkl", buf.getvalue())
try:
    latents.read_pt(evil)
    check("an unexpected class in the .pt is refused", False)
except latents.LatentError:
    check("an unexpected class in the .pt is refused", True)

print("FAILED" if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
