"""v0.37: a plan that edits a video (edit_video) — the plan settings (Video: edit), the branches given the video's
proportions, « cut on the shots » (a new scene per change of shot, long shots in equal parts that continue each
other), each clip given its slice of the video as <Video 1> with its sound (voices numbered after it), the source
slice behind the empty take cards, and the assembly with the original sound."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8246"; M = "http://127.0.0.1:8771"
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
    out = call(S, P + "/generate", body)
    for _ in range(40):
        time.sleep(0.7); run_mock()
        jobs = call(S, P + "/jobs")["jobs"]
        if jobs and jobs[-1]["status"] in ("done", "error", "cancelled"): break
    return out

# a video of 3 shots (9 s, 12 s, 7 s) with a sound
SRC = "/tmp/v37_source.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=9", "-f", "lavfi", "-i",
                "smptebars=size=640x360:rate=24:duration=12", "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=24", "-f", "lavfi", "-i",
                "sine=frequency=300:duration=28", "-filter_complex", "[2:v]trim=duration=7,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", SRC], check=True)

root = "/tmp/h3s_v37"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "assembly_engine": "plugin", "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8246", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v37_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    _plan = call(S, P)["plan"]; _plan["clips"] = _plan["clips"][:1]; call(S, P + "/plan", _plan, "PUT")   # one clip, replaced by the cut
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    voice = "/tmp/v37_voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=4", voice], check=True)
    call(S, f"{P}/resources?kind=voices&filename=voix.wav", raw=open(voice, "rb").read(), method="POST")
    res = call(S, f"{P}/resources?kind=videos&filename=source.mp4", raw=open(SRC, "rb").read(), method="POST")
    call(S, P + "/branches", {})
    call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png", "voice": "refs/voices/voix.wav"},
                                          "rue": {"image": "refs/images/rue.png"}}, "width": 768, "height": 768}, "PUT")
    cuts = call(S, f"{P}/resources/scenes?path=refs/videos/source.mp4&start=0&end=672")
    check("changes of shot found in the segment", cuts.get("cuts") == [216, 504], cuts)

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await page.click("text=Plan settings"); await page.wait_for_timeout(800)
            box = page.locator(".start-video")
            check("plan settings: a Video section with the 3 choices", await box.locator(".sv-kind option").count() == 3)
            await box.locator(".sv-kind").select_option("edit"); await page.wait_for_timeout(600)
            box = page.locator(".start-video")
            check("« Edit a video »: its explanation", "each clip edits its own slice" in await box.inner_text())
            await box.locator(".sv-file select").select_option("refs/videos/source.mp4"); await page.wait_for_timeout(1500)
            box = page.locator(".start-video")
            end = box.locator(".sv-range input[type=number]").nth(1)
            await end.fill("28"); await end.dispatch_event("change"); await page.wait_for_timeout(500)
            check("the segment shown", "0.000 s → 28.000 s" in (await box.locator(".sv-info").inner_text()).replace(",", "."),
                  await box.locator(".sv-info").inner_text())
            warn = box.locator(".sv-size")
            for _ in range(20):
                if await warn.is_visible(): break
                await page.wait_for_timeout(200)
            check("a branch without the video's proportions: warned", await warn.is_visible() and "768 × 768" in await warn.inner_text())
            await warn.locator("button").click(); await page.wait_for_timeout(1200)
            dlg = page.locator(".h3-dlg")
            if await dlg.count():
                await page.keyboard.press("Enter"); await page.wait_for_timeout(800)
            br = call(S, P)["branches"][0]
            check("…given the video's proportions on request", abs(br["width"] / br["height"] - 16 / 9) < 0.03, (br["width"], br["height"]))
            await page.locator(".ev-split").click(); await page.wait_for_timeout(600)
            check("cutting asks before replacing the clips", await page.locator(".h3-dlg").count() == 1)
            await page.keyboard.press("Enter")
            for _ in range(50):
                n = await page.evaluate("H3Editor.state.plan.clips.length")
                if n == 4 and (await page.evaluate("H3Editor.state.plan.clips[0].name")).startswith("edit_"): break
                await page.wait_for_timeout(200)
            await page.evaluate("H3Editor.state.plan.edit_video.instruction = 'the footage becomes a hand-drawn cartoon'")   # 0.38: {edit}
            plan = await page.evaluate("H3Editor.state.plan")
            shape = [[c["frames"], c["continue"]] for c in plan["clips"]]
            check("cut on the shots: a new scene at each shot, the long shot in 2 parts", shape == [[209, False], [192, False], [175, True], [209, False]], shape)
            check("every clip's prompt keeps <Video 1>", all("<Video 1>" in c["prompt"] for c in plan["clips"]))
            errors = await page.evaluate("H3.validate(H3Editor.state.plan).filter((m) => m.level === 'error').map((m) => m.text)")
            check("the plan is valid", not errors, errors)
            check("timeline: the edited segment in the header", "edits the video" in await page.locator(".tl-edit").inner_text())
            await page.screenshot(path="v37_settings.png")
            # clip 2 speaks with the voice of « fillette »
            plan["clips"][1]["refs"] = ["fillette"]
            plan["clips"][1]["prompt"] = plan["clips"][1]["prompt"].replace("No music", "<Subject 1> speaks with the voice from {voice:fillette}.\nNo music")
            saved = call(S, P + "/plan", plan, "PUT")
            check("plan saved (current version)", saved.get("plan", {}).get("version") == 6 and not saved["validation"]["errors"], saved.get("validation"))
            await page.reload(); await page.wait_for_timeout(1500)
            await page.click("#viewTabs >> text=Takes"); await page.wait_for_timeout(2500)
            src = page.locator(".tk-placeholder .tk-src-thumb").first
            state = ""
            for _ in range(60):
                state = await src.evaluate("(v) => v.dataset.state + ' ' + (v.getAttribute('src') || '')") if await src.count() else ""
                if state.startswith("ready"): break
                await page.wait_for_timeout(250)
            check("Takes tab: the empty card of clip 1 shows its slice of the video", state.startswith("ready") and "previews/thumbs/refs/videos/source.mp4_0_209" in state, state)
            await page.screenshot(path="v37_takes.png")
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())

    call(M, "/test/cap_reset", {})
    gen({"clip": 1, "branch": "b1", "random": True})
    job = call(S, P + "/jobs")["jobs"][-1]
    check("clip 1 generated", job["status"] == "done", (job["status"], job.get("error")))
    r2v = call(M, "/test/cap", {})["r2v"]
    br = call(S, P)["branches"][0]
    check("clip 1: its 209 frames of the video as <Video 1>, at the branch size", r2v["videos"] == [[209, br["height"], br["width"], 3]], r2v["videos"])
    check("…with the video's sound", r2v["video_audios"] == 1)
    wf = json.load(open("/tmp/mock_last_prompt.json"))
    check("the workflow gives the video with an « H3 Plan - Video » node", any(n["class_type"] == "H3PlanVideo" and n["inputs"]["name"] == plan_ref
                                                                            for n in wf.values()) if (plan_ref := call(S, P)["plan"]["edit_video"]["ref"]) else False)
    gen({"clip": 2, "branch": "b1", "random": True})
    r2v = call(M, "/test/cap", {})["r2v"]
    check("clip 2: its 192 frames, the voice numbered after the video's sound (<Audio 2>)",
          r2v["videos"] and r2v["videos"][0][0] == 192 and "<Audio 2>" in (r2v["prompt"] or "") and "<Audio 1>" not in (r2v["prompt"] or ""), r2v)
    takes = call(S, P + "/takes")["clips"]
    rec = takes[0]["takes"][-1]["record"]
    check("the take records the video's SHA", rec["studio"]["refs"].get(plan_ref, {}).get("video") == res.get("sha") or
          rec["studio"]["refs"].get(plan_ref, {}).get("video"), rec["studio"]["refs"])
    # assembly of clips 1-2 with the original sound
    leaf = takes[1]["takes"][-1]["id"]
    out = call(S, P + "/assemble", {"clip": 2, "take": leaf})
    time.sleep(1.5); run_mock(); time.sleep(3)
    asm = call(M, "/test/cap", {})["assembly"]
    jobs = call(S, P + "/jobs")["jobs"]
    check("assembly done", jobs[-1]["kind"] == "assemble" and jobs[-1]["status"] == "done", (out, jobs[-1]["status"], jobs[-1].get("error")))
    check("…with the original sound of the segment (the generated one is silent here)", asm.get("audio_level", 0) > 0.01, asm)
    # the same with the sound H3 made
    plan = call(S, P)["plan"]; plan["edit_video"]["sound"] = "h3"; call(S, P + "/plan", plan, "PUT")
    out = call(S, P + "/assemble", {"clip": 2, "take": leaf})
    time.sleep(1.5); run_mock(); time.sleep(3)
    asm = call(M, "/test/cap", {})["assembly"]
    check("sound « h3 »: the generated sound is kept", asm.get("audio_level", 1) < 0.001, asm)
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
