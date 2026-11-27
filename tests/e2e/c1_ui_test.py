"""0.47: the Takes screen and the plan screen, tidied up — no columns mode, no « running / waiting » label nor Stop in
the bar, ◎ to the generation running, the branch name edited in place, the view scrolled down to the lowest card and no
further, the minimap filled by the graph, an assembly launched with the video pane folded shows on its tab, assembled
videos open on a double click and loop, « Cancel all » in the queue, the plan screen with a row of its own."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8242"; M = "http://127.0.0.1:8771"
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
def run_mock():
    try: call(M, "/test/run", {})
    except Exception: pass
def wait_last(P):
    for _ in range(90):
        time.sleep(0.7); run_mock()
        jobs = call(S, P + "/jobs")["jobs"]
        if jobs and jobs[-1]["status"] in ("done", "error", "cancelled"): break
    return call(S, P + "/jobs")["jobs"][-1]
root = "/tmp/h3s_c1"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8242", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("c1_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/branches", {"how": "empty"})
b1, b2 = [b["id"] for b in call(S, P)["branches"]][:2]
call(S, P + "/generate", {"clip": 1, "branch": b1}); t1 = wait_last(P)["take"]
call(S, P + "/generate", {"clip": 2, "branch": b1, "after": t1}); t2 = wait_last(P)["take"]
call(S, P + "/generate", {"clip": 1, "branch": b2}); wait_last(P)
call(S, P + "/selection", {"selection": {"branch": b1, "1": t1, "2": t2}}, "PUT")
call(S, P + "/assemble", {"clip": 2, "take": t2}); asm = wait_last(P)
try:
    check("an assembled video to look at", asm["kind"] == "assemble" and asm["status"] == "done", asm.get("status"))

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1500, "height": 1000}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/")
            await page.evaluate("localStorage.setItem('h3studio.project','rue'); localStorage.setItem('h3clipplan.view', JSON.stringify({mapOpen: true, paneOpen: true}))")
            await page.reload(); await page.wait_for_timeout(1500)
            await takes_screen(page); await page.wait_for_timeout(1500)
            # ---- the bar
            check("no tree / columns switch", await page.locator(".tk-viewbar .tabs").count() == 0)
            check("no « running / waiting » label, no Stop in the bar", await page.locator(".tk-bar .tk-queue, .tk-bar button.danger").count() == 0)
            to_run = page.locator(".tk-to-running")
            check("◎ greyed while nothing runs", await to_run.count() == 1 and await to_run.is_disabled())
            # ---- the name of a branch, edited in place
            check("no « rename » button", await page.locator(".tk-band-head button", has_text="rename").count() == 0)
            name = page.locator(f".tk-band-head .tk-band-name").first
            await name.click(); await name.fill("Renamed branch"); await name.press("Enter"); await page.wait_for_timeout(1200)
            check("Enter saves the name", any(br["name"] == "Renamed branch" for br in call(S, P)["branches"]), call(S, P)["branches"])
            name = page.locator(f".tk-band-head .tk-band-name").first
            await name.click(); await name.fill("Not kept"); await name.press("Escape"); await page.wait_for_timeout(1000)
            check("Esc gives the name back", not any(br["name"] == "Not kept" for br in call(S, P)["branches"])
                  and await page.locator(".tk-band-head .tk-band-name").first.input_value() == "Renamed branch")
            # ---- scrolled down to the lowest card, and no further
            low = await page.evaluate("""() => { const vp = document.querySelector('#takesView .tk-viewport'); vp.scrollTop = 1e6;
                const cards = [...vp.querySelectorAll('.tk-card')]; const vr = vp.getBoundingClientRect();
                const tops = cards.map((c) => c.getBoundingClientRect().top - vr.top); return [Math.max(...tops), Math.min(...tops.filter((t) => t > -1e5)), vp.clientHeight]; }""")
            check("the lowest card stops near the top of the view", 0 < low[0] < 120, low)
            # ---- minimap: the graph fills it (centred), the frame may go past its edges
            mm = await page.evaluate("""() => { const T = H3Takes.state; return [T.mapScale, T.mapOffset, T.graphSize]; }""")
            filled = abs(mm[2][0] * mm[0] - 260) < 1 or abs(mm[2][1] * mm[0] - 160) < 1
            check("the graph fills the minimap", filled and mm[1][0] >= 0 and mm[1][1] >= 0, mm)
            await page.evaluate("document.querySelector('#takesView .tk-viewport').scrollTop = 0")
            # ---- assembled videos: a click does not open them, a double click does, and the video loops
            item = page.locator(".tk-pane-item").first
            await item.click(); await page.wait_for_timeout(600)
            check("a click on an assembled video does not open it", await page.locator(".tk-modal video").count() == 0)
            await item.dblclick(); await page.wait_for_timeout(800)
            check("a double click opens it, looping", await page.locator(".tk-modal video[loop]").count() == 1)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            # ---- an assembly launched with the pane folded shows on its tab
            await page.evaluate("H3Takes.state.paneOpen = false; H3Takes.render()"); await page.wait_for_timeout(400)
            call(S, "/api/queue/pause", {})
            await page.locator(".tk-selbar button", has_text="assemble").click(); await page.wait_for_timeout(2500)
            check("the folded tab shows the assembly waiting", await page.locator(".tk-pane.folded .tk-pane-busy").count() == 1)
            # ---- the queue: « Cancel all »
            await page.click("#studioQueueBtn"); await page.wait_for_timeout(800)
            btn = page.locator(".studio-q-bar button", has_text="Cancel all")
            check("« Cancel all » in the queue", await btn.count() == 1 and await btn.is_enabled())
            await btn.click(); await page.wait_for_selector(".h3-dlg"); await page.click(".h3-dlg-buttons button.danger-fill, .h3-dlg-buttons button.primary")
            await page.wait_for_timeout(1500)
            waiting = [j for j in call(S, P + "/jobs")["jobs"] if j["status"] in ("queued", "running")]
            check("everything cancelled", not waiting, waiting)
            call(S, "/api/queue/resume", {})
            await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
            for close in await page.locator(".tk-modal button, .studio-dlg button", has_text="Close").all():
                try: await close.click(timeout=500)
                except Exception: pass
            # ---- the queue button keeps its width
            w = await page.evaluate("document.getElementById('studioQueueBtn').getBoundingClientRect().width")
            check("the queue button has a fixed width", abs(w - 380) < 2, w)
            # ---- the plan screen: a row of its own, no chain of take ids in its title
            await plan_screen(page); await page.wait_for_timeout(800)
            row = page.locator(".studio-plan-row")
            check("the plan screen has its own row", await row.is_visible())
            for sel in ("#studioBackBtn", "#btnSave", "#btnUndo", "#btnRedo", "#btnPlanSettings", "#badge"):
                check(f"{sel} in the plan row", await row.locator(sel).count() == 1)
            check("the project buttons stay in the project row", await row.locator(".studio-bar").count() == 0 and await page.locator("header .studio-bar").is_visible())
            title = await page.text_content("#studioPlanTitle")
            check("no chain of take ids in the title", "→" not in title and ":" not in title, title)
            check("the title is shown once", not await page.locator("#fileName").is_visible())
            await takes_screen(page)
            check("no plan row on the Takes screen", not await page.locator(".studio-plan-row").is_visible())
            check("no page error", not errs, errs)
            await page.screenshot(path="c1_takes.png")
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
