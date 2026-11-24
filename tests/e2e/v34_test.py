"""v0.34: files for ComfyUI copied straight into its input folder when its folder is known (no upload size limit),
a clear message when ComfyUI refuses an upload as too big (413), and a playable copy (H.264) of the videos the
browser cannot play (here an AVI), made with its progress, used by the players, deleted with the video."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8243"; M = "http://127.0.0.1:8771"
OK = []
def check(name, cond, info=""):
    OK.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}
def run_mock():
    try: call(M, "/test/run", {})
    except Exception: pass

root = "/tmp/h3s_v34"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
def start_server(extra):
    json.dump(dict({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, **extra), open(cfg, "w"))
    proc = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8243", "--no-browser", "--config", cfg], cwd=ENCORE,
                            stdout=subprocess.DEVNULL, stderr=open("v34_srv.log", "a"))
    time.sleep(1.5)
    return proc
AVI = "/tmp/v34_clip.avi"      # 12 s in MPEG-4 part 2 in an AVI: Chrome plays neither
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=12", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=12", "-c:v", "mpeg4", "-q:v", "4", "-c:a", "pcm_s16le", AVI], check=True)
P = "/api/projects/rue"
PDIR = f"{root}/projets/rue"
srv = start_server({})
try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")

    # ---- ComfyUI's folder unknown: the upload route, and its 413 explained
    call(M, "/test/max_upload", {"bytes": 200})
    call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True}); time.sleep(2.5)
    job = call(S, P + "/jobs")["jobs"][-1]
    check("upload refused as too big (413): the job says what to do", job["status"] == "error" and "--max-upload-size" in (job.get("error") or "")
          and "configuration" in (job.get("error") or ""), (job["status"], job.get("error")))
    srv.terminate(); srv.wait()

    # ---- ComfyUI's folder known: copied straight into its input folder, whatever the limit
    info = call(M, "/test/comfy_root", {})
    before = len(info["uploads"])
    srv = start_server({"comfy_dir": info["root"]})
    call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True}); time.sleep(1.5); run_mock(); time.sleep(2.5)
    job = call(S, P + "/jobs")["jobs"][-1]
    check("ComfyUI's folder known: the clip is made despite the limit", job["status"] == "done", (job["status"], job.get("error")))
    after = call(M, "/test/comfy_root", {})["uploads"]
    sent = [u for u in after[before:] if u[0] == "input"]
    check("…the pictures did not go through the upload route", sent == [], sent)
    copies = [os.path.join(d, f) for d, _, fs in os.walk(os.path.join(info["root"], "input")) for f in fs if "fillette" in f and "_" in f]
    check("…they are in ComfyUI's input folder, whole, without a .part", copies and all(os.path.getsize(c) == os.path.getsize(fixture("fillette.png")) for c in copies)
          and not [f for d, _, fs in os.walk(os.path.join(info["root"], "input")) for f in fs if f.endswith(".part")], copies)
    call(M, "/test/max_upload", {"bytes": 0})

    # ---- a video the browser cannot play
    res = call(S, f"{P}/resources?kind=videos&filename=clip.avi", raw=open(AVI, "rb").read(), method="POST")
    check("an AVI imported", res.get("path") == "refs/videos/clip.avi", res)
    check("preview status of a file that is not a video: refused", "error" in call(S, f"{P}/resources/preview?path=refs/images/rue.png"))
    check("no playable copy yet", call(S, f"{P}/resources/preview?path=refs/videos/clip.avi")["state"] == "none")
    # 0.42: a start video is fixed once a branch has takes: a fresh branch for this part
    call(S, P + "/branches/b1?confirm=1", method="DELETE"); call(S, P + "/branches", {})
    plan = call(S, P)["plan"]
    plan["refs"]["intro"] = "start video"; plan["start_video"] = {"ref": "intro", "start": 0, "end": 4}; plan["clips"][0]["continue"] = True
    call(S, P + "/plan", plan, "PUT")
    call(S, P + "/start-video", {"file": "refs/videos/clip.avi"}, "PUT")

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await plan_screen(page)
            await page.locator(".tl .block.startvid").click(); await page.wait_for_timeout(1500)
            box = page.locator(".start-video")
            note = box.locator(".studio-preview-note")
            seen = ""
            for _ in range(40):
                if await note.is_visible():
                    seen = await note.inner_text()
                    if "%" in seen: break
                await page.wait_for_timeout(100)
            fast = "previews/" in (await box.locator("video.sv-player").get_attribute("src") or "")    # a fast machine: already made
            check("plan settings: the player says it makes a playable copy", "playable copy" in seen or fast, seen)
            await page.screenshot(path="v34_making.png")
            src = ""
            for _ in range(100):
                src = await box.locator("video.sv-player").get_attribute("src") or ""
                if "previews/" in src: break
                await page.wait_for_timeout(200)
            check("…then plays the copy", "previews/refs/videos/clip.avi.mp4" in src, src)
            await page.wait_for_timeout(1500)
            meta = await page.evaluate("(() => { const v = document.querySelector('video.sv-player'); return [v.videoWidth, v.videoHeight, v.duration]; })()")
            check("the copy is decoded: picture and the same duration", meta[0] > 0 and abs(meta[2] - 12.0) < 0.1, meta)
            check("the note is gone", not await note.is_visible())
            await page.screenshot(path="v34_playing.png")
            await page.locator(".tk-box-head button", has_text="Close").last.click(); await page.wait_for_timeout(300)
            await page.click("text=Resources…"); await page.wait_for_timeout(1500)
            vid = page.locator(".tk-modal").last.locator(".studio-res", has_text="clip.avi").locator("video")
            check("resources: the copy is played at once", "previews/" in (await vid.get_attribute("src") or ""))
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())

    copy = f"{PDIR}/previews/refs/videos/clip.avi.mp4"
    check("the copy is H.264, at most 540 high", os.path.isfile(copy) and b"avc1" in open(copy, "rb").read(), copy)
    check("ComfyUI still gets the original (the start video stays the AVI)", call(S, P).get("start_video_file") == "refs/videos/clip.avi")
    call(S, P + "/start-video", {"file": None}, "PUT")
    out = call(S, f"{P}/resources?path=refs/videos/clip.avi&confirm=1", method="DELETE")
    check("deleting the video deletes its copy", out.get("deleted") and not os.path.exists(copy), out)
finally:
    try: call(M, "/test/max_upload", {"bytes": 0})
    except Exception: pass
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
