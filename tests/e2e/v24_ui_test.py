import asyncio, json, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8237"
cfg = "/tmp/h3s_v24/config.json"
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8237", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v24_ui_srv.log", "w"))
time.sleep(1.5)
# take of clip 1 back to its real size (the API test changed it)
import glob
for f in glob.glob("/tmp/h3s_v24/projets/rue/takes/clip_001/*.json"):
    r = json.load(open(f)); r["width"] = 960; json.dump(r, open(f, "w"))
req = urllib.request.Request(S + "/api/projects/rue/branches", data=b"{}", method="POST", headers={"Content-Type": "application/json", "X-Encore": "1"}); urllib.request.urlopen(req)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1300)
        await page.click("#viewTabs >> text=Prises"); await page.wait_for_timeout(900)
        await page.screenshot(path="v24_takes.png")
        print("asm buttons", await page.eval_on_selector_all(".tk-asm-btn", "e => e.map(x => [x.textContent, x.className])"))
        # clip plan window
        await page.click(".tk-col-head >> nth=1 >> .tk-clipplan"); await page.wait_for_timeout(500)
        await page.screenshot(path="v24_clipplan.png"); await page.click(".tk-plan-modal >> text=Fermer"); await page.wait_for_timeout(300)
        # take plan window (clip 1: frames and prompt changed)
        card = page.locator(".tk-card >> nth=0"); await card.hover(); await card.locator(".tk-plan-btn").click(); await page.wait_for_timeout(800)
        await page.screenshot(path="v24_takeplan.png")
        print("changed rows", await page.eval_on_selector_all(".tk-plan-row.changed label", "e => e.map(x => x.textContent)"),
              "ins", await page.eval_on_selector_all(".tk-diff-ins", "e => e.map(x => x.textContent.slice(0, 40))"))
        await page.click(".tk-plan-modal >> text=Fermer"); await page.wait_for_timeout(300)
        # invalid assembly from clip 2 take
        card = page.locator(".tk-card >> nth=1"); await card.hover(); await card.locator(".tk-asm-btn").click(); await page.wait_for_timeout(900)
        await page.screenshot(path="v24_confirm.png")
        print("dialog", (await page.inner_text(".h3-dialog, .h3dlg, [class*=dialog]"))[:400] if await page.query_selector(".h3-dialog, .h3dlg, [class*=dialog]") else None)
        await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
        # fold branch 1, then branch 2
        await page.click(".tk-band-head >> nth=0 >> .tk-fold"); await page.wait_for_timeout(600)
        await page.screenshot(path="v24_folded.png")
        print("folded heads", await page.eval_on_selector_all(".tk-band-head.folded", "e => e.map(x => x.innerText.replace(/\\n/g,' | '))"),
              "cards", await page.locator(".tk-card").count(), "stored", await page.evaluate("localStorage.getItem('encore.folded.rue')"))
        await page.reload(); await page.wait_for_timeout(1300); await page.click("#viewTabs >> text=Prises"); await page.wait_for_timeout(900)
        print("after reload folded", await page.locator(".tk-band-head.folded").count())
        await page.click(".tk-band-head.folded .tk-fold"); await page.wait_for_timeout(600)
        print("unfolded cards", await page.locator(".tk-card").count())
        # light theme check of the take plan
        await page.evaluate("H3Theme.set && H3Theme.set('light')"); await page.wait_for_timeout(300)
        card = page.locator(".tk-card >> nth=0"); await card.hover(); await card.locator(".tk-plan-btn").click(); await page.wait_for_timeout(800)
        await page.screenshot(path="v24_takeplan_light.png")
        print("errors", errs)
        await b.close()
try: asyncio.run(main())
finally: srv.terminate()
