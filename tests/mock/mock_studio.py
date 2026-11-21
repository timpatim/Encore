"""Fake ComfyUI for Encore's tests: the real plugin code (numpy torch shim), fake models, websocket.

    H3_PLUGIN=/path/to/ComfyUI-H3-ClipPlan PYTHONPATH=tests/mock/shim MOCK_PORT=8771 python tests/mock/mock_studio.py
Test hooks: POST /test/run (finish the job running), /test/start, /test/foreign, /test/interrupts.
"""
import random, json, os, sys, shutil, threading, uuid, glob, time, base64, hashlib, struct
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from email.parser import BytesParser
from email.policy import default as email_default
from urllib.parse import urlparse, parse_qs
HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, "fake_env.py")).read())   # sets pkg, inp, outp, fake modules
VIDEOS = sorted(glob.glob(os.path.join(HERE, "..", "fixtures", "clips", "*.mp4")))
for n in ("fillette.png", "rue.png"):
    os.makedirs(os.path.join(inp, "refs", "rue_test_v1"), exist_ok=True)
    shutil.copy(os.path.join(inp, n), os.path.join(inp, "refs", "rue_test_v1", n))
Image.new("RGB", (64, 64), (200, 30, 30)).save(os.path.join(inp, "refs", "rue_test_v1", "fillette_rouge.png"))
os.makedirs(os.path.join(inp, "voices", "rue_test_v1"), exist_ok=True)
for n in ("fillette.wav", "homme.wav"):
    open(os.path.join(inp, "voices", "rue_test_v1", n), "wb").write(b"x")
import hashlib as _h
na.load = lambda path: (torch.full((1, 32000 * 6), float(int(_h.md5(path.encode()).hexdigest()[:4], 16))), 32000)
class AVAE:
    audio_sample_rate = 32000; audio_sample_rate_output = 44100
    def decode(self, z): return torch.ones(1, int(z.shape[-1] * 44100 / 40), 2)
HISTORY, PROMPTS, QUEUE = {}, {}, []
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
STATE = {"down": False}


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
        "ModelPreviewOverrideKJ": {"model": ["MODEL"], "max_resolution": ["INT", {"default": 1024, "min": 0, "max": 8192}], "jpeg_quality": ["INT", {"min": 30, "max": 100}],
            "suppress_default_preview": ["BOOLEAN", {}], "preview_frames": ["INT", {"default": 1, "min": 1, "max": 1024}], "preview_fps": ["INT", {"min": 1, "max": 60}],
            "tiny_vae": ["COMBO", {"options": ["none", "taeh3.safetensors"]}]},
    }
    for k, v in simple.items(): info[k] = {"input": {"required": v}}
    simple2 = {
        "MinimaxH3LatentUpscaler3D": {"latent": ["*"], "model_name": combo(["minimax_h3_latent_upscaler_3d_fp16.safetensors"])},
        "MinimaxH3LatentUpscalerNode2D": {"latent": ["*"], "model_name": combo(["minimax_h3_latent_upscaler_2d_conv_v1_fp16.safetensors"])},
        "LatentUpscaleModelLoader": {"model_name": combo(["h3_official_upscaler.safetensors"])},
    }
    for k, v in simple2.items(): info[k] = {"input": {"required": v}}
    for k in ["LTXVSeparateAVLatent", "LTXVConcatAVLatent", "LatentUpscale", "LatentCut", "ReplaceVideoLatentFrames", "SplitSigmas",
              "ManualSigmas", "MiniMaxH3LatentUpscaleWithModel"]:
        info[k] = {"input": {"required": {}}}
    for k in ["MiniMaxH3SigmaShift", "MiniMaxH3AudioVAECompatibility", "RandomNoise", "BasicGuider", "SamplerCustomAdvanced", "VAEDecode", "VHS_VideoCombine",
              "MiniMaxH3ReferenceToVideo", "MiniMaxH3SongMaskedAVContext", "MiniMaxH3GeneratedAVMaskedContext", "MiniMaxH3StreamLiveMusicVideoToVHS"]:
        info[k] = {"input": {"required": {}}}
    for name, cls in pkg.NODE_CLASS_MAPPINGS.items():
        it = cls.INPUT_TYPES()
        conv = lambda d: {k: ([v[0]] + ([v[1]] if len(v) > 1 else []) if not isinstance(v[0], list) else [v[0], v[1] if len(v) > 1 else {}]) for k, v in d.items()}
        info[name] = {"input": {"required": conv(it.get("required", {})), "optional": conv(it.get("optional", {}))}}
    for k in list(info):
        if k in HIDDEN: del info[k]
    return info
