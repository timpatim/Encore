import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8220"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"} if body is not None else {"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
root = "/tmp/h3s_qui"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8220", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        call(S, "/api/queue/pause", {"mode": "after"})
        A = call(S, P + "/generate", {"clip": 1, "branch": "b1"}); B = call(S, P + "/generate", {"clip": 2, "after": A["take_id"]})
        C = call(S, P + "/generate", {"clip": 1, "random": True, "branch": "b1"})
        await page.wait_for_timeout(2500)
        print("ghosts", await page.eval_on_selector_all(".tk-ghost-label", "e => e.map(x => x.textContent)"))
        print("badge", await page.eval_on_selector("#studioQueueBtn", "e => e.textContent"))
        await page.click("#studioQueueBtn"); await page.wait_for_timeout(1500)
        await page.screenshot(path="q1_manager.png")
        groups = page.locator(".studio-q-group")
        print("groups", await groups.count())
        # 0.48.2: a group is dragged by its ≡ handle
        h = await groups.nth(1).locator(".studio-q-handle").bounding_box(); top = await groups.nth(0).bounding_box()
        await page.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2); await page.mouse.down()
        for k in range(1, 11):
            await page.mouse.move(h["x"] + h["width"] / 2, h["y"] + (top["y"] + 3 - h["y"]) * k / 10); await page.wait_for_timeout(30)
        await page.mouse.up(); await page.wait_for_timeout(1500)
        q = call(S, "/api/queue"); print("after drag", [[(j["clip"], j["seed"] == C["seed"]) for j in g["jobs"]] for g in q["groups"]])
        await page.click(".studio-q-group >> nth=0 >> button:has-text('suspendre')"); await page.wait_for_timeout(1200)
        await page.click(".studio-q-group >> nth=1 >> .studio-q-line >> nth=0 >> button:has-text('annuler')"); await page.wait_for_timeout(600)
        msgs.append(await page.eval_on_selector(".h3-dlg-text", "e => e.textContent")); await page.click(".h3-dlg button:has-text('Oui')"); await page.wait_for_timeout(1500)
        print("dialogs", msgs)
        q = call(S, "/api/queue"); print("after cancel", [[j["clip"] for j in g["jobs"]] + (["S"] if g["suspended"] else []) for g in q["groups"]])
        await page.click("button:has-text('Reprendre')"); await page.wait_for_timeout(1500)
        print("badge2", await page.eval_on_selector("#studioQueueBtn", "e => e.textContent"))
        await page.screenshot(path="q2_manager.png")
        print("ERRORS:", errs); await b.close()
try: asyncio.run(main())
finally: srv.terminate()
