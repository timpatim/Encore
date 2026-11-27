"""0.48 (interface): the master line on the takes screen (its empty cells, the first one generated with a click, its
takes in a row at the top of the band), ▶▶ of a branch = the master line, ▶▶ of the selection in the selection bar,
« duplicate » in the branch header, « + new branch » (empty or from a file), the frozen master plan (clips and subjects
read-only, a clip added at the end), « New branch with this plan… »."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, restart_mock, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8245"; M = "http://127.0.0.1:8771"
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
P = "/api/projects/rue"
def drain():
    for _ in range(120):
        time.sleep(0.3)
        try: call(M, "/test/run", {})
        except Exception: pass
        if not any(j["status"] in ("queued", "running", "harvest") for j in call(S, P + "/jobs")["jobs"]): break
    time.sleep(0.5)
def line_takes():
    recs = [t["record"] for c in call(S, P + "/takes")["clips"] for t in c["takes"]]
    return sorted((r for r in recs if r["studio"].get("line")), key=lambda r: r["saved_at"])
restart_mock()
root = "/tmp/h3s_d2"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8245", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("d2_srv.log", "w"))
time.sleep(1.5)
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
N = len(call(S, P + "/plan?branch=b1")["plan"]["clips"])


async def confirm(page):
    await page.wait_for_selector(".h3-dlg", timeout=10000)
    await page.click(".h3-dlg-buttons button.danger-fill, .h3-dlg-buttons button.primary"); await page.wait_for_timeout(1200)


try:
    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 1000}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await takes_screen(page); await page.wait_for_timeout(1200)
            # ---- the empty master line
            cells = page.locator(".tk-cell")
            check("one empty cell per clip of the master plan", await cells.count() == N, await cells.count())
            check("only the first one can be generated", await page.locator(".tk-cell.active").count() == 1
                  and await page.locator(".tk-cell.active").get_attribute("data-cell") == "b1:1")
            await page.locator(".tk-cell.active").click(); await page.wait_for_selector("#launchPanel")
            check("the cell opens the launch panel, its clip read-only", await page.locator("#launchPanel .locked-banner").count() == 1)
            await launch_go(page); await page.wait_for_timeout(800)
            jobs = call(S, P + "/jobs")["jobs"]
            check("a click on the cell launches clip 1 of the master line", len(jobs) == 1 and jobs[0]["record"]["studio"].get("line"), jobs)
            drain(); await page.evaluate("H3Takes.rescan()"); await page.wait_for_timeout(2500)
            line = line_takes()
            check("the take is on the master line", len(line) == 1)
            card = page.locator(f".tk-card[data-take='{line[0]['id']}']")
            check("… tagged « master plan »", await card.locator(".tk-line-tag").count() == 1)
            check("the next cell can be generated now", await page.locator(".tk-cell.active").get_attribute("data-cell") == "b1:2"
                  and await page.locator(".tk-cell").count() == N - 1)
            cy = (await card.bounding_box())["y"]; ny = (await page.locator(".tk-cell.active").bounding_box())["y"]
            check("the line is a row", abs(cy - ny) < 2, (cy, ny))
            # ---- ▶▶ of the branch fills the master line
            fill = page.locator(".tk-band-head .tk-fill").first
            check("▶▶ of the branch: the master line", "master line" in (await fill.get_attribute("title") or ""), await fill.get_attribute("title"))
            await fill.click(); await confirm(page)
            drain(); await page.evaluate("H3Takes.rescan()"); await page.wait_for_timeout(2500)
            check("the whole master line generated", len(line_takes()) == N and await page.locator(".tk-cell").count() == 0, len(line_takes()))
            ys = {round((await page.locator(f".tk-card[data-take='{r['id']}']").bounding_box())["y"]) for r in line_takes()}
            check("… in a row", len(ys) == 1, ys)
            # ---- the selection: its own ▶▶ in the selection bar
            await page.locator(f".tk-card[data-take='{line_takes()[1]['id']}']").click(); await page.wait_for_timeout(1500)
            check("▶▶ of the selection in the selection bar", await page.locator(".tk-selbar .tk-fill-sel").count() == 1)
            # ---- the frozen master plan
            await page.locator(".tk-master").first.click(); await page.wait_for_timeout(1500)
            check("master plan: its clips read-only", await page.locator(".clipitem.locked").count() == N)
            check("… with the frozen banner", "master line" in await page.text_content(".locked-banner"), await page.text_content(".locked-banner"))
            check("its subjects are frozen", await page.locator(".sx-lib-subject .sx-edit", has_text="🔒").count() >= 1)
            await page.locator(".sx-lib-subject .sx-edit").first.click(); await page.wait_for_timeout(500)
            check("a frozen subject is shown without « save »", await page.locator(".sx-frozen-subject").count() == 1 and await page.locator(".sx-save").count() == 0)
            await page.locator(".tk-modal button", has_text="Close").last.click(); await page.wait_for_timeout(300)
            await page.evaluate("H3Editor.state.sel = H3Editor.state.plan.clips.length - 1"); await page.evaluate("H3Editor.render()")
            await page.locator("#list button", has_text="clip").first.click(); await page.wait_for_timeout(800)
            check("a clip can be added at the end", len(await page.evaluate("H3Editor.state.plan.clips")) == N + 1)
            await page.click("#btnSave"); await page.wait_for_timeout(1500)
            check("… and saved", len(call(S, P + "/plan?branch=b1")["plan"]["clips"]) == N + 1, call(S, P + "/plan?branch=b1").get("error"))
            check("after saving, the plan shown is still version 7, without error (0.48.1)", await page.evaluate("H3Editor.state.plan.version") == 7
                  and "version" not in (await page.text_content("#side") or ""))
            await takes_screen(page); await page.wait_for_timeout(1500)
            check("the added clip is a new cell of the master line", await page.locator(".tk-cell.active").get_attribute("data-cell") == f"b1:{N + 1}")
            # ---- « duplicate » and « + new branch »
            await page.locator(".tk-band-head .tk-dup").first.click(); await page.wait_for_timeout(800)
            dlg = page.locator(".tk-modal").last
            text = await dlg.inner_text()
            check("« duplicate »: without or with the clips of the selection", "Duplicate" in text and "Empty" not in text and await dlg.locator("input[value], input[type=radio]").count() >= 2, text)
            await dlg.locator("button", has_text="Close").click(); await page.wait_for_timeout(300)
            await page.locator(".tk-newbranch").click(); await page.wait_for_timeout(800)
            dlg = page.locator(".tk-modal").last
            text = await dlg.inner_text()
            check("« + new branch »: empty or from a file only", "Empty" in text and "without" not in text.lower(), text)
            await dlg.locator("button", has_text="Close").click(); await page.wait_for_timeout(300)
            # ---- « New branch with this plan… » on the plan of the selection
            await plan_screen(page); await page.wait_for_timeout(800)
            n = len(call(S, P)["branches"])
            await page.click("#studioUsePlanBtn"); await page.wait_for_selector(".use-plan")
            check("only a new branch is offered", await page.locator(".use-plan .use-master").count() == 0)
            await page.fill(".use-plan input", "From the selection"); await page.click(".use-plan .use-new"); await page.wait_for_timeout(1500)
            brs = call(S, P)["branches"]
            check("a new branch with the plan of the selection", len(brs) == n + 1 and brs[-1]["name"] == "From the selection", [x["name"] for x in brs])
            await takes_screen(page); await page.wait_for_timeout(800)
            await page.screenshot(path="d2_takes.png")
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
