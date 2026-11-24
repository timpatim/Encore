import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8217"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"} if body is not None else {"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
root = "/tmp/h3s_up"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8217", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for kind, f in (("images", fixture("fillette.png")), ("images", fixture("rue.png"))):
    call(S, f"{P}/resources?kind={kind}&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1700, "height": 1000}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1300)
        await takes_screen(page); await page.wait_for_timeout(800)
        run = lambda: call(M, "/test/run", {})
        msgs = []
        async def on_dialog(d):
            msgs.append(d.message); await d.accept()
        page.on("dialog", on_dialog)
        await page.evaluate("H3Studio.kit.openUpscale('b1')"); await page.wait_for_timeout(800)
        print("summary0", await page.eval_on_selector(".studio-up-sum", "e => e.textContent"))
        await page.locator(".studio-upscale .tk-row:has(label:text('Modèle')) select").select_option("minimax_h3_latent_upscaler_3d_fp16.safetensors"); await page.wait_for_timeout(300)
        await page.locator(".studio-upscale .tk-row:has(label:text('Activé')) input").check(); await page.wait_for_timeout(500)
        print("summary1", await page.eval_on_selector(".studio-up-sum", "e => e.textContent"))
        await page.screenshot(path="u1_dialog.png", full_page=True)
        await page.click(".tk-box-head button:has-text('Fermer')"); await page.wait_for_timeout(800)
        import json as J
        print("branch", J.dumps(call(S, P)["branches"][0]["upscale"])[:200])
        await page.click(".tk-placeholder >> nth=0 >> .tk-plus"); await launch_go(page); run(); await page.wait_for_timeout(2700)
        wf = J.load(open("/tmp/mock_last_prompt.json")); print("clip1 nodes", sorted(n["class_type"] for k, n in wf.items() if int(k) >= 60), "71" in wf)
        await page.click(".tk-slot >> nth=0"); await launch_go(page); run(); await page.wait_for_timeout(2700)
        wf = J.load(open("/tmp/mock_last_prompt.json")); print("clip2 has replace", "71" in wf, wf.get("70", {}).get("inputs"), wf["61"]["inputs"]["width"], wf["69"]["inputs"]["width"])
        # forced without
        await page.hover(".tk-card.chosen >> nth=1"); await page.locator(".tk-card.chosen >> nth=1").locator("button.tk-retake").click(); await page.wait_for_timeout(1200)
        dl = page.locator("#launchPanel")
        await dl.locator(".studio-up-line button").first.click(); await page.wait_for_timeout(300)        # « modifier… »
        await dl.locator(".tk-row:has(label:text('Activé')) input").uncheck(); await page.wait_for_timeout(300)
        await launch_go(page); run(); await page.wait_for_timeout(2700)
        wf = J.load(open("/tmp/mock_last_prompt.json")); print("forced off has upscale", any(int(k) >= 60 for k in wf))
        print("badges", await page.eval_on_selector_all(".tk-card", "e => e.map(c => !!c.querySelector('.tk-up-badge'))"))
        print("header btn", await page.eval_on_selector(".tk-band-head .tk-brsettings", "e => e.textContent"))
        await page.screenshot(path="u2_takes.png")
        print("dialogs", msgs)
        print("ERRORS:", errs); await b.close()
try: asyncio.run(main())
finally: srv.terminate()
