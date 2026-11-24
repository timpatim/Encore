import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock, plan_screen, takes_screen  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8230"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"} if body is not None else {"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
root = "/tmp/h3s_v20b"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8230", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v20b_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for kind, f in (("images", fixture("fillette.png")), ("images", fixture("rue.png")), ("voices", fixture("v20_song.wav"))):
    call(S, f"{P}/resources?kind={kind}&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png", "voice": "refs/voices/v20_song.wav"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")
orig = [c["prompt"] for c in call(S, P)["plan"]["clips"]]
# the whole branch, then a second take of clip 5 made with an extra LoRA and no upscale (0.42: set for the take)
def drain():
    for _ in range(40):
        time.sleep(0.8)
        try: call(M, "/test/run", {})
        except Exception: pass
        time.sleep(0.8)
        if not [j for j in call(S, P + "/jobs")["jobs"] if j["status"] in ("queued", "running", "harvest")]: break
call(S, P + "/branches/b1/fill", {"dry_run": False, "assemble": False}); drain()
t4 = call(S, P)["plan_takes"]["4"]
call(S, P + "/generate", {"clip": 5, "after": t4, "loras": [{"name": "perso/style_07.safetensors", "strength": 0.6}], "upscale_settings": {"enabled": False}}); drain()
print("takes", {k: len(v) for k, v in call(S, P + "/takes")["takes"].items()} if isinstance(call(S, P + "/takes").get("takes"), dict) else "?")
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1500, "height": 950}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
        await plan_screen(page, master=True)          # the master plan: every clip can be edited
        same = []
        for i in range(5):
            await page.locator(".clipitem").nth(i).click(); await page.wait_for_timeout(250)
            same.append(await page.evaluate(f"H3Editor.state.plan.clips[{i}].prompt") == orig[i])
        print("prompts untouched by viewing", same)
        await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(300)
        print("subject chips", await page.eval_on_selector_all("#side .sx-chipS", "e => e.map(x => x.textContent)"))
        print("extra lines shown", await page.locator("text=Autres lignes").count(), "| retention raw", await page.locator(".sx-box").nth(2).locator(".sx-ret").count() == 0)
        print("custom opening note", await page.locator("text=rédigée à la main").count())
        print("voice buttons", await page.locator("#side button:has-text('voix')").count(), "| dialogue chips", await page.eval_on_selector_all("#side .sx-chipD", "e => e.map(x => x.textContent)"))
        # @ menu shows the replies; pick one in shot 1
        shot = page.locator(".sx-shot textarea").first
        await shot.click(); await page.keyboard.press("Control+End"); await page.keyboard.type(" @répl")
        await page.wait_for_timeout(200)
        items = await page.eval_on_selector_all(".sx-ac-item", "e => e.map(x => x.textContent)")
        print("ac", items[:3])
        await page.keyboard.press("Escape")
        await page.screenshot(path="v20b_free.png")
        # Prises: ↻ « nouvelle prise » opens the launch panel, set like the take (its LoRA, its upscale)
        await takes_screen(page); await page.wait_for_timeout(1600)
        buttons = page.locator(".tk-retake")
        print("retake buttons", await buttons.count())
        for k in range(await buttons.count()):
            await buttons.nth(k).evaluate("e => e.click()"); await page.wait_for_timeout(1200)
            title = await page.locator("#launchPanel .launch-head b").text_content()
            vals = await page.eval_on_selector_all("#launchPanel .studio-lora select", "e => e.map(x => x.value)")
            up = await page.eval_on_selector("#launchPanel .studio-up-line", "e => e.textContent")
            print("launch panel:", title, "| loras", vals, "| upscale", up[:60])
            if vals: await page.screenshot(path="v20b_retake.png")
            await page.click("#launchPanel .launch-foot button:has-text('Annuler')"); await page.wait_for_timeout(400)
        # pick filter on a LoRA select (branch LoRA dialog)
        await page.evaluate("H3Takes.state.studio.openBranchLoras('b1')"); await page.wait_for_timeout(800)
        await page.click(".tk-modal button:has-text('+ ajouter un LoRA')"); await page.wait_for_timeout(200)
        sel = page.locator(".tk-modal .studio-lora select").first
        bx = await sel.bounding_box(); await page.mouse.click(bx["x"] + 20, bx["y"] + 8); await page.wait_for_timeout(200)
        print("pick open", await page.locator(".h3-pick-pop").count(), await page.locator(".h3-pick-count").text_content())
        await page.keyboard.type("style 1")
        print("filtered", await page.eval_on_selector_all(".h3-pick-item", "e => e.map(x => x.textContent)"))
        await page.screenshot(path="v20b_pick.png")
        await page.keyboard.press("ArrowDown"); await page.keyboard.press("Enter"); await page.wait_for_timeout(500)
        print("chosen", await sel.input_value())
        br = call(S, P)["branches"][0]
        print("branch loras saved", br.get("loras"))
        print("errors", errs[:5])
        await b.close()
asyncio.run(main()); srv.terminate()
