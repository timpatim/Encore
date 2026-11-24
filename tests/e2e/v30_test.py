"""v0.30/0.31: a plan that starts from a video (start_video) — the project's video (chosen in the plan settings, the
same for every branch), clip 1 continuing the segment (context read from the file and encoded), validity of the takes,
assembly with or without the segment, and the interface (plan settings without « null », timeline, start video
column of the Takes tab, resources)."""
import asyncio, copy, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
sys.path.insert(0, ENCORE)
from encore import plan_core, takes as takes_mod, projects  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8241"; M = "http://127.0.0.1:8771"
OK = []
def check(name, cond, info=""):
    OK.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}
def run_mock():
    try: call(M, "/test/run", {})
    except Exception: pass
def gen(body):
    call(S, P + "/generate", body); time.sleep(1.5); run_mock(); time.sleep(2.5)

root = "/tmp/h3s_v30"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "assembly_engine": "plugin", "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8241", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v30_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
PDIR = f"{root}/projets/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
res = call(S, f"{P}/resources?kind=videos&filename=intro.mp4", raw=open(fixture("v30_intro.mp4"), "rb").read(), method="POST")


def twig():
    """The takes of the selected twig (0.42: a take never becomes invalid)."""
    return {int(k): v for k, v in call(S, P)["plan_takes"].items()}


