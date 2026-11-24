import asyncio, json, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock, plan_screen, takes_screen  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8235"; M = "http://127.0.0.1:8771"
root = "/tmp/h3s_v22"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
shutil.copytree("/tmp/h3s_v20/projets", root + "/projets"); shutil.copytree("/tmp/h3s_v20b/projets/rue", root + "/projets/rue")
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "theme": "light"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8235", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v22_srv.log", "w"))
time.sleep(1.5)
async def close(page):
    for _ in range(3):
        b = page.locator(".tk-modal .tk-box-head button").last
        if await b.count(): await b.click(); await page.wait_for_timeout(250)
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1500, "height": 950}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','robot')"); await page.reload(); await page.wait_for_timeout(1500)
        print("theme", await page.evaluate("document.documentElement.dataset.theme"))
        await plan_screen(page)
        await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(400)
        await page.screenshot(path="v22_plan.png")
        ta = page.locator(".sx-box").nth(1).locator("textarea"); await ta.click(); await page.keyboard.press("End"); await page.keyboard.type(" @"); await page.wait_for_timeout(200)
        await page.screenshot(path="v22_ac.png"); await page.keyboard.press("Escape")
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
        await takes_screen(page); await page.wait_for_timeout(2500)
        await page.screenshot(path="v22_takes.png")
        await page.click("#studioQueueBtn"); await page.wait_for_timeout(800); await page.screenshot(path="v22_queue.png"); await close(page)
        await page.evaluate("H3Studio.kit.openUpscale('b1')"); await page.wait_for_timeout(800); await page.screenshot(path="v22_upscale.png"); await close(page)
        await page.click("#studioThemeBtn"); await page.wait_for_timeout(400)
        print("after toggle", await page.evaluate("document.documentElement.dataset.theme"), json.load(open(cfg)).get("theme"))
        await page.screenshot(path="v22_takes_dark.png")
        print("errors", errs[:5])
        await b.close()
asyncio.run(main()); srv.terminate()
