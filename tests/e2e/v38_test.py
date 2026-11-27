"""v0.38: an edited video with a common instruction ({edit}, written once in the « Common instruction » entry of
the Plan tab, the pictures it names added to the clips) and clips after the segment that continue the video
(segment end on the timeline, 🎞 on the edited clips, no <Video 1> after the segment, no slice of the video for
them, the original sound kept only over the edited part)."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
sys.path.insert(0, ENCORE); from encore import plan_core  # noqa: E402
S = "http://127.0.0.1:8247"; M = "http://127.0.0.1:8771"
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
def gen(body):            # until the job is over: the mock runs what ComfyUI has received
    if body.get("clip", 1) > 1 and "after" not in body:      # 0.42: after the take chosen for the clip before
        body = dict(body, after=call(S, P)["plan_takes"].get(str(body["clip"] - 1)))
    out = call(S, P + "/generate", body)
    for _ in range(40):
        time.sleep(0.7); run_mock()
        jobs = call(S, P + "/jobs")["jobs"]
        if jobs and jobs[-1]["status"] in ("done", "error", "cancelled"): break
    return out

def tone(path, at):
    """0.50: dominant frequency (Hz) of the sound 0.5 s around ``at`` seconds of a video (0 when silent)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(max(0, at - 0.25)), "-t", "0.5", "-i", path, "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw[: len(raw) // 4 * 4], dtype=np.float32)
    if len(x) < 1000 or np.abs(x).max() < 1e-3: return 0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return round(float(np.argmax(spec) * 48000 / len(x)) / 50) * 50
def last_export(root, project):
    folder = f"{root}/projets/{project}/exports"
    return max((os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".mp4")), key=os.path.getmtime)

SRC = "/tmp/v38_source.mp4"     # 3 shots (9 s, 12 s, 7 s) with a sound
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=9", "-f", "lavfi", "-i",
                "smptebars=size=640x360:rate=24:duration=12", "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=24", "-f", "lavfi", "-i",
                "sine=frequency=1000:duration=28", "-filter_complex", "[2:v]trim=duration=7,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", SRC], check=True)

