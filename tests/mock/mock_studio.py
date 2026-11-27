"""Fake ComfyUI for Encore's tests (0.50): fake models and nodes (ComfyUI's own, MultiRef, VHS), a websocket.

    MOCK_PORT=8771 python tests/mock/mock_studio.py
Each node of a workflow is checked like ComfyUI would (class known, files present) and its fake output computed; what
the nodes received is kept for the tests (POST /test/cap).
Test hooks: POST /test/run (finish the job running), /test/start, /test/foreign, /test/interrupts.
"""
import random, json, os, sys, shutil, subprocess, threading, uuid, glob, time, base64, hashlib, struct, tempfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from email.parser import BytesParser
from email.policy import default as email_default
from urllib.parse import urlparse, parse_qs
HERE = os.path.dirname(os.path.abspath(__file__))
VIDEOS = sorted(glob.glob(os.path.join(HERE, "..", "fixtures", "clips", "*.mp4")))
root = tempfile.mkdtemp()
inp, outp = os.path.join(root, "input"), os.path.join(root, "output")
os.makedirs(inp); os.makedirs(outp)
CAP = {}
HISTORY, PROMPTS, QUEUE = {}, {}, []
STREAM, LAST_ASSEMBLY = {}, {}
RUNNING = []
WS = []
WSLOCK = threading.Lock()
UPLOADS = []
def ws_send_bin(data):
    head = bytes([0x82]) + (bytes([len(data)]) if len(data) < 126 else (bytes([126]) + struct.pack(">H", len(data)) if len(data) < 65536 else bytes([127]) + struct.pack(">Q", len(data))))
    with WSLOCK:
        for w in list(WS):
            try: w.write(head + data); w.flush()
            except Exception: WS.remove(w)
def ws_send(msg):
    data = json.dumps(msg).encode()
    head = bytes([0x81]) + (bytes([len(data)]) if len(data) < 126 else (bytes([126]) + struct.pack(">H", len(data)) if len(data) < 65536 else bytes([127]) + struct.pack(">Q", len(data))))
    with WSLOCK:
        for w in list(WS):
            try: w.write(head + data); w.flush()
            except Exception: WS.remove(w)

def combo(values): return [values, {}]
HIDDEN = set()
STATE = {"down": False, "max_upload": 0}


