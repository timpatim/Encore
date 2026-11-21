import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
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
CONT = "The incoming performer motion, camera trajectory, body momentum, facial state, lighting, environment and object state continue uninterrupted from the protected video context."
def comp(parts):
    names = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
    return "\n\n".join(f"{n}\n{p}" for n, p in zip(names, parts))
p1 = comp(["<Subject 1> is the small robot whose body comes from {picture:robot}.\n<Subject 2> is the beach shown in {picture:beach}.",
           "[reference generation] <Subject 1> walks on <Subject 2>.",
           "<Subject 1> (appears throughout [Shot 1]): fully_preserved - same robot\n<Subject 2> (appears throughout [Shot 1]): fully_preserved - same place",
           "Warm cinematic music video.\n[Shot 1] Wide shot: <Subject 1> walks along the pier of <Subject 2>.",
           "Soft waves.", "Gentle opening of the song; the visible performance stays synchronized to it."])
p2 = comp(["<Subject 1> is the small robot whose body comes from {picture:robot}.\n<Subject 2> is the beach shown in {picture:beach}.",
           "[reference generation] <Subject 1> dances.",
           "<Subject 1> (appears throughout [Shot 1]): fully_preserved - same robot\n<Subject 2> (appears throughout [Shot 1]): fully_preserved - same place",
           "Warm cinematic music video.\n[Shot 1] " + CONT + " <Subject 1> sways on <Subject 2>.",
           "Soft waves.", "Second chorus."])
plan = {"version": 3, "project": "robot", "mode": "music_video", "refs": {"robot": "small rusty robot", "beach": "beach at golden hour"},
        "context_frames": 39, "crossfade_frames": 0, "song": {"file": "song.wav", "duration_seconds": 40},
        "clips": [{"name": "intro", "frames": 209, "continue": False, "refs": ["robot", "beach"], "prompt": p1, "lyrics": "le soleil descend"},
                  {"name": "chorus", "frames": 226, "continue": True, "refs": ["robot", "beach"], "prompt": p2, "lyrics": "on danse au bord de l'eau"}]}
P = "/api/projects/robot"
call(S, "/api/projects", {"name": "robot", "mode": "music_video"})
call(S, P + "/import-plan?filename=robot.json", raw=json.dumps(plan).encode(), method="POST")
for kind, f in (("images", fixture("v20_robot.png")), ("images", fixture("v20_beach.png")), ("songs", fixture("v20_song.wav"))):
    call(S, f"{P}/resources?kind={kind}&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/branches", {})
call(S, P + "/branches/b1", {"refs": {"robot": {"image": "refs/images/v20_robot.png"}, "beach": {"image": "refs/images/v20_beach.png"}}, "song": "refs/songs/v20_song.wav"}, "PUT")
before = call(S, P)["plan"]["clips"][1]["prompt"]

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
        page = await b.new_page(viewport={"width": 1500, "height": 950}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None); page.on("response", lambda r: errs.append("404 " + r.url) if r.status == 404 else None)
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','robot')"); await page.reload(); await page.wait_for_timeout(1500)
        # clip 2
        await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(500)
        await page.screenshot(path="v20_plan.png", full_page=False)
        print("subjects chips", await page.eval_on_selector_all("#side .sx-chipS", "e => e.map(x => x.textContent)"))
        print("thumbs", await page.locator("#side img.sx-thumb").count())
        print("lock", (await page.locator(".sx-lock").nth(1).text_content())[:40])
        print("summary display", await page.locator(".sx-box").nth(1).locator("textarea").input_value())
        # nothing changed yet: prompt identical
        cur = await page.evaluate("H3Editor.state.plan.clips[1].prompt")
        print("unchanged prompt", cur == before)
        # @ completion in summary
        ta = page.locator(".sx-box").nth(1).locator("textarea")
        await ta.click(); await page.keyboard.press("End"); await page.keyboard.type(" with @be")
        await page.wait_for_timeout(200)
        print("ac items", await page.eval_on_selector_all(".sx-ac-item", "e => e.map(x => x.textContent)"))
        await page.screenshot(path="v20_ac.png")
        await page.keyboard.press("Enter"); await page.wait_for_timeout(200)
        print("summary now", await ta.input_value())
        print("prompt summary", (await page.evaluate("H3.parseSections(H3Editor.state.plan.clips[1].prompt)[1]")))
        # drag a reference chip into the soundscape
        snd = page.locator(".sx-box").nth(4).locator("textarea")
        await page.locator("#side .sx-chipR").first.drag_to(snd)
        await page.wait_for_timeout(200)
        print("after drop", await snd.input_value())
        # rename a subject: prompt unchanged, names change
        name_in = page.locator(".sx-name").first
        p_before = await page.evaluate("H3Editor.state.plan.clips[1].prompt")
        await name_in.fill("bot"); await name_in.press("Enter"); await page.wait_for_timeout(300)
        print("rename keeps prompt", p_before == await page.evaluate("H3Editor.state.plan.clips[1].prompt"), await page.evaluate("H3Editor.state.plan.clips[1]._subjects"))
        print("summary after rename", await page.locator(".sx-box").nth(1).locator("textarea").input_value())
        # move subject 2 up
        await page.locator(".sx-subject").nth(1).locator("button[title^='monter']").click(); await page.wait_for_timeout(300)
        print("after move sec0", await page.evaluate("H3.parseSections(H3Editor.state.plan.clips[1].prompt)[0]"))
        print("after move summary", await page.evaluate("H3.parseSections(H3Editor.state.plan.clips[1].prompt)[1]"))
        # toggle continue off: sentence becomes the lead-in
        await page.locator(".fields input[type=checkbox]").uncheck(); await page.wait_for_timeout(300)
        print("detailed after toggle", (await page.evaluate("H3.parseSections(H3Editor.state.plan.clips[1].prompt)[3]"))[:140])
        # song card
        print("song range", await page.locator(".song-range").text_content())
        await page.click("button[data-kind=new]"); await page.wait_for_timeout(1200)
        print("playing", await page.evaluate("document.querySelector('.song-head').style.display"), await page.locator(".song-clock").text_content())
        await page.screenshot(path="v20_song.png")
        await page.click("button[data-kind=new]")
        # add clip: inherits
        await page.click(".listbar button:has-text('+ clip')"); await page.wait_for_timeout(500)
        np = await page.evaluate("H3.parseSections(H3Editor.state.plan.clips[2].prompt)")
        print("new clip", await page.evaluate("[H3Editor.state.plan.clips.length, H3Editor.state.plan.clips[2].continue, H3Editor.state.plan.clips[2]._subjects]"))
        print("new clip sec0 kept", np[0][:60], "| sum", np[1], "| det", np[3][:60], "| snd", np[4], "| music", repr(np[5]))
        # settings dialog
        await page.click("#btnPlanSettings"); await page.wait_for_timeout(300)
        print("settings boxes", await page.eval_on_selector_all(".plan-settings h2", "e => e.map(x => x.textContent)"))
        await page.screenshot(path="v20_settings.png")
        await page.click(".tk-box-head button:has-text('Fermer')")
        print("errors", errs[:5])
        await b.close()
asyncio.run(main())
srv.terminate()
