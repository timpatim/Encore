import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8232"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"} if body is not None else {"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
root = "/tmp/h3s_v21"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
shutil.copytree("/tmp/h3s_v20b/projets", root + "/projets")
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8232", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v21_srv.log", "w"))
time.sleep(1.5)
FRW = re.compile(r"[éèàùçêâîôû]|\b(prise|prises|branche|aucun|aucune|avec|sans|choisir|annuler|fermer|lancer|générer|réglages|suite|voix|chanson|paroles)\b", re.I)
async def scan(page, label):
    text = await page.evaluate("document.body.innerText")
    titles = await page.evaluate("[...document.querySelectorAll('[title],[placeholder]')].map(e => (e.title||'') + ' ' + (e.placeholder||''))")
    bad = sorted({l.strip() for l in (text.split("\n") + titles) if FRW.search(l)})
    print(f"[{label}] french-looking lines: {len(bad)}")
    for l in bad[:25]: print("   ", l[:150])
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1500, "height": 950}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
        print("lang", await page.evaluate("H3I18n.lang()"))
        await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(300)
        await scan(page, "plan en"); await page.screenshot(path="v21_plan_en.png")
        await page.click("#viewTabs >> text=Takes"); await page.wait_for_timeout(2500)
        await scan(page, "takes en"); await page.screenshot(path="v21_takes_en.png")
        await page.click("text=Default settings…"); await page.wait_for_timeout(800)
        await scan(page, "defaults en"); await page.screenshot(path="v21_defaults_en.png")
        await page.locator(".tk-modal select").first.select_option("fr"); await page.wait_for_timeout(2500)
        print("lang after", await page.evaluate("H3I18n.lang()"), call(S, "/api/config")["language"])
        await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(300)
        await page.screenshot(path="v21_plan_fr.png")
        print("fr sample", (await page.evaluate("document.body.innerText"))[:300].replace("\n", " | "))
        print("errors", errs[:5])
        await b.close()
asyncio.run(main()); srv.terminate()
