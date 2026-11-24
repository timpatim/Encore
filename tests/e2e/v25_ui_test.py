"""v0.25 UI: buttons of an invalidated take, ▶▶ label while generating, Encore opened from the local network."""
import asyncio, json, subprocess, sys, time, urllib.request, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
OK = []
def check(name, cond, info=""):
    OK.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
cfg = "/tmp/h3s_v25/config.json"
IP = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()[0]
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8237", "--host", "0.0.0.0", "--no-browser", "--config", cfg],
                       cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v25_ui_srv.log", "w"))
time.sleep(1.5)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        for base in ("http://127.0.0.1:8237", f"http://{IP}:8237"):
            page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(base + "/")
            secure = await page.evaluate("window.isSecureContext && !!(window.crypto && crypto.subtle)")
            await page.evaluate("localStorage.setItem('h3studio.project','rue'); localStorage.removeItem('encore.folded.rue')")
            await page.reload(); await page.wait_for_timeout(1500)
            await takes_screen(page); await page.wait_for_timeout(1200)
            cards = await page.locator(".tk-card").count()
            states = await page.eval_on_selector_all(".tk-card", "e => e.map(x => x.className)")
            check(f"{base}: takes shown (secure context: {secure})", cards >= 3 and any("chosen" in s or "ok" in s or "other" in s for s in states) and not errs, (cards, errs))
            if base.startswith("http://127"):
                card = page.locator(".tk-card[data-take] >> nth=0"); await card.hover(); await page.wait_for_timeout(300)
                box = await card.locator(".tk-actions button.tk-retake").bounding_box()
                top = await page.evaluate(f"document.elementFromPoint({box['x'] + box['width'] / 2}, {box['y'] + box['height'] / 2}).textContent")
                check("« new take » reachable on a take (0.42: no invalidated takes)", "assemble" not in top.lower(), top)
                asm = await card.locator(".tk-asm-btn").bounding_box()
                check("assemble button visible, apart from « new take »", asm and (asm["y"] >= box["y"] + box["height"] or asm["y"] + asm["height"] <= box["y"] or asm["x"] >= box["x"] + box["width"] or asm["x"] + asm["width"] <= box["x"]), (asm, box))
                await page.screenshot(path="v25_take_card.png", clip={"x": box["x"] - 230, "y": box["y"] - 30, "width": 320, "height": 200})
                # ▶▶ while a generation of the branch is queued
                await page.evaluate("fetch('/api/queue/pause', {method: 'POST', headers: {'X-Encore': '1'}, body: '{}'})")
                await page.evaluate("fetch('/api/projects/rue/generate', {method: 'POST', headers: {'X-Encore': '1', 'Content-Type': 'application/json'}, body: JSON.stringify({clip: 1, branch: 'b1', random: true})})")
                await page.wait_for_timeout(2500)
                await page.evaluate("H3Takes.state.fill = {}; H3Takes.render()"); await page.wait_for_timeout(1500)
                fill = await page.eval_on_selector_all(".tk-band-head .tk-fill", "e => e.map(x => x.title)")
                check("▶▶ says generating (EN, in its tooltip since 0.27)", any("enerat" in f for f in fill), fill)
                jobs = await page.evaluate("fetch('/api/projects/rue/jobs').then(r => r.json())")
                for j in jobs["jobs"]:
                    if j["status"] == "queued":
                        await page.evaluate(f"fetch('/api/projects/rue/jobs/{j['id']}', {{method: 'DELETE', headers: {{'X-Encore': '1'}}}})")
                await page.evaluate("fetch('/api/queue/resume', {method: 'POST', headers: {'X-Encore': '1'}, body: '{}'})")
            await page.close()
        await b.close()
try: asyncio.run(main())
finally: srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
