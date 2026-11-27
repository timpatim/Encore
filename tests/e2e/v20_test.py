import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock, plan_screen, takes_screen  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8228"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"} if body is not None else {"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
root = "/tmp/h3s_v20"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8228", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v20_srv.log","w"))
time.sleep(1.5)
plan = {"version": 7, "project": "robot", "mode": "music_video",
        "files": {"robot": {"kind": "image", "file": "refs/images/v20_robot.png"}, "beach": {"kind": "image", "file": "refs/images/v20_beach.png"}},
        "subjects": {"robot": {"kind": "person", "description": "the small robot", "pictures": [{"file": "robot", "role": "body"}]},
                     "beach": {"kind": "place", "description": "a beach at golden hour", "pictures": [{"file": "beach"}]}},
        "context_frames": 39, "crossfade_frames": 0, "song": {"file": "song.wav", "duration_seconds": 40},
        "clips": [{"name": "intro", "frames": 209, "continue": False, "lyrics": "le soleil descend", "summary": "@robot walks on @beach.",
                   "description": "Warm cinematic music video.\n[Shot 1] Wide shot: @robot walks along the pier of @beach.", "soundscape": "Soft waves.",
                   "music": "Gentle opening of the song; the visible performance stays synchronized to it."},
                  {"name": "chorus", "frames": 226, "continue": True, "lyrics": "on danse au bord de l'eau", "summary": "@robot dances.",
                   "description": "Warm cinematic music video.\n[Shot 1] @robot sways on @beach.", "soundscape": "Soft waves.", "music": "Second chorus.",
                   "subjects": [{"name": "beach", "keep": "partial"}]}]}
P = "/api/projects/robot"
call(S, "/api/projects", {"name": "robot", "mode": "music_video"})
call(S, P + "/import-plan?filename=robot.json", raw=json.dumps(plan).encode(), method="POST")
for kind, f in (("images", fixture("v20_robot.png")), ("images", fixture("v20_beach.png")), ("songs", fixture("v20_song.wav"))):
    call(S, f"{P}/resources?kind={kind}&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/essence", {"song": "refs/songs/v20_song.wav"}, "PUT")      # 0.43: the song is the project's
before = call(S, P)["plan"]["clips"][1]

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
        page = await b.new_page(viewport={"width": 1500, "height": 950}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None); page.on("response", lambda r: errs.append("404 " + r.url) if r.status == 404 else None)
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','robot')"); await page.reload(); await page.wait_for_timeout(1500)
        await plan_screen(page)
        # clip 2
        await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(500)
        await page.screenshot(path="v20_plan.png", full_page=False)
        print("library subjects", await page.eval_on_selector_all("#side .sx-lib-subject .sx-chipS", "e => e.map(x => x.textContent)"))
        print("library thumbs", await page.locator("#side .sx-files img.sx-thumb").count())
        print("clip subjects", await page.eval_on_selector_all("#sxUses .sx-use", "e => e.map(x => x.dataset.subject)"))
        print("keep of beach", await page.locator('.sx-use[data-subject="beach"] .sx-keep').input_value())
        print("summary", await page.locator('textarea[data-sec="summary"]').input_value())
        cur = await page.evaluate("JSON.stringify(H3Editor.state.plan.clips[1])")
        print("unchanged clip", json.loads(cur) == before)
        # @ completion in summary
        ta = page.locator('textarea[data-sec="summary"]')
        await ta.click(); await page.keyboard.press("End"); await page.keyboard.type(" with @be")
        await page.wait_for_timeout(200)
        print("ac items", await page.eval_on_selector_all(".sx-ac-item", "e => e.map(x => x.textContent)"))
        await page.screenshot(path="v20_ac.png")
        await page.keyboard.press("Enter"); await page.wait_for_timeout(200)
        print("summary now", await ta.input_value())
        # drag a subject chip of the library into the soundscape
        snd = page.locator('textarea[data-sec="soundscape"]')
        await page.locator("#side .sx-lib-subject .sx-chipS").first.drag_to(snd)
        await page.wait_for_timeout(200)
        print("after drop", await snd.input_value())
        # rename a subject in its window: every text follows
        await page.locator('#side .sx-lib-subject[data-subject="robot"] .sx-edit').click(); await page.wait_for_timeout(300)
        await page.fill(".sx-sname", "bot"); await page.click(".sx-save"); await page.wait_for_timeout(400)
        print("after rename", await page.evaluate("[Object.keys(H3Editor.state.plan.subjects), H3Editor.state.plan.clips[0].summary, H3Editor.state.plan.clips[1].description]"))
        # the composed prompt (server) names the subjects with numbers
        await page.wait_for_timeout(800)
        await page.click(".sx-tab-h3"); await page.wait_for_timeout(600)
        h3 = await page.input_value("textarea.sx-h3")
        print("composed", "[video continuation + reference generation]" in h3, "partially_preserved" in h3, "@" not in h3)
        await page.click("button:has-text('Champs')"); await page.wait_for_timeout(300)
        # toggle continue off: only the link changes (the opening sentence is the server's)
        await page.locator(".fields input[type=checkbox]").uncheck(); await page.wait_for_timeout(300)
        print("description after toggle", (await page.evaluate("H3Editor.state.plan.clips[1].description"))[:60])
        # song card
        print("song range", await page.locator(".song-range").text_content())
        await page.click("button[data-kind=new]"); await page.wait_for_timeout(1200)
        print("playing", await page.evaluate("document.querySelector('.song-head').style.display"), await page.locator(".song-clock").text_content())
        await page.screenshot(path="v20_song.png")
        await page.click("button[data-kind=new]")
        # add clip: inherits the subject settings and the style
        await page.click(".listbar button:has-text('+ clip')"); await page.wait_for_timeout(500)
        print("new clip", await page.evaluate("[H3Editor.state.plan.clips.length, H3Editor.state.plan.clips[2].continue, H3Editor.state.plan.clips[2].subjects, H3Editor.state.plan.clips[2].description, H3Editor.state.plan.clips[2].music]"))
        # settings dialog: no references any more
        await page.click("#btnPlanSettings"); await page.wait_for_timeout(300)
        print("settings boxes", await page.eval_on_selector_all(".plan-settings h2", "e => e.map(x => x.textContent)"))
        await page.screenshot(path="v20_settings.png")
        await page.click(".tk-box-head button:has-text('Fermer')")
        print("errors", errs[:5])
        await b.close()
asyncio.run(main())
srv.terminate()