try:
    check("video imported into refs/videos", res.get("path") == "refs/videos/intro.mp4", res)
    listing = call(S, P)["resources"]
    check("the video is listed with its SHA", [v["name"] for v in listing.get("videos", [])] == ["intro.mp4"] and listing["videos"][0]["sha"], listing.get("videos"))

    plan = call(S, P)["plan"]
    plan["refs"]["intro"] = "start video"
    plan["start_video"] = {"ref": "intro", "start": 0.5, "end": 6.0}
    plan["clips"][0]["continue"] = True
    saved = call(S, P + "/plan", plan, "PUT")
    check("plan saved in the current version without error", saved["plan"]["version"] == plan_core.PLAN_VERSION and not saved["validation"]["errors"], saved.get("validation"))
    call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")
    refused = call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True})
    check("no start video chosen: clip 1 refused with a clear message", "start video: no file chosen" in (refused.get("error") or ""), refused)
    bad = call(S, P + "/start-video", {"file": "refs/videos/none.mp4"}, "PUT")
    check("start video: a file that is not imported is refused", "error" in bad, bad)
    sv = call(S, P + "/start-video", {"file": "refs/videos/intro.mp4"}, "PUT")
    check("start video chosen for the project", sv.get("start_video_file") == "refs/videos/intro.mp4" and call(S, P).get("start_video_file") == "refs/videos/intro.mp4", sv)

    call(M, "/test/cap_reset", {})
    gen({"clip": 1, "branch": "b1", "random": True})
    jobs = call(S, P + "/jobs")["jobs"]
    check("clip 1 continuing the video: generated", jobs and jobs[-1]["status"] == "done", [(j["status"], j.get("error")) for j in jobs])
    wf = json.load(open("/tmp/mock_last_prompt.json"))
    vnode = [n for n in wf.values() if n["class_type"] == "H3PlanVideo"]
    check("the workflow has an « H3 Plan - Video » node in the references", len(vnode) == 1 and vnode[0]["inputs"]["name"] == "intro"
          and vnode[0]["inputs"]["video_file"].endswith(".mp4"), vnode)
    cap = call(M, "/test/cap", {})
    check("the end of the segment was read and encoded (90 frames at the branch size)",
          cap["video_encoded"] and cap["video_encoded"][-1] == [90, 544, 960, 3], cap["video_encoded"])
    check("clip 1 got the 39-frame context", cap["ctx"] and cap["ctx"][0] == 39, cap["ctx"])
    t1 = call(S, P + "/takes")["clips"][0]["takes"]
    sha = listing["videos"][0]["sha"]
    check("the take records the video's SHA", t1 and t1[-1]["record"]["studio"]["refs"]["intro"].get("video") == sha, t1 and t1[-1]["record"]["studio"]["refs"])
    t1 = t1[-1]["id"]
    # 0.33: with the upscale, pass 2 gets the video's context frames back (with their noise mask)
    call(S, P + "/branches/b1", {"upscale": {"model": "minimax_h3_latent_upscaler_3d_fp16.safetensors"}}, "PUT")
    up = dict(call(S, P)["branches"][0]["upscale"], enabled=True)
    gen({"clip": 1, "branch": "b1", "upscale_settings": up})
    wf = json.load(open("/tmp/mock_last_prompt.json"))
    from encore.workflows import latent_frames
    check("upscale, clip 1 continuing the video: the context goes back into pass 2",
          "71" in wf and wf["70"]["inputs"]["amount"] == latent_frames(39) and wf["72"]["inputs"]["video_latent"] == ["71", 0],
          {k: wf.get(k) for k in ("70", "71", "72")})
    up_take = call(S, P + "/takes")["clips"][0]["takes"][-1]["id"]
    check("the upscaled take is done", up_take != t1, up_take)
    call(S, P + "/branches/b1", {"upscale": {"enabled": False}}, "PUT")
    call(S, P + "/selection", {"selection": {"1": t1, "branch": "b1"}}, "PUT")    # the rest of the test goes on from t1
    gen({"clip": 2, "after": t1})
    t2 = call(S, P + "/takes")["clips"][1]["takes"][-1]["id"]
    check("the twig: clip 1 then clip 2", twig() == {1: t1, 2: t2}, twig())

    # assembly: the segment opens the video
    call(S, P + "/assemble", {"clip": 2, "take": t2}); time.sleep(1.5); run_mock(); time.sleep(3)
    a = [j for j in call(S, P + "/jobs")["jobs"] if j["kind"] == "assemble"]
    check("assembly with the segment done", a and a[-1]["status"] == "done", [(j["status"], j.get("error")) for j in a])
    asm = call(M, "/test/cap", {})["assembly"]
    normal = plan_core.normalize(json.loads(json.dumps(call(S, P)["plan"])))
    end2 = plan_core.timeline(normal)[1]["end"]
    check("assembled: 1 piece of video + 2 clips", asm.get("input_count") == 3, asm)
    check("sound from the start of the segment to the end of clip 2",
          abs(asm.get("audio_samples", 0) / asm.get("audio_rate", 1) - end2 / 24) < 0.05, (asm, end2 / 24))

    # springboard only: same takes, assembly without the segment
    plan = call(S, P)["plan"]; plan["start_video"]["in_assembly"] = False
    saved = call(S, P + "/plan", plan, "PUT")
    check("« not in the video »: an assembly setting, free to change", "error" not in saved and saved["plan"]["start_video"]["in_assembly"] is False, saved.get("error"))
    call(S, P + "/assemble", {"clip": 2, "take": t2}); time.sleep(1.5); run_mock(); time.sleep(3)
    asm = call(M, "/test/cap", {})["assembly"]
    first = plan_core.timeline(plan_core.normalize(json.loads(json.dumps(plan))))[0]["raw_start"]
    check("assembled without the segment: 2 clips, sound from clip 1's start",
          asm.get("input_count") == 2 and abs(asm["audio_samples"] / asm["audio_rate"] - (end2 - first) / 24) < 0.05, (asm, first))

    # 0.42: with takes, the start video and its segment are fixed (another branch is made to change them)
    shutil.copy(fixture("v30_intro.mp4"), "/tmp/intro_b.mp4"); open("/tmp/intro_b.mp4", "ab").write(b"\0" * 64)
    other = call(S, f"{P}/resources?kind=videos&filename=intro_b.mp4", raw=open("/tmp/intro_b.mp4", "rb").read(), method="POST")
    out = call(S, P + "/start-video", {"file": other["path"]}, "PUT")
    check("another start video refused once there are takes", "error" in out and call(S, P)["start_video_file"] == "refs/videos/intro.mp4", out)
    plan["start_video"]["end"] = 7.0
    out = call(S, P + "/plan", plan, "PUT")
    check("another segment refused once there are takes", "error" in out, out)
    plan["start_video"]["end"] = 6.0
    check("the twig is still there", twig() == {1: t1, 2: t2}, twig())

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
            page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await plan_screen(page)
            # Plan tab: the segment before clip 1 on the timeline
            block = page.locator(".tl .block.startvid")
            check("timeline: start video block", await block.count() == 1 and "intro" in await block.inner_text())
            check("timeline: hatched (not in the final video)", "out" in (await block.get_attribute("class") or ""))
            # plan settings: the start video section, with the branch's file in a player
            await block.click(); await page.wait_for_timeout(800)
            box = page.locator(".start-video")
            check("plan settings: start video section", await box.count() == 1)
            check("plan settings: no « null » written", "null" not in await box.inner_text(), await box.inner_text())
            # 0.43: the video file is chosen in the project settings; the plan settings keep the branch's segment
            check("plan settings: no file list (project settings)", await box.locator(".sv-file").count() == 0)
            check("plan settings: player on the project's video", await box.locator("video.sv-player").count() == 1
                  and "intro" in (await box.locator("video.sv-player").get_attribute("src") or ""))
            check("plan settings: the segment is greyed (the branch has takes)", await box.locator(".sv-range input").first.is_disabled())
            check("the start video's reference is not in the plan's reference list",
                  await page.locator("#refRows input.rname[value='intro']").count() == 0)
            info = await box.locator(".sv-info").inner_text()
            check("plan settings: segment used shown on the grid", "124 frames" in info and "0.833" in info and "6.000" in info and "moves forward" in info, info)
            await page.screenshot(path="v30_plan_settings.png")
            # the « ⇤ here » button: greyed too, with the reason
            here = box.locator("button", has_text="⇤")
            check("« ⇤ here » greyed with the reason", await here.is_disabled() and "Fixed" in (await here.get_attribute("title") or ""), await here.get_attribute("title"))
            await page.locator(".tk-box-head button", has_text="Close").last.click(); await page.wait_for_timeout(300)
            # Takes tab: not in the final video, no start video column
            await takes_screen(page); await page.wait_for_timeout(1500)
            check("Takes tab: no start video column while it is not in the video", await page.locator(".tk-card.tk-startvid").count() == 0)
            plan_now = call(S, P)["plan"]; plan_now["start_video"]["in_assembly"] = True
            call(S, P + "/plan", plan_now, "PUT")
            await page.reload(); await page.wait_for_timeout(1500)
            await takes_screen(page); await page.wait_for_timeout(1500)
            card = page.locator(".tk-card.tk-startvid")
            check("Takes tab: a start video card before clip 1", await card.count() == 1 and "intro.mp4" in await card.inner_text(), await card.count())
            head = await page.locator(".tk-col-head.tk-col-start").inner_text()
            check("Takes tab: « Start video » column header", "Start video" in head, head)
            cbox = await card.bounding_box(); t1box = await page.locator(f".tk-card[data-take='{t1}']").bounding_box()
            check("the column comes before clip 1", cbox and t1box and cbox["x"] + cbox["width"] < t1box["x"], (cbox, t1box))
            check("clip 1's takes (normal and upscaled) are linked to the start video", await page.locator("path.tk-link.start").count() == 2)
            check("the branch header no longer lists the video", "intro.mp4" not in await page.locator(".tk-band-head").first.inner_text())
            await page.screenshot(path="v31_takes_column.png")
            await card.click(); await page.wait_for_timeout(800)
            check("a click on it opens the start video settings", await page.locator(".start-video").count() == 1)
            await page.locator(".tk-box-head button", has_text="Close").last.click(); await page.wait_for_timeout(300)
            # Resources: the videos section
            await page.click("text=Resources…"); await page.wait_for_timeout(700)
            check("resources: videos section with a player", await page.locator(".tk-modal video.studio-res-video").count() == 2)
            await page.screenshot(path="v30_resources.png")
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