root = "/tmp/h3s_v38"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8247", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v38_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    call(S, f"{P}/resources?kind=videos&filename=source.mp4", raw=open(SRC, "rb").read(), method="POST")
    call(S, P + "/branches/b1", {"width": 1024, "height": 576}, "PUT")
    plan = call(S, P)["plan"]
    plan["files"]["source"] = {"kind": "video"}
    plan["edit_video"] = {"ref": "source", "start": 0, "end": 21.0}      # shots 1 and 2 edited, the rest continues
    plan["clips"] = plan["clips"][:1]                                     # inside the segment: replaced by the cut
    call(S, P + "/plan", plan, "PUT")
    call(S, P + "/start-video", {"file": "refs/videos/source.mp4"}, "PUT")

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await plan_screen(page)
            await page.click("text=Plan settings"); await page.wait_for_timeout(800)
            box = page.locator(".start-video")
            check("settings: one line for the common instruction", await box.locator(".sv-instr").count() == 1)
            await box.locator(".ev-split").click(); await page.wait_for_timeout(500)
            await page.keyboard.press("Enter")
            for _ in range(50):
                if (await page.evaluate("H3Editor.state.plan.clips[0].name")).startswith("edit_"): break
                await page.wait_for_timeout(200)
            plan = await page.evaluate("H3Editor.state.plan")
            check("cut on the shots of 0-21 s: 3 clips that keep <Video 1>",
                  [[c["frames"], c["continue"]] for c in plan["clips"]] == [[209, False], [192, False], [175, True]]
                  and all("<Video 1>" in c["description"] for c in plan["clips"]), [[c["frames"], c["continue"]] for c in plan["clips"]])
            # the common instruction, from the settings line
            await page.locator(".start-video .sv-instr button").click(); await page.wait_for_timeout(600)
            await plan_screen(page)
            check("the instruction entry opens in the Plan tab", await page.locator(".clipitem.instr.sel").count() == 1 and await page.locator("textarea.instr-text").count() == 1)
            check("its palette lists the plan's subjects (not the video)", "@fillette" in await page.locator("#side").inner_text() and "source" not in await page.locator("#side").inner_text())
            ta = page.locator("textarea.instr-text")
            await ta.click()
            await page.keyboard.type("the footage becomes a hand-drawn cartoon; the girl is replaced by @fill")
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter"); await page.wait_for_timeout(400)
            instr = await page.evaluate("H3Editor.state.plan.edit_video.instruction")
            check("@ puts a subject in the instruction", instr and instr.strip().endswith("@fillette"), instr)
            info = await page.locator(".instr-info").inner_text()
            check("…it says which clips use it and which subjects it names", "1–3" in info and "@fillette" in info, info)
            errors = await page.evaluate("H3.validate(H3Editor.state.plan).filter((m) => m.level === 'error').map((m) => m.text)")
            check("the plan is valid (fillette added to the clips by the instruction)", not errors, errors)
            # a clip after the segment
            await plan_screen(page)
            await page.locator(".clipitem").nth(3).click(); await page.wait_for_timeout(300)
            await page.click("#list >> text=+ clip"); await page.wait_for_timeout(600)
            plan = await page.evaluate("H3Editor.state.plan")
            last = plan["clips"][-1]
            check("a clip added after the segment continues the video, without <Video 1>", len(plan["clips"]) == 4 and last["continue"] and "<Video" not in last.get("description", ""), last)
            check("the timeline shows the end of the segment", await page.locator(".tl .segend").count() == 1)
            await plan_screen(page)
            badges = await page.locator("#list .clipitem:not(.instr) .nm").all_inner_texts()
            check("🎞 on the 3 edited clips only", [t.startswith("🎞") for t in badges] == [True, True, True, False], badges)
            await page.click("text=Plan settings"); await page.wait_for_timeout(600)
            line = await page.locator(".start-video .sv-info").inner_text()
            check("settings: which clips edit, which continue", "1–3 edit the video" in line and "4–4 continue it" in line, line)
            await page.locator(".tk-box-head button", has_text="Close").last.click()
            await page.screenshot(path="v38_plan.png")
            saved = call(S, P + "/plan", await page.evaluate("H3Editor.state.plan"), "PUT")
            check("plan saved (version 7) without error", saved.get("plan", {}).get("version") == 7 and not saved["validation"]["errors"], saved.get("validation"))
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())

    plan = call(S, P)["plan"]
    for k in (1, 2, 3, 4):
        call(M, "/test/cap_reset", {})
        gen({"clip": k, "branch": "b1", "random": True})
        job = call(S, P + "/jobs")["jobs"][-1]
        r2v = call(M, "/test/cap", {})["r2v"]
        if k == 1:
            check("clip 1 generated", job["status"] == "done", (job["status"], job.get("error")))
            check("clip 1: the instruction in its prompt, with its picture", "hand-drawn cartoon" in (r2v["prompt"] or "") and "<Picture" in (r2v["prompt"] or "")
                  and "[video editing" in (r2v["prompt"] or ""), r2v["prompt"])
            check("clip 1: its slice of the video", r2v["videos"] and r2v["videos"][0][0] == 209, r2v["videos"])
        if k == 4:
            check("clip 4 (after the segment) generated", job["status"] == "done", (job["status"], job.get("error")))
            check("clip 4: no video given to H3", r2v["videos"] == [] and r2v["video_audios"] == 0, r2v)
    takes = call(S, P + "/takes")["clips"]
    leaf = takes[3]["takes"][-1]["id"]
    call(S, P + "/assemble", {"clip": 4, "take": leaf}); time.sleep(1.5); run_mock(); time.sleep(3)
    jobs = call(S, P + "/jobs")["jobs"]
    check("assembly of the 4 clips done", jobs[-1]["kind"] == "assemble" and jobs[-1]["status"] == "done", (jobs[-1]["status"], jobs[-1].get("error")))
    # 0.50: assembled by Encore (ffmpeg); the segment's sound is at 1000 Hz, the fake preview of clip 4 at 600 Hz
    normal = plan_core.normalize(call(S, P)["plan"]); rows = plan_core.timeline(normal)
    at = lambda i: (rows[i]["visible"] + rows[i]["end"]) / 2 / 24 - plan_core.final_start(normal) / 24  # noqa: E731
    tones = [tone(last_export(root, "rue"), at(i)) for i in range(4)]
    check("…the original sound over the edited part only", tones[:3] == [1000, 1000, 1000] and tones[3] == 600, tones)
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
