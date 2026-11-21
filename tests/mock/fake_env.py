# Executed by mock_studio.py (exec, same namespace): a fake ComfyUI around the REAL plugin code.
# Sets: pkg (the plugin's nodes module), inp / outp (ComfyUI's input / output folders), torch, Image, na, CAP.
# The plugin folder comes from the H3_PLUGIN environment variable (the ComfyUI-H3-ClipPlan folder).
import sys, types, os, json, shutil, tempfile, importlib
import torch                                    # the numpy shim of tests/mock/shim (PYTHONPATH)
from PIL import Image

PLUGIN = os.environ.get("H3_PLUGIN")
if not PLUGIN or not os.path.isfile(os.path.join(PLUGIN, "nodes.py")):
    sys.exit("H3_PLUGIN must give the ComfyUI-H3-ClipPlan folder (the one holding nodes.py)")
root = tempfile.mkdtemp()
inp, outp = os.path.join(root, "input"), os.path.join(root, "output")
os.makedirs(os.path.join(inp, "plans")); os.makedirs(outp)
for n in ("fillette.png", "rue.png"):
    Image.new("RGB", (64, 64)).save(os.path.join(inp, n))
fp = types.ModuleType("folder_paths")
fp.get_input_directory = lambda: inp
fp.get_output_directory = lambda: outp
fp.get_annotated_filepath = lambda n: os.path.join(inp, n)
fp.exists_annotated_filepath = lambda n: os.path.exists(os.path.join(inp, n))
sys.modules["folder_paths"] = fp
CAP = {}
class R2V:
    @classmethod
    def execute(cls, **kw):
        CAP.update(kw)
        steps = 2 + 5 * ((kw["length"] - 5) // 17)
        audio_t = round(kw["length"] / 24 * 40)
        return ("COND", {"samples": [torch.zeros(1, 24, steps, 34, 60), torch.zeros(1, 32, 2, audio_t)]})
ext = types.ModuleType("comfy_extras"); m = types.ModuleType("comfy_extras.nodes_minimax_h3"); m.MiniMaxH3ReferenceToVideo = R2V
na = types.ModuleType("comfy_extras.nodes_audio")
na.load = lambda path: (torch.randn(1, int(32000 * (6 if "homme" in path else 9))), 32000)
sys.modules.update({"comfy_extras": ext, "comfy_extras.nodes_minimax_h3": m, "comfy_extras.nodes_audio": na})
class GenCtx:
    def prepare(self, latent, source_latent, context_length, audio_feather_ticks):
        CAP["ctx"] = (context_length, audio_feather_ticks, source_latent["samples"][0].shape)
        return (latent, context_length)
class SongCtx:     # music_video mode
    def prepare(self, latent, audio_vae, master_audio, clip_start_seconds, context_length, source_fps, crop, source_latent):
        CAP["song_ctx"] = (clip_start_seconds, context_length)
        return (latent, context_length, {"waveform": torch.zeros((1, 2, 8000)), "sample_rate": 8000})
nodes_mod = types.ModuleType("nodes"); nodes_mod.NODE_CLASS_MAPPINGS = {"MiniMaxH3GeneratedAVMaskedContext": GenCtx, "MiniMaxH3SongMaskedAVContext": SongCtx}
sys.modules["nodes"] = nodes_mod
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGIN)))
pkg = importlib.import_module(os.path.basename(os.path.abspath(PLUGIN)) + ".nodes")
print("fake ComfyUI: plugin", os.path.abspath(PLUGIN), "version", getattr(pkg, "APP_VERSION", "?"), flush=True)
for n in ("homme.wav", "fillette.wav"):
    open(os.path.join(inp, n), "wb").write(b"x")
