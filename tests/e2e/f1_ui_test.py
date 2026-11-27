"""0.49 (UI): « duplicate » with portions of the selection (thumbnails by scene, a clip kept with its scene from its
start), the band of the new branch (boxes of the clips left free, the clips taken over after them), its master plan
(clips left free editable, their length locked) and the length locked in the launch panel."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, takes_screen, restart_mock  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8253"; M = "http://127.0.0.1:8771"; P = "/api/projects/rue"
OK = []
def check(name, cond, info=""):
    OK.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}
def drain():
    for _ in range(150):
        time.sleep(0.3)
        try: call(M, "/test/run", {})
        except Exception: pass
        if not any(j["status"] in ("queued", "running", "harvest") for j in call(S, P + "/jobs")["jobs"]): break
    time.sleep(0.4)
restart_mock()
root = "/tmp/h3s_f1"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
os.makedirs(os.path.join(ENCORE, "tests", "e2e", "out"), exist_ok=True)
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8253", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL,
                       stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "f1_ui_srv.log"), "w"))
time.sleep(1.5)
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
master = call(S, P + "/plan?branch=b1")["plan"]
master["clips"][2]["continue"] = False            # 1 → 2 | 3 → 4 | 5
call(S, P + "/plan", {"branch": "b1", "leaf": None, "plan": master}, "PUT")
call(S, P + "/branches/b1/fill", {"dry_run": False, "assemble": False}); drain()
t = {int(c["index"]): x["id"] for c in call(S, P + "/takes")["clips"] for x in c["takes"]}
call(S, P + "/selection", {"selection": {"branch": "b1", **{str(i): t[i] for i in t}}}, "PUT")
try:
    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 1000}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await takes_screen(page); await page.wait_for_timeout(1500)
            # ---------------- the duplicate dialog: portions by scene
            await page.locator(".tk-band-head .tk-dup").first.click(); await page.wait_for_timeout(800)
            clips = page.locator(".br-pick .br-clip")
            check("one thumbnail per clip of the selection, ✂ between the scenes", await clips.count() == 5 and await page.locator(".br-pick .br-cut").count() == 2,
                  (await clips.count(), await page.locator(".br-pick .br-cut").count()))
            await page.locator(".br-clip[data-clip='2']").click(); await page.wait_for_timeout(200)
            await page.locator(".br-clip[data-clip='3']").click(); await page.wait_for_timeout(200)
            on = lambda: page.eval_on_selector_all(".br-clip.on", "e => e.map(x => +x.dataset.clip)")  # noqa: E731
            check("freeing clip 3 frees the rest of its scene (4)", await on() == [1, 5], await on())
            await page.locator(".br-clip[data-clip='4']").click(); await page.wait_for_timeout(200)
            check("taking over clip 4 takes its scene from its start (3)", await on() == [1, 3, 4, 5], await on())
            await page.locator(".br-clip[data-clip='4']").click(); await page.wait_for_timeout(200)
            text = await page.inner_text(".br-new")
            check("the dialog says what is taken over and what is left free", "clips 1, 3, 5" in text and "Left free: clips 2, 4" in text, text)
            await page.locator(".tk-modal button.primary", has_text="Create").last.click(); await page.wait_for_timeout(2000)
            meta = call(S, P)
            nb = [x for x in meta["branches"] if x.get("base")][-1]
            check("the new branch takes over 1, 3 and 5", nb["base"]["takes"] == [t[1], None, t[3], None, t[5]], nb.get("base"))
            B = nb["id"]
            # ---------------- its band: the boxes of the clips left free, the clips taken over after them
            await page.wait_for_timeout(1500)
            reused = page.locator(f".tk-card.tk-reused[data-band='{B}']")
            check("three clips taken over in the band", await reused.count() == 3, await reused.count())
            check("the box of clip 2 is the one to generate", await page.locator(f".tk-cell.active[data-cell='{B}:2']").count() == 1)
            r3 = page.locator(f".tk-card.tk-reused[data-band='{B}'][data-take='{t[3]}']")
            check("clip 3 taken over waits for clip 2 (↻ and + disabled)", await r3.locator(".tk-retake[disabled]").count() == 1 and await r3.locator(".tk-next[disabled]").count() == 1)
            c2 = (await page.locator(f".tk-cell[data-cell='{B}:2']").bounding_box()); b3 = await r3.bounding_box()
            check("clip 3 taken over comes right after the box of clip 2, on its row", abs(c2["y"] - b3["y"]) < 4 and b3["x"] > c2["x"], (c2, b3))
            # ---------------- its master plan: clips left free read-only
            await page.locator(f".tk-band-head[data-branch='{B}'] .tk-master").first.click(); await page.wait_for_timeout(1500)
            await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(500)
            summ = page.locator('#editor textarea[data-sec="summary"]')
            check("clip 2 left free: editable like any clip of a master plan", await summ.count() == 1 and not await summ.evaluate("e => e.readOnly")
                  and await page.locator("#editor .locked-banner").count() == 0)
            check("… but its length is locked", await page.locator("#editor select.ed-frames[disabled]").count() == 1)
            await summ.click(); await page.keyboard.press("Control+End"); await page.keyboard.type(" A red umbrella."); await page.wait_for_timeout(600)
            await page.click("#btnSave"); await page.wait_for_timeout(1200)
            m2 = call(S, P + f"/plan?branch={B}")["plan"]["clips"][1]
            check("… and its change is saved in the master plan", m2.get("summary", "").endswith("A red umbrella."), m2.get("summary"))
            await page.locator(".clipitem").nth(2).click(); await page.wait_for_timeout(500)
            check("clip 3 taken over stays read-only", await page.locator("#editor .locked-banner").count() == 1)
            await takes_screen(page); await page.wait_for_timeout(1200)
            # ---------------- ▶▶ makes clips 2 and 4
            call(S, P + f"/branches/{B}/fill", {"dry_run": False, "assemble": False}); drain()
            await page.evaluate("H3Takes.rescan()"); await page.wait_for_timeout(2500)
            check("no box left in the band", await page.locator(f".tk-cell[data-cell^='{B}:']").count() == 0)
            check("clip 3 taken over can be made again now", await r3.locator(".tk-retake:not([disabled])").count() == 1)
            L = call(S, P + "/takes"); mine = {int(c["index"]): x["id"] for c in L["clips"] for x in c["takes"] if ((x.get("record") or x).get("studio") or {}).get("branch") == B}
            card2 = page.locator(f".tk-card[data-take='{mine[2]}']")
            await card2.hover(); await card2.locator(".tk-retake").click(); await page.wait_for_selector("#launchPanel"); await page.wait_for_timeout(1500)
            check("a new take of clip 2: its length is locked", await page.locator("#launchPanel select.ed-frames[disabled]").count() == 1
                  or await page.locator("#editor select.ed-frames[disabled]").count() == 1)
            await page.locator("#launchPanel button", has_text="Cancel").last.click(); await page.wait_for_timeout(500)
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
