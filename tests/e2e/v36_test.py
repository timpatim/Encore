"""v0.36: the start video card of the Takes tab — a small copy of the segment only (made once by ffmpeg, the card
says « preparing… » meanwhile), the same <video> kept when the tab is drawn again (a new take does not reload it),
a thumbnail playing without the mouse on it stopped at the next redraw, the copies deleted with the video."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8245"; M = "http://127.0.0.1:8771"
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

root = "/tmp/h3s_v36"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8245", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v36_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
PDIR = f"{root}/projets/rue"
try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    call(S, f"{P}/resources?kind=videos&filename=intro.mp4", raw=open(fixture("v30_intro.mp4"), "rb").read(), method="POST")
    plan = call(S, P)["plan"]
    plan["files"]["intro"] = {"kind": "video"}; plan["start_video"] = {"ref": "intro", "start": 0.5, "end": 6.0}; plan["clips"][0]["continue"] = True
    call(S, P + "/plan", plan, "PUT")
    call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")
    call(S, P + "/start-video", {"file": "refs/videos/intro.mp4"}, "PUT")
    check("thumbnail of a bad segment: refused", "error" in call(S, f"{P}/resources/thumb?path=refs/videos/intro.mp4&start=50&end=10"))

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1500, "height": 900}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await takes_screen(page)
            card = page.locator(".tk-card.tk-startvid")
            await card.wait_for()
            waiting = await card.locator(".tk-sv-wait").count()
            state = ""
            for _ in range(60):
                state = await card.evaluate("(c) => { const v = c.querySelector('video'); return v ? v.dataset.state + ' ' + v.getAttribute('src') : ''; }")
                if state.startswith("ready"): break
                await page.wait_for_timeout(200)
            check("the card plays a small copy of the segment", state.startswith("ready") and "previews/thumbs/refs/videos/intro.mp4_" in state, state)
            # (0.42: the page opens on the Takes screen, the copy may be ready before the first look)
            check("« preparing… » gone once ready", waiting in (0, 1) and await card.locator(".tk-sv-wait").count() == 0, waiting)
            dur = await card.evaluate("(c) => c.querySelector('video').duration")
            check("the copy holds the segment only (5.5 s asked, on the grid)", 4.5 < dur < 5.8, dur)
            await card.evaluate("(c) => { c.querySelector('video').__kept = 1; }")
            # a new take: the tab is drawn again
            call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True}); time.sleep(1.5); run_mock(); time.sleep(1)
            await page.click("text=Refresh"); await page.wait_for_timeout(2500)
            kept = await page.locator(".tk-card.tk-startvid").evaluate("(c) => { const v = c.querySelector('video'); return [v.__kept === 1, v.dataset.state]; }")
            check("after a new take: the same player, nothing reloaded", kept == [True, "ready"], kept)
            check("…and no « preparing… »", await page.locator(".tk-card.tk-startvid .tk-sv-wait").count() == 0)
            # playing while the mouse is elsewhere: stopped at the next redraw
            await page.mouse.move(5, 5)
            await page.locator(".tk-card.tk-startvid").evaluate("(c) => { const v = c.querySelector('video'); v.muted = true; return v.play(); }")
            await page.wait_for_timeout(300)
            await page.click("text=Refresh"); await page.wait_for_timeout(1500)
            paused = await page.locator(".tk-card.tk-startvid").evaluate("(c) => c.querySelector('video').paused")
            check("a thumbnail playing without the mouse on it is stopped", paused)
            # with the mouse on it, it plays
            await page.locator(".tk-card.tk-startvid").hover(); await page.wait_for_timeout(600)
            check("hovering plays it", not await page.locator(".tk-card.tk-startvid").evaluate("(c) => c.querySelector('video').paused"))
            await page.mouse.move(5, 5); await page.wait_for_timeout(400)
            check("leaving stops it", await page.locator(".tk-card.tk-startvid").evaluate("(c) => c.querySelector('video').paused"))
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())

    thumbs = f"{PDIR}/previews/thumbs/refs/videos"
    check("one copy made, kept for next time", len([f for f in os.listdir(thumbs) if f.endswith(".mp4") and ".part" not in f]) == 1, os.listdir(thumbs))
    again = call(S, f"{P}/resources/thumb?path=refs/videos/intro.mp4&start=" + os.listdir(thumbs)[0].split("_")[-2] + "&end=" + os.listdir(thumbs)[0].split("_")[-1][:-4])
    check("asked again: ready at once", again.get("state") == "done", again)
    # 0.42: the start video of a branch with takes is fixed; the branch goes first
    check("the start video cannot change while takes use it", "error" in call(S, P + "/start-video", {"file": None}, "PUT"))
    call(S, P + "/branches/b1?confirm=1", method="DELETE")
    call(S, P + "/start-video", {"file": None}, "PUT")
    out = call(S, f"{P}/resources?path=refs/videos/intro.mp4&confirm=1", method="DELETE")
    check("deleting the video deletes its segment copies", out.get("deleted") and not [f for f in os.listdir(thumbs) if f.startswith("intro.mp4_")], (out, os.listdir(thumbs)))
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