def screenshot_video(nodes):
    """For the README screenshots (tests/screenshots): MOCK_VIDEOS is a folder of <scene>_<n>.mp4 videos; the
    scene is the first one whose name is in a reference image of the prompt, a video of it is taken at random."""
    folder = os.environ.get("MOCK_VIDEOS")
    if not folder: return None
    images = " ".join(str(n["inputs"].get("image", "")) for n in nodes.values() if n["class_type"] == "H3PlanReference")
    videos = sorted(glob.glob(os.path.join(folder, "*.mp4")))
    scenes = sorted({os.path.basename(v).rsplit("_", 1)[0] for v in videos})
    scene = next((sc for sc in scenes if sc in images), scenes[0] if scenes else None)
    pick = [v for v in videos if os.path.basename(v).startswith(scene + "_")]
    return random.choice(pick) if pick else None


def execute(pid, prompt):
    try:
        bank = None
        nodes = prompt
        def refs_of(link):
            nonlocal bank
            if not link: return None
            node = nodes[link[0]]; i = node["inputs"]
            prev = refs_of(i.get("references"))
            if node["class_type"] == "H3PlanReference": return pkg.H3PlanReference().add(i["name"], i["image"], prev)[0]
            return pkg.H3PlanVoice().add(i["name"], i["voice_file"], prev)[0]
        clipn = next(n for n in nodes.values() if n["class_type"] == "H3PlanClip")["inputs"]
        refs = refs_of(clipn.get("references"))
        song = {"waveform": torch.zeros((1, 2, 8000 * 60)), "sample_rate": 8000} if clipn.get("master_audio") else None   # music_video: a silent song
        o = pkg.H3PlanClip().prepare("CLIP", "VAE", AVAE(), clipn["plan_file"], clipn["clip_index"], clipn["seed_mode"], references=refs, master_audio=song,
                                     width=clipn["width"], height=clipn["height"], take_token=clipn["take_token"], parent_token=clipn["parent_token"], seed_override=clipn["seed_override"])
        sl = next(n for n in nodes.values() if n["class_type"] == "H3PlanSaveLatent")["inputs"]
        pkg.H3PlanSaveLatent().save(o[1], o[5], sl["delete_stale"], AVAE())
        dst = os.path.join(outp, o[4] + "_00001.mp4"); os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(screenshot_video(nodes) or VIDEOS[clipn["clip_index"] % len(VIDEOS)], dst)
        HISTORY[pid] = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": {}}
        try:
            with open("/tmp/mock_last_prompt.json", "w") as fh: json.dump(prompt, fh, indent=1)
        except Exception: pass
        ws_send({"type": "execution_success", "data": {"prompt_id": pid}})
    except Exception as e:
        HISTORY[pid] = {"status": {"status_str": "error", "completed": False, "messages": [["execution_error", {"node_type": "H3PlanClip", "exception_message": str(e)}]]}, "outputs": {}}
        ws_send({"type": "execution_error", "data": {"prompt_id": pid, "node_type": "H3PlanClip", "exception_message": str(e)}})