def object_info():
    info = {}
    simple = {
        "UNETLoader": {"unet_name": combo(["minimax_h3_ref2va_pruned_int8_convrot.safetensors", "other.safetensors"]), "weight_dtype": combo(["default", "fp8_e4m3fn"])},
        "CLIPLoader": {"clip_name": combo(["qwen3vl_32b_minimax_h3_int8_convrot.safetensors"]), "type": combo(["minimax", "flux"]), "device": combo(["default", "cpu"])},
        "VAELoader": {"vae_name": combo(["minimax_h3_video_vae_int8_convrot.safetensors", "minimax_h3_audio_vae_fp32.safetensors"])},
        "LoraLoaderModelOnly": {"model": ["MODEL"], "lora_name": combo(["minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "feu.safetensors", "style_pastel.safetensors"] + [f"perso/style_{k:02d}.safetensors" for k in range(1, 25)]), "strength_model": ["FLOAT", {}]},
        "ModelAttentionBackend": {"model": ["MODEL"], "attention": ["COMBO", {"options": ["pytorch attention", "comfy kitchen attention"]}]},
        "KSamplerSelect": {"sampler_name": combo(["euler", "res_multistep"])},
        "BasicScheduler": {"model": ["MODEL"], "scheduler": combo(["simple", "karras"]), "steps": ["INT", {}], "denoise": ["FLOAT", {}]},
        "LoadAudio": {"audio": combo(["song.wav"])},
        "LoadImage": {"image": combo(["fillette.png", "rue.png"])},
        "ModelPreviewOverrideKJ": {"model": ["MODEL"], "max_resolution": ["INT", {"default": 1024, "min": 0, "max": 8192}], "jpeg_quality": ["INT", {"min": 30, "max": 100}],
            "suppress_default_preview": ["BOOLEAN", {}], "preview_frames": ["INT", {"default": 1, "min": 1, "max": 1024}], "preview_fps": ["INT", {"min": 1, "max": 60}],
            "tiny_vae": ["COMBO", {"options": ["none", "taeh3.safetensors"]}]},
        "MinimaxH3LatentUpscaler3D": {"latent": ["*"], "model_name": combo(["minimax_h3_latent_upscaler_3d_fp16.safetensors"])},
        "MinimaxH3LatentUpscalerNode2D": {"latent": ["*"], "model_name": combo(["minimax_h3_latent_upscaler_2d_conv_v1_fp16.safetensors"])},
        "LatentUpscaleModelLoader": {"model_name": combo(["h3_official_upscaler.safetensors"])},
    }
    for k, v in simple.items(): info[k] = {"input": {"required": v}}
    # MiniMax H3 Reference to Video: its growing inputs as ComfyUI's workflows name them (numbered from 0)
    opt = {}
    for group, count in (("ref_image", 9), ("ref_video", 3), ("ref_video_audio", 3), ("ref_audio", 3)):
        for k in range(count): opt[f"{group}s.{group}_{k}"] = ["IMAGE" if group in ("ref_image", "ref_video") else "AUDIO"]
    info["MiniMaxH3ReferenceToVideo"] = {"input": {"required": {"clip": ["CLIP"], "prompt": ["STRING", {}], "width": ["INT", {}], "height": ["INT", {}],
                                                                "length": ["INT", {}], "ref_image_size": combo(["match", "max"])},
                                                   "optional": dict(opt, vae=["VAE"], audio_vae=["VAE"])}}
    for k in ["LTXVSeparateAVLatent", "LTXVConcatAVLatent", "LatentUpscale", "LatentCut", "ReplaceVideoLatentFrames", "SplitSigmas",
              "ManualSigmas", "MiniMaxH3LatentUpscaleWithModel", "MiniMaxH3SigmaShift", "MiniMaxH3AudioVAECompatibility", "RandomNoise",
              "BasicGuider", "SamplerCustomAdvanced", "VAEDecode", "VAEDecodeAudio", "VHS_VideoCombine", "VHS_LoadVideo",
              "MiniMaxH3SongMaskedAVContext", "MiniMaxH3GeneratedAVMaskedContext", "MiniMaxH3ExistingVideoMaskedContext",
              "MiniMaxH3MotionContextSaveLatent", "MiniMaxH3MotionContextLoadLatent", "MiniMaxH3StreamLiveMusicVideoToVHS"]:
        info[k] = {"input": {"required": {}}}
    for k in list(info):
        if k in HIDDEN: del info[k]
    return info
def screenshot_video(nodes):
    """For the README screenshots (tests/screenshots): MOCK_VIDEOS is a folder of <scene>_<n>.mp4 videos; the
    scene is the first one whose name is in a reference image of the prompt, a video of it is taken at random."""
    folder = os.environ.get("MOCK_VIDEOS")
    if not folder: return None
    images = " ".join(str(n["inputs"].get("image", "")) for n in nodes.values() if n["class_type"] == "LoadImage")
    videos = sorted(glob.glob(os.path.join(folder, "*.mp4")))
    scenes = sorted({os.path.basename(v).rsplit("_", 1)[0] for v in videos})
    scene = next((sc for sc in scenes if sc in images), scenes[0] if scenes else None)
    pick = [v for v in videos if os.path.basename(v).startswith(scene + "_")]
    return random.choice(pick) if pick else None


class NodeError(Exception):
    def __init__(self, node_type, message):
        super().__init__(message); self.node_type = node_type


def video_shape(path):
    """[frames, height, width, 3] of a video file, and whether it has sound (ffprobe)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames,width,height", "-of", "json", path], capture_output=True, text=True)
    st = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
    snd = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip() != ""
    return [int(st.get("nb_read_frames") or 0), int(st.get("height") or 0), int(st.get("width") or 0), 3], snd


def write_latent(path, frames):
    """A small fake latent in MultiRef's format (video and audio side by side; the shapes say how long it is)."""
    steps = 2 + 5 * ((int(frames) - 5) // 17) if frames >= 5 else 1
    tensors = {"audio": ("F32", [1, 1, 1, max(1, round(frames / 24 * 40))]), "video": ("F32", [1, 1, steps, 1, 1])}
    header, off, blobs = {"__metadata__": {"format": "h3_motion_context_av_v1"}}, 0, []
    for name in sorted(tensors):
        dtype, shape = tensors[name]; n = 4
        for d in shape: n *= d
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [off, off + n]}; off += n; blobs.append(b"\0" * n)
    text = json.dumps(header).encode(); text += b" " * (-len(text) % 8)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f: f.write(struct.pack("<Q", len(text)) + text + b"".join(blobs))


def run_graph(nodes):
    """Computes the nodes in order of their links (like ComfyUI): {node id: outputs}; raises NodeError."""
    done = {}
    def val(v):
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in nodes:
            return out(v[0])[v[1]]
        return v
    def out(nid):
        if nid in done: return done[nid]
        node = nodes[nid]; ct = node["class_type"]; i = {k: val(v) for k, v in node["inputs"].items()}
        done[nid] = NODES.get(ct, lambda i, ct=ct: [ct] * 4)(i)
        return done[nid]
    for nid in nodes: out(nid)
    return done
def _input_file(ct, name):
    path = os.path.join(inp, name)
    if not os.path.isfile(path): raise NodeError(ct, f"Invalid file: {name}")
    return path
def n_load_image(i):
    _input_file("LoadImage", i["image"]); return [{"image": i["image"]}, "MASK"]
def n_load_audio(i):
    _input_file("LoadAudio", i["audio"]); return [{"audio": i["audio"]}]
def n_load_video(i):
    path = _input_file("VHS_LoadVideo", i["video"]); shape, snd = video_shape(path)
    return [{"video": i["video"], "shape": shape}, shape[0], {"sound": snd} if snd else None, {}]
def n_r2v(i):
    groups = {g: [v for k, v in sorted(i.items()) if k.startswith(g + "s.")] for g in ("ref_image", "ref_video", "ref_video_audio", "ref_audio")}
    CAP["r2v"] = {"prompt": i["prompt"], "length": i["length"], "images": [x["image"] for x in groups["ref_image"]],
                  "videos": [x["shape"] for x in groups["ref_video"]], "video_audios": len([x for x in groups["ref_video_audio"] if x]),
                  "audios": [x["audio"] for x in groups["ref_audio"]], "ref_image_size": i["ref_image_size"]}
    return ["COND", {"frames": int(i["length"]), "width": int(i["width"]), "height": int(i["height"])}]
def n_free_ctx(i):
    src = i["source_latent"]
    if not isinstance(src, dict) or not src.get("loaded"): raise NodeError("MiniMaxH3GeneratedAVMaskedContext", "source_latent is not a loaded H3 latent")
    CAP["ctx"] = [int(i["context_length"]), int(i["audio_feather_ticks"]), src["file"]]
    return [dict(i["latent"], context=int(i["context_length"])), int(i["context_length"])]
def n_video_ctx(i):
    CAP.setdefault("video_encoded", []).append(i["source_frames"]["shape"])
    CAP["ctx"] = [int(i["context_length"]), int(i["audio_feather_ticks"]), i["source_frames"]["shape"]]
    return [dict(i["latent"], context=int(i["context_length"])), int(i["context_length"]), 0, int(i["context_length"])]
def n_song_ctx(i):
    CAP["song_ctx"] = [float(i["clip_start_seconds"]), int(i["context_length"])]
    if i.get("source_frames"): CAP.setdefault("video_encoded", []).append(i["source_frames"]["shape"])
    if i.get("source_latent") is not None and not (i["source_latent"] or {}).get("loaded"):
        raise NodeError("MiniMaxH3SongMaskedAVContext", "source_latent is not a loaded H3 latent")
    if i.get("source_frames") or i.get("source_latent"):
        CAP["ctx"] = [int(i["context_length"]), 8, (i.get("source_frames") or {}).get("shape") or i["source_latent"]["file"]]
    frames = i["latent"]["frames"]
    return [dict(i["latent"], context=int(i["context_length"])), int(i["context_length"]), {"song": i["master_audio"]["audio"], "frames": frames}]
def n_load_latent(i):
    p = i["latent_path"]; path = p if os.path.isabs(p) else os.path.join(outp, p)
    if not os.path.isfile(path): raise NodeError("MiniMaxH3MotionContextLoadLatent", f"no saved latent at {p}")
    return [{"loaded": True, "file": os.path.relpath(path, outp)}]
def n_sampler(i):
    lat = i["latent_image"]
    return [dict(lat) if isinstance(lat, dict) else lat, dict(lat) if isinstance(lat, dict) else lat]
def n_save_latent(i):
    prefix = i["filename_prefix"]; slot = int(i.get("clip_index") or 0)
    path = os.path.join(outp, f"{prefix}_{slot:05d}.safetensors" if slot else f"{prefix}_00001_.safetensors")
    write_latent(path, (i["latent"] or {}).get("frames", 0) if isinstance(i["latent"], dict) else 0)
    CAP["saved"] = os.path.relpath(path, outp)
    return [path]
def n_decode(i):
    return [{"frames": (i["samples"] or {}).get("frames", 0) if isinstance(i["samples"], dict) else 0}]
NODES = {"LoadImage": n_load_image, "LoadAudio": n_load_audio, "VHS_LoadVideo": n_load_video, "MiniMaxH3ReferenceToVideo": n_r2v,
         "MiniMaxH3GeneratedAVMaskedContext": n_free_ctx, "MiniMaxH3ExistingVideoMaskedContext": n_video_ctx,
         "MiniMaxH3SongMaskedAVContext": n_song_ctx, "MiniMaxH3MotionContextLoadLatent": n_load_latent,
         "SamplerCustomAdvanced": n_sampler, "MiniMaxH3MotionContextSaveLatent": n_save_latent, "VAEDecode": n_decode}


def clip_of(pid):
    """The clip a prompt makes (Encore's extra data), for the tone of its fake preview: 300 Hz for clip 1, 400 for 2…"""
    try:
        return int(((PROMPTS.get(pid) or (None, {}))[1].get("h3studio") or {}).get("clip") or 1)
    except (TypeError, ValueError):
        return 1
def execute(pid, prompt):
    nodes = prompt
    try:
        done = run_graph(nodes)
        CAP["clip_info"] = {"r2v": CAP.get("r2v"), "ctx": CAP.get("ctx"), "song_ctx": CAP.get("song_ctx")}
        combine = next((k for k, n in nodes.items() if n["class_type"] == "VHS_VideoCombine"), None)
        outputs = {}
        if combine:
            prefix = nodes[combine]["inputs"]["filename_prefix"]
            frames = int((done.get("20") or [None, {}])[1].get("frames") or 0)
            dst = os.path.join(outp, prefix + "_00001.mp4"); os.makedirs(os.path.dirname(dst), exist_ok=True)
            shot = screenshot_video(nodes)
            if shot: shutil.copy(shot, dst)
            else:      # a preview as long as the take (an edit clip that continues it reads its last frames)
                made = frames and subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24", "-f", "lavfi", "-i",
                                                  f"sine=frequency={200 + 100 * clip_of(pid)}:sample_rate=48000",
                                                  "-frames:v", str(frames), "-shortest", "-c:a", "aac", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", dst]).returncode == 0
                if not made: shutil.copy(VIDEOS[0], dst)
            outputs[combine] = {"gifs": [{"filename": os.path.basename(dst), "subfolder": os.path.dirname(prefix), "type": "output", "format": "video/h264-mp4"}]}
        HISTORY[pid] = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": outputs}
        try:
            with open("/tmp/mock_last_prompt.json", "w") as fh: json.dump(prompt, fh, indent=1)
        except Exception: pass
        ws_send({"type": "execution_success", "data": {"prompt_id": pid}})
    except NodeError as e:
        HISTORY[pid] = {"status": {"status_str": "error", "completed": False, "messages": [["execution_error", {"node_type": e.node_type, "exception_message": str(e)}]]}, "outputs": {}}
        ws_send({"type": "execution_error", "data": {"prompt_id": pid, "node_type": e.node_type, "exception_message": str(e)}})
    except Exception as e:
        HISTORY[pid] = {"status": {"status_str": "error", "completed": False, "messages": [["execution_error", {"node_type": "?", "exception_message": repr(e)}]]}, "outputs": {}}
        ws_send({"type": "execution_error", "data": {"prompt_id": pid, "node_type": "?", "exception_message": repr(e)}})
import itertools
NUM, COUNTER, FOREIGN, INTERRUPTS = {}, itertools.count(1), set(), []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if STATE["down"] and not self.path.startswith("/test/"):
            self.send_response(503); self.end_headers(); return
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/ws":
            key = self.headers["Sec-WebSocket-Key"]
            acc = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + "\r\n\r\n").encode()); self.wfile.flush()
            with WSLOCK: WS.append(self.wfile)
            ws_send({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": len(QUEUE)}}}})
            try:
                while True:
                    b = self.rfile.read(2)
                    if len(b) < 2: break
                    n = b[1] & 0x7F
                    if n == 126: n = struct.unpack(">H", self.rfile.read(2))[0]
                    elif n == 127: n = struct.unpack(">Q", self.rfile.read(8))[0]
                    self.rfile.read(4 + n)
                    if b[0] & 0x0F == 8: break
            finally:
                with WSLOCK:
                    if self.wfile in WS: WS.remove(self.wfile)
            self.close_connection = True
            return
        if u.path == "/system_stats": return self.send({"system": {"comfyui_version": "mock"}, "devices": [{"name": "MockGPU"}]})
        if u.path == "/object_info": return self.send(object_info())
        if u.path.startswith("/object_info/"): n = u.path.split("/")[-1]; return self.send({n: object_info()[n]})
        if u.path == "/view":
            base = inp if q.get("type") == "input" else outp
            path = os.path.join(base, q.get("subfolder", ""), q["filename"])
            if not os.path.isfile(path): return self.send({"error": "nf"}, 404)
            ct = "video/mp4" if path.endswith(".mp4") else "image/png" if path.endswith(".png") else "application/octet-stream"
            return self.send(open(path, "rb").read(), ctype=ct)
        if u.path == "/queue": return self.send({"queue_running": [[NUM.get(pid, 0), pid, PROMPTS[pid][0], PROMPTS[pid][1]] for pid in RUNNING], "queue_pending": [[NUM.get(pid, 0), pid, PROMPTS[pid][0], PROMPTS[pid][1]] for pid in QUEUE]})
        if u.path.startswith("/history/"): pid = u.path.split("/")[-1]; return self.send({pid: HISTORY[pid]} if pid in HISTORY else {})
        self.send({"error": "nf " + u.path}, 404)
    def do_POST(self):
        u = urlparse(self.path); n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n)
        if u.path == "/upload/image":
            if STATE["max_upload"] and n > STATE["max_upload"]:     # like ComfyUI's --max-upload-size (aiohttp)
                return self.send(f"Maximum request body size {STATE['max_upload']} exceeded, actual body size {n}".encode(), 413, ctype="text/plain")
            msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + raw)
            fields, filedata, fname = {}, None, None
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if part.get_filename(): filedata, fname = part.get_payload(decode=True), part.get_filename()
                else: fields[name] = part.get_content()
            sub = fields.get("subfolder", ""); kind = fields.get("type", "input")
            d = os.path.join(outp if kind == "output" else inp, sub); os.makedirs(d, exist_ok=True)
            open(os.path.join(d, fname), "wb").write(filedata); UPLOADS.append((kind, sub, fname))
            return self.send({"name": fname, "subfolder": sub, "type": kind})
        body = json.loads(raw or b"{}")
        if u.path == "/prompt":
            pid = uuid.uuid4().hex; PROMPTS[pid] = (body["prompt"], body.get("extra_data", {})); QUEUE.append(pid); NUM[pid] = next(COUNTER)
            missing = [n["class_type"] for n in body["prompt"].values() if n["class_type"] not in object_info()]
            if missing: QUEUE.remove(pid); return self.send({"error": {"message": "missing node"}, "node_errors": {"1": {"class_type": missing[0], "errors": [{"message": "not installed"}]}}}, 400)
            return self.send({"prompt_id": pid, "number": len(QUEUE)})
        if u.path == "/interrupt":
            INTERRUPTS.append(body.get("prompt_id"))
            for pid in list(RUNNING):
                if body.get("prompt_id") and body["prompt_id"] != pid: continue
                RUNNING.remove(pid)
                HISTORY[pid] = {"status": {"status_str": "error", "completed": False, "messages": [["execution_interrupted", {"prompt_id": pid}]]}, "outputs": {}}
                ws_send({"type": "execution_interrupted", "data": {"prompt_id": pid}})
            return self.send({})
        if u.path == "/queue":
            for pid in body.get("delete") or []:
                if pid in QUEUE: QUEUE.remove(pid)
            return self.send({})
        if u.path == "/test/hide":     # test hook: these node classes disappear from object_info (custom node not loaded)
            HIDDEN.clear(); HIDDEN.update(body.get("names") or []); return self.send({"hidden": sorted(HIDDEN)})
        if u.path == "/test/down":     # test hook: ComfyUI stops answering (true) or comes back (false)
            STATE["down"] = bool(body.get("down")); return self.send(STATE)
        if u.path == "/test/progress":   # test hook: one more sampling step of the running prompt
            pid = RUNNING[0]
            ws_send({"type": "progress", "data": {"prompt_id": pid, "node": "25", "value": body["value"], "max": 8}})
            return self.send({})
        if u.path == "/test/kj":   # test hook: KJNodes Model Preview Override message (mp4 or jpeg, raw base64)
            data = open(VIDEOS[0], "rb").read() if body.get("video") else open(os.path.join(inp, "rue.png"), "rb").read()
            ws_send({"type": "kj_preview_override", "data": {"node_id": "45", "image": base64.b64encode(data).decode(), "mime": "video/mp4" if body.get("video") else "image/jpeg",
                     "w": 512, "h": 288, "step": body.get("step", 1), "total": 8, "fps": 7.0, "audio": bool(body.get("video"))}})
            return self.send({})
        if u.path == "/test/preview":   # test hook: previews like ComfyUI (binary) and like a custom widget (JSON)
            import io
            from PIL import Image as _I
            buf = io.BytesIO(); _I.new("RGB", (96, 54), tuple(body.get("rgb", [200, 100, 0]))).save(buf, "PNG")
            ws_send_bin(struct.pack(">II", 1, 2) + buf.getvalue())
            if body.get("meta"):
                pid = RUNNING[0] if RUNNING else ""
                m = json.dumps({"node_id": "25", "prompt_id": pid, "image_type": "image/png"}).encode()
                ws_send_bin(struct.pack(">II", 4, len(m)) + m + buf.getvalue())
            if body.get("widget"):
                ws_send({"type": "kjnodes.preview", "data": {"node": "3", "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}})
            return self.send({})
        if u.path == "/test/start":   # test hook: the oldest queued prompt starts running
            pid = QUEUE.pop(0); RUNNING.append(pid)
            ws_send({"type": "execution_start", "data": {"prompt_id": pid}})
            ws_send({"type": "executing", "data": {"prompt_id": pid, "node": "25"}})
            ws_send({"type": "progress", "data": {"prompt_id": pid, "node": "25", "value": 3, "max": 8}})
            return self.send({"prompt_id": pid})
        if u.path == "/test/fail":  # test hook: the oldest queued prompt fails
            pid = RUNNING.pop(0) if RUNNING else QUEUE.pop(0)
            HISTORY[pid] = {"status": {"status_str": "error", "completed": False, "messages": [["execution_error", {"node_type": "MiniMaxH3ReferenceToVideo", "exception_message": "panne simulée"}]]}, "outputs": {}}
            ws_send({"type": "execution_error", "data": {"prompt_id": pid, "node_type": "MiniMaxH3ReferenceToVideo", "exception_message": "panne simulée"}})
            return self.send({"prompt_id": pid})
        if u.path == "/test/foreign":   # test hook: a prompt queued by someone else (running if asked)
            pid = "foreign-" + uuid.uuid4().hex[:6]; PROMPTS[pid] = ({}, {}); NUM[pid] = next(COUNTER)
            (RUNNING if body.get("run") else QUEUE).append(pid); FOREIGN.add(pid)
            return self.send({"prompt_id": pid})
        if u.path == "/test/max_upload":   # test hook: ComfyUI refuses uploads over this many bytes (0: no limit)
            STATE["max_upload"] = int(body.get("bytes") or 0); return self.send(STATE)
        if u.path == "/test/comfy_root":   # test hook: the fake ComfyUI folder (input/ inside), and what went through the upload route
            os.makedirs(os.path.join(os.path.dirname(inp), "custom_nodes"), exist_ok=True); os.makedirs(os.path.join(os.path.dirname(inp), "models"), exist_ok=True)
            return self.send({"root": os.path.dirname(inp), "uploads": [list(u_) for u_ in UPLOADS]})
        if u.path == "/test/interrupts": return self.send({"interrupts": INTERRUPTS})
        if u.path == "/test/cap":   # test hook: what the plugin gave the fake nodes (video encodes, contexts, last assembly)
            return self.send({"video_encoded": CAP.get("video_encoded", []), "song_ctx": CAP.get("song_ctx") or [],
                              "ctx": CAP.get("ctx"), "assembly": LAST_ASSEMBLY, "clip_info": CAP.get("clip_info"), "saved": CAP.get("saved"),
                              "r2v": CAP.get("r2v") or {"prompt": None, "videos": [], "video_audios": 0, "images": [], "audios": []}})
        if u.path == "/test/cap_reset":
            for k in ("video_encoded", "song_ctx", "ctx", "r2v", "saved"): CAP.pop(k, None)
            return self.send({})
        if u.path == "/test/run":   # test hook: execute the oldest queued prompt
            if RUNNING: ws_send({"type": "executing", "data": {"prompt_id": RUNNING[0], "node": "26"}}); time.sleep(0.3)
            if not RUNNING and not QUEUE: return self.send({"empty": True})
            pid = RUNNING.pop(0) if RUNNING else QUEUE.pop(0); prompt = PROMPTS[pid][0]
            if pid in FOREIGN:
                HISTORY[pid] = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": {}}
                return self.send({"prompt_id": pid, "status": "success", "messages": []})
            RUNNING.insert(0, pid)          # still in the queue (running) until its history is written
            try:
                execute(pid, prompt)
            finally:
                if pid in RUNNING: RUNNING.remove(pid)
            return self.send({"prompt_id": pid, "status": HISTORY[pid]["status"]["status_str"], "messages": HISTORY[pid]["status"]["messages"]})
        self.send({"error": "nf"}, 404)
PORT = int(os.environ.get("MOCK_PORT", "8771"))
print("mock on", PORT, flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
