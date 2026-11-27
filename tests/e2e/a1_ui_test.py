"""Chantier A, lot A1 (interface): the Takes screen is the main screen; every generation goes through the launch
panel (docked on the right, the graph stays visible); the plan screen shows the plan of the selection (generated
clips locked) or the master plan of a branch; a twig's plan is changed without touching the master plan."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8243"; M = "http://127.0.0.1:8771"


def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}


def check(label, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))


root = "/tmp/h3s_a1ui"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8243", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "a1ui_srv.log"), "w"))
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")


def drain():
    for _ in range(40):
        time.sleep(0.6)
        try: call(M, "/test/run", {})
        except Exception: pass
        time.sleep(0.6)
        if not [j for j in call(S, P + "/jobs")["jobs"] if j["status"] in ("queued", "running", "harvest")]: break


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1600, "height": 1000}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("dialog", lambda d: (errs.append("dialog: " + d.message) if "figé" not in d.message and "ne peut plus" not in d.message else print("alert:", d.message[:90]), asyncio.ensure_future(d.dismiss())))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1800)
        check("opens on the Takes screen", await page.is_visible("#takesView") and not await page.is_visible("#planView"))
        check("no Plan / Prises tabs", not await page.is_visible("#viewTabs"))
        check("selection bar on the master plan", "plan maître" in (await page.text_content(".tk-selbar")).lower(), await page.text_content(".tk-selbar"))

        # clip 1 through the launch panel: the graph stays visible
        await page.click(".tk-cell.active >> nth=0"); await page.wait_for_timeout(1200)
        box = await page.eval_on_selector("#launchPanel", "e => e.getBoundingClientRect().left")
        check("panel docked on the right, graph visible", box > 500 and await page.is_visible(".tk-band-head"), box)
        check("panel shows the clip editor", await page.is_visible("#launchPanel #editor .fields"))
        await launch_go(page); drain(); await page.wait_for_timeout(2500)
        t1 = call(S, P)["plan_takes"].get("1")
        check("clip 1 made and selected", bool(t1))

        # clip 2: « + » box after the take
        await page.click(".tk-cell.active >> nth=0"); await launch_go(page); drain(); await page.wait_for_timeout(2500)
        t2 = call(S, P)["plan_takes"].get("2")
        check("clip 2 after clip 1", bool(t2))

        # a new take of clip 2 with another prompt, from the panel
        card = page.locator(f'.tk-card[data-take="{t2}"]')
        await card.hover(); await card.locator("button.tk-retake").click(); await page.wait_for_timeout(1300)
        seed0 = t2.split("_")[0][1:]
        check("0.49.1: a new take starts with a new seed", (await page.input_value("#launchPanel .launch-seed")) != seed0
              and not await page.is_visible("#launchPanel .warnline:has-text('identique')"))
        await page.click("#launchPanel .launch-seed-back"); await page.wait_for_timeout(400)
        check("… the seed of the take redone can be put back", (await page.input_value("#launchPanel .launch-seed")) == seed0)
        check("identical warning shown", await page.is_visible("#launchPanel .warnline:has-text('identique')"))
        raw = page.locator('#launchPanel textarea[data-sec="summary"]')
        await raw.click(); await page.keyboard.press("Control+End"); await page.keyboard.type(" A red umbrella."); await page.wait_for_timeout(900)
        check("identical warning gone after the change", not await page.is_visible("#launchPanel .warnline:has-text('identique')"))
        await launch_go(page); drain(); await page.wait_for_timeout(2500)
        t2b = call(S, P)["plan_takes"].get("2")
        tw = call(S, P + f"/plan?leaf={t2b}")
        check("the new take carries its own prompt", t2b != t2 and tw["plan"]["clips"][1]["summary"].endswith("A red umbrella."), t2b)
        check("the first take keeps its prompt", not call(S, P + f"/plan?leaf={t2}")["plan"]["clips"][1]["summary"].endswith("A red umbrella."))

        # clip 3 after the first take of clip 2, then: a new take of clip 2 lists the twigs through it
        call(S, P + "/generate", {"clip": 3, "after": t2}); drain()
        await page.click(".tk-bar button >> nth=0"); await page.wait_for_timeout(2200)
        card = page.locator(f'.tk-card[data-take="{t2}"]')
        await card.hover(); await card.locator("button.tk-retake").click(); await page.wait_for_timeout(1300)
        # 0.48.2: both twigs through the take keep the same plan for the clips after it, so there is nothing to choose
        check("same plan in every twig: no « plan of the following clips » choice", await page.locator("#launchPanel .launch-opt").count() == 0)
        await page.click("#launchPanel button:has-text('plan choisi en entier')"); await page.wait_for_timeout(300)
        check("whole plan unfolds", await page.is_visible("#launchPanel .launch-whole .launch-clip"))
        await page.click("#launchPanel .launch-foot button:has-text('Annuler')"); await page.wait_for_timeout(500)
        check("panel closed, editor given back", not await page.is_visible("#launchPanel") and await page.evaluate("!!document.querySelector('#planView #editor')"))

        # plan of the selection: generated clips locked, the suite saved for this twig only
        sel = call(S, P)
        await plan_screen(page); await page.wait_for_timeout(500)
        locked = await page.eval_on_selector_all("#list .clipitem.locked", "e => e.length")
        check("plan screen: generated clips locked", locked == sel["plan_locked"] and locked >= 2, (locked, sel["plan_locked"]))
        await page.locator("#list .clipitem").nth(0).click(); await page.wait_for_timeout(300)
        check("a locked clip is read-only", await page.is_visible(".locked-banner") and await page.eval_on_selector("#editor .fields input", "e => e.readOnly"))
        n = len(sel["plan"]["clips"])
        await page.locator("#list .clipitem").nth(n - 1).click(); await page.wait_for_timeout(300)
        await page.fill("#editor .fields input >> nth=0", "renamed_last"); await page.wait_for_timeout(800)
        await takes_screen(page); await page.wait_for_timeout(800)
        leaf = call(S, P)["plan_leaf"]
        check("suite saved for the twig", call(S, P + f"/plan?leaf={leaf}")["plan"]["clips"][n - 1]["name"] == "renamed_last")
        check("master plan unchanged", call(S, P + "/plan?branch=b1")["plan"]["clips"][n - 1]["name"] != "renamed_last")

        # master plan of the branch
        await plan_screen(page, master=True)
        check("master plan: frozen by the takes (0.48), its clips locked", await page.eval_on_selector_all("#list .clipitem.locked", "e => e.length") >= 1)
        check("plan title says master", "maître" in (await page.text_content("#studioPlanTitle")))
        await takes_screen(page)

        # frozen settings: the size of a branch with takes
        out = call(S, P + "/branches/b1", {"width": 640, "height": 384}, "PUT")
        check("size refused for a branch with takes", "error" in out or out.get("HTTP") == 400, out)

        # a new branch whose master plan gives the girl another picture: the launch panel shows that plan's picture
        b2 = call(S, P + "/branches", {})["branch"]["id"]
        m2 = call(S, P + f"/plan?branch={b2}")["plan"]
        m2["subjects"]["fillette"]["pictures"][0]["file"] = "rue"
        call(S, P + "/plan", {"branch": b2, "plan": m2}, "PUT")
        await page.reload(); await takes_screen(page); await page.wait_for_timeout(800)
        await page.click(f".tk-cell.active[data-cell='{b2}:1']"); await page.wait_for_selector("#launchPanel"); await page.wait_for_timeout(600)
        img = await page.get_attribute('#launchPanel .sx-lib-subject[data-subject="fillette"] img', "src")
        check("launch panel shows the pictures of its plan", bool(img) and "rue.png" in img, img)
        await page.evaluate("H3Launch.close()")
        await page.wait_for_timeout(300)
        await page.screenshot(path="a1_ui.png")
        print("ERRORS:", errs); await b.close()

try:
    asyncio.run(main())
finally:
    srv.terminate()