def execute_assemble(pid, prompt):
    a = prompt["10"]["inputs"]
    class Stream:
        def stream_to_vhs(self, **kw):
            dst = os.path.join(outp, kw["filename_prefix"] + "_00001.mp4"); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy(screenshot_video({}) or VIDEOS[0], dst)
            return {"ui": {"gifs": [{"filename": os.path.basename(dst), "subfolder": os.path.dirname(kw["filename_prefix"]), "type": "output"}]}, "result": ([dst],)}
    nodes_mod.NODE_CLASS_MAPPINGS["MiniMaxH3StreamLiveMusicVideoToVHS"] = Stream
    pkg._decode_audio = lambda vae, z: (torch.zeros((1, 2, int(z.shape[-1] * 44100 / 40))), 44100)
    try:
        song = {"waveform": torch.zeros((1, 2, 8000 * 60)), "sample_rate": 8000} if a.get("master_audio") else None
        r = pkg.H3PlanAssemble().assemble("VAE", a["plan_file"], 0, 19, master_audio=song, audio_vae=AVAE())
        HISTORY[pid] = {"status": {"status_str": "success", "messages": []}, "outputs": {"10": {**r["ui"], "text": [r["result"][1]]}}}
    except Exception as e:
        HISTORY[pid] = {"status": {"status_str": "error", "messages": [["execution_error", {"node_type": "H3PlanAssemble", "exception_message": str(e)}]]}, "outputs": {}}
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
        if u.path == "/h3clipplan/ping": return self.send({"app": "h3clipplan", "version": "3.5"})
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
        if u.path == "/h3clipplan/takes":
            try: return self.send(pkg._takes_listing(q["plan"]))
            except Exception as e: return self.send({"error": str(e)}, 400)
        if u.path == "/h3clipplan/settings": return self.send(pkg._read_settings(q["project"]))
        self.send({"error": "nf " + u.path}, 404)
    def do_POST(self):
        u = urlparse(self.path); n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n)
        if u.path == "/upload/image":
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
        if u.path == "/h3clipplan/selection": return self.send(pkg._save_selection(body["plan"], body["selection"]))
        if u.path == "/h3clipplan/digest": return self.send(pkg._ref_digests(body.get("images"), body.get("voices")))
        if u.path == "/h3clipplan/delete_takes": return self.send(pkg._delete_takes(body["plan"], body["takes"]))
        if u.path == "/h3clipplan/settings": return self.send(pkg._write_settings(body["project"], body["settings"]))
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
            HISTORY[pid] = {"status": {"status_str": "error", "completed": False, "messages": [["execution_error", {"node_type": "H3PlanClip", "exception_message": "panne simulée"}]]}, "outputs": {}}
            ws_send({"type": "execution_error", "data": {"prompt_id": pid, "node_type": "H3PlanClip", "exception_message": "panne simulée"}})
            return self.send({"prompt_id": pid})
        if u.path == "/test/foreign":   # test hook: a prompt queued by someone else (running if asked)
            pid = "foreign-" + uuid.uuid4().hex[:6]; PROMPTS[pid] = ({}, {}); NUM[pid] = next(COUNTER)
            (RUNNING if body.get("run") else QUEUE).append(pid); FOREIGN.add(pid)
            return self.send({"prompt_id": pid})
        if u.path == "/test/interrupts": return self.send({"interrupts": INTERRUPTS})
        if u.path == "/test/run":   # test hook: execute the oldest queued prompt
            if RUNNING: ws_send({"type": "executing", "data": {"prompt_id": RUNNING[0], "node": "26"}}); time.sleep(0.3)
            pid = RUNNING.pop(0) if RUNNING else QUEUE.pop(0); prompt = PROMPTS[pid][0]
            if pid in FOREIGN:
                HISTORY[pid] = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": {}}
                return self.send({"prompt_id": pid, "status": "success", "messages": []})
            (execute_assemble if "10" in prompt else execute)(pid, prompt)
            return self.send({"prompt_id": pid, "status": HISTORY[pid]["status"]["status_str"], "messages": HISTORY[pid]["status"]["messages"]})
        self.send({"error": "nf"}, 404)
PORT = int(os.environ.get("MOCK_PORT", "8771"))
print("mock on", PORT, flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
