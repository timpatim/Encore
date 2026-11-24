"""v0.40: the final video made by Encore with ffmpeg from the takes' previews (no assembly in ComfyUI):
length on the timeline, the sound of each take where it shows, the original sound over an edited part; the plugin
still assembles when a take has no preview."""
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
sys.path.insert(0, ENCORE); from encore import plan_core  # noqa: E402
S = "http://127.0.0.1:8250"; M = "http://127.0.0.1:8771"
OK = []
def check(name, cond, info=""):
    OK.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}
def run_mock():
    try: call(M, "/test/run", {})
    except Exception: pass
def wait_last(P):
    for _ in range(90):
        time.sleep(0.7); run_mock()
        jobs = call(S, P + "/jobs")["jobs"]
        if jobs and jobs[-1]["status"] in ("done", "error", "cancelled"): break
    return call(S, P + "/jobs")["jobs"][-1]
def gen(P, body):
    if body.get("clip", 1) > 1 and "after" not in body:      # 0.42: after the take chosen for the clip before
        body = dict(body, after=call(S, P)["plan_takes"].get(str(body["clip"] - 1)))
    call(S, P + "/generate", body); return wait_last(P)
def frames_of(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return int(out or 0)
def tone(path, at):
    """Dominant frequency (Hz) of the sound 0.5 s around ``at`` seconds (0 when silent)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at - 0.25), "-t", "0.5", "-i", path, "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw[: len(raw) // 4 * 4], dtype=np.float32)
    if len(x) < 1000 or np.abs(x).max() < 1e-3: return 0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return round(float(np.argmax(spec) * 48000 / len(x)) / 50) * 50

SRC = "/tmp/v40_source.mp4"     # 3 shots (9 s, 12 s, 7 s) with a 300 Hz sound
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=9", "-f", "lavfi", "-i",
                "smptebars=size=640x360:rate=24:duration=12", "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=24", "-f", "lavfi", "-i",
                "sine=frequency=300:duration=28", "-filter_complex", "[2:v]trim=duration=7,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", SRC], check=True)

root = "/tmp/h3s_v40"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8250", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v40_srv.log", "w"))
time.sleep(1.5)
try:
    # ---------------- free mode, 3 clips (1 new scene, 2 continue): 300, 400, 500 Hz in the previews
    P = "/api/projects/rue"
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}},
                                 "width": 1024, "height": 576}, "PUT")
    for k in (1, 2, 3):
        job = gen(P, {"clip": k, "branch": "b1"})
        check(f"clip {k} generated", job["status"] == "done", (job["status"], job.get("error")))
    plan = plan_core.normalize(call(S, P)["plan"]); rows = plan_core.timeline(plan)
    leaf = call(S, P + "/takes")["clips"][2]["takes"][-1]["id"]
    call(M, "/test/cap_reset", {})
    call(S, P + "/assemble", {"clip": 3, "take": leaf}); job = wait_last(P)
    check("assembly done", job["kind"] == "assemble" and job["status"] == "done", (job["status"], job.get("error")))
    check("…by Encore: nothing sent to ComfyUI", not call(M, "/test/cap", {}).get("assembly"))
    ex = sorted(call(S, P + "/exports")["exports"], key=lambda e: e["created"])[-1]
    mp4 = f"{root}/projets/rue/exports/{ex['name']}.mp4"
    meta = json.load(open(f"{root}/projets/rue/exports/{ex['name']}.json"))
    check("the export says ffmpeg made it", meta.get("assembled_by") == "ffmpeg" and "ffmpeg" in meta.get("report", ""), meta)
    check("its length: the timeline up to the end of clip 3", frames_of(mp4) == rows[2]["end"], (frames_of(mp4), rows[2]["end"]))
    check("its size: the branch size", "1024x576" in meta.get("report", ""), meta.get("report"))
    mid = lambda r: (r["visible"] + r["end"]) / 2 / 24
    check("the sound of each take where it shows", [tone(mp4, mid(r)) for r in rows[:3]] == [300, 400, 500], [tone(mp4, mid(r)) for r in rows[:3]])
    check("a continue clip replaces the overlap with its own sound", tone(mp4, (rows[1]["raw_start"] + 6) / 24) == 400, tone(mp4, (rows[1]["raw_start"] + 6) / 24))
    check("infos written", os.path.isfile(f"{root}/projets/rue/exports/{ex['name']}.txt") or any(n.startswith(ex["name"]) and n.endswith((".md", ".txt", ".html"))
          for n in os.listdir(f"{root}/projets/rue/exports")), os.listdir(f"{root}/projets/rue/exports"))

    # ---------------- a take without preview: the plugin assembles
    take2 = call(S, P + "/takes")["clips"][1]["takes"][-1]["id"]
    import glob
    for f in glob.glob(f"{root}/projets/rue/**/{take2}.mp4", recursive=True): os.remove(f)
    call(M, "/test/cap_reset", {})
    call(S, P + "/assemble", {"clip": 3, "take": leaf}); job = wait_last(P)
    check("without a preview: assembly done", job["status"] == "done", (job["status"], job.get("error")))
    check("…by the plugin in ComfyUI", bool(call(M, "/test/cap", {}).get("assembly")))
    ex2 = sorted(call(S, P + "/exports")["exports"], key=lambda e: e["created"])[-1]
    check("…and the export says so", json.load(open(f"{root}/projets/rue/exports/{ex2['name']}.json")).get("assembled_by") == "plugin")

    # ---------------- an edited video (0-21 s) then a clip that continues it: original sound, then the generated one
    P = "/api/projects/ed"
    call(S, "/api/projects", {"name": "ed", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    call(S, f"{P}/resources?kind=videos&filename=source.mp4", raw=open(SRC, "rb").read(), method="POST")
    call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}},
                                 "width": 1024, "height": 576}, "PUT")
    raw = call(S, P)["plan"]
    c = raw["clips"]
    raw["refs"]["source"] = "edited video"
    raw["edit_video"] = {"ref": "source", "start": 0, "end": 21.0, "instruction": "the footage becomes a cartoon"}
    clips = []
    for n, (src, frames, cont) in enumerate(((0, 209, False), (4, 192, False), (1, 175, True), (2, 175, True)), start=1):
        clip = dict(c[src], frames=frames, name=f"e{n}"); clip["continue"] = cont
        clip["prompt"] = clip["prompt"].replace("summary:\n", "summary:\n{edit} ", 1)
        clips.append(clip)
    raw["clips"] = clips
    saved = call(S, P + "/plan", raw, "PUT")
    check("edit plan accepted", not saved.get("validation", {}).get("errors"), saved.get("validation"))
    call(S, P + "/start-video", {"file": "refs/videos/source.mp4"}, "PUT")
    for k in (1, 2, 3, 4):
        job = gen(P, {"clip": k, "branch": "b1"})
        check(f"edit clip {k} generated", job["status"] == "done", (job["status"], job.get("error")))
    plan = plan_core.normalize(call(S, P)["plan"]); rows = plan_core.timeline(plan)
    leaf = call(S, P + "/takes")["clips"][3]["takes"][-1]["id"]
    call(M, "/test/cap_reset", {})
    call(S, P + "/assemble", {"clip": 4, "take": leaf}); job = wait_last(P)
    ex = sorted(call(S, P + "/exports")["exports"], key=lambda e: e["created"])[-1]
    check("edit: assembly done by Encore", job["status"] == "done"
          and json.load(open(f"{root}/projets/ed/exports/{ex['name']}.json")).get("assembled_by") == "ffmpeg", (job["status"], job.get("error")))
    mp4 = f"{root}/projets/ed/exports/{ex['name']}.mp4"
    check("edit: its length", frames_of(mp4) == rows[3]["end"], (frames_of(mp4), rows[3]["end"]))
    tones = [tone(mp4, (rows[i]["visible"] + rows[i]["end"]) / 2 / 24) for i in range(4)]
    check("edit: the original sound over the edited clips, the generated one after", tones == [300, 300, 300, 600], tones)
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
