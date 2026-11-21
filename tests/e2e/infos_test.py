import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8218"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"} if body is not None else {"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
root = "/tmp/h3s_inf"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8218", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for kind, f in (("images", fixture("fillette.png")), ("images", fixture("rue.png"))):
    call(S, f"{P}/resources?kind={kind}&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/branches", {}); call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1700, "height": 1000}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1300)
        await page.click("#viewTabs >> text=Prises"); await page.wait_for_timeout(800)
        run = lambda: call(M, "/test/run", {})
        await page.click(".tk-placeholder >> nth=0 >> .tk-plus"); await page.wait_for_timeout(900); run(); await page.wait_for_timeout(2700)
        await page.click(".tk-slot >> nth=0"); await page.wait_for_timeout(900); run(); await page.wait_for_timeout(2700)
        # second version of clip 2 (from the same clip 1 take)
        await page.hover(".tk-card.chosen >> nth=1"); await page.click(".tk-card.chosen >> nth=1 >> button.tk-retake"); await page.wait_for_timeout(900); run(); await page.wait_for_timeout(2800)
        print("global button", await page.query_selector("text=Lancer l'assemblage"))
        print("leaf buttons", await page.eval_on_selector_all(".tk-asm-btn", "e => e.map(x => [x.textContent, x.disabled, x.closest('.tk-card').dataset.take.slice(-6)])"))
        sel0 = call(S, P + "/selection") if False else None
        # queue a generation (not run), then both assemblies
        await page.hover(".tk-card.chosen >> nth=1"); await page.click(".tk-card.chosen >> nth=1 >> button.tk-retake", force=True); await page.wait_for_timeout(900)
        for n in (0, 1):
            card = page.locator(".tk-card:has(.tk-asm-btn)").nth(n)
            await card.hover(); await card.locator(".tk-asm-btn").click(); await page.wait_for_timeout(900)
        print("jobs", [(j["kind"], j["status"], j.get("clips")) for j in call(S, P + "/jobs")["jobs"] if j["status"] != "done"])
        print("pane", await page.eval_on_selector_all(".tk-pane-item", "e => e.map(x => x.className.split(' ').slice(-1)[0])"))
        for _ in range(3): run(); await page.wait_for_timeout(2500)
        ex = call(S, P + "/exports")["exports"]
        print("exports", [(e["clips"], sorted(e["takes"].items())) for e in ex])
        print("infos field", [e.get("infos") for e in ex])
        import glob, os
        for f in sorted(glob.glob("/tmp/h3s_inf/projets/rue/exports/*")): print("file", os.path.basename(f), os.path.getsize(f))
        await page.click("text=Vidéos assemblées…"); await page.wait_for_timeout(800)
        print("infos buttons", len(await page.query_selector_all(".tk-modal button:has-text('infos')")))
        cps = call(S, P + "/checkpoints")["checkpoints"]
        print("checkpoints", [c["name"] for c in cps])
        print("ERRORS:", errs); await b.close()
try: asyncio.run(main())
finally: srv.terminate()
