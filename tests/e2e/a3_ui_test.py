"""Chantier A, lot A3 (interface): 🗑 on a take (with a confirmation listing what goes with it), the trash
(restore, erase), Ctrl+Z only where the plan is edited; the launch panel lies over the screen (nothing moves) and
the frame of the minimap stays inside it."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8247"; M = "http://127.0.0.1:8771"


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


root = "/tmp/h3s_a3ui"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8247", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "a3ui_srv.log"), "w"))
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")


def drain():
    for _ in range(40):
        time.sleep(0.6)
        try: call(M, "/test/run", {})
        except Exception: pass
        time.sleep(0.6)
        if not [j for j in call(S, P + "/jobs")["jobs"] if j["status"] in ("queued", "running", "harvest")]: break


def gen(body):
    j = call(S, P + "/generate", body)
    for _ in range(40):
        drain()
        take = next((x for x in call(S, P + "/jobs")["jobs"] if x["id"] == j.get("id")), {}).get("take")
        if take:
            return take
        time.sleep(0.5)
    raise RuntimeError(f"no take for {body}: {j}")


async def confirm(page):
    await page.wait_for_selector(".h3-dlg", timeout=10000); text = await page.text_content(".h3-dlg")
    await page.click(".h3-dlg-buttons button.danger-fill, .h3-dlg-buttons button.primary"); await page.wait_for_timeout(1500)
    return text


async def main():
    t1 = gen({"clip": 1, "branch": "b1"}); t2a = gen({"clip": 2, "after": t1}); t2b = gen({"clip": 2, "after": t1})
    t3 = gen({"clip": 3, "after": t2a})
    call(S, P + "/branches", {"how": "empty"}); call(S, P + "/branches", {"how": "empty"})
    call(S, P + "/selection", {"selection": {"branch": "b1", "1": t1, "2": t2b}}, "PUT")
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1500, "height": 760}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1800)

        # the launch panel lies over the screen: nothing moves
        w0 = await page.evaluate("document.getElementById('takesView').getBoundingClientRect().width")
        card = page.locator(f".tk-card[data-take='{t2b}']")
        await card.hover(); await card.locator(".tk-retake").click(); await page.wait_for_selector("#launchPanel")
        w1 = await page.evaluate("document.getElementById('takesView').getBoundingClientRect().width")
        check("the launch panel lies over the takes (nothing moves)", abs(w0 - w1) < 1, (w0, w1))
        box = await card.bounding_box(); panel = await page.locator("#launchPanel").bounding_box()
        check("the take it starts from stays visible beside it", box and box["x"] + box["width"] <= panel["x"], (box, panel))
        await page.evaluate("H3Launch.close()"); await page.wait_for_timeout(400)

        # the minimap: scrolled to the bottom, its frame stays inside
        await page.evaluate("const v = document.querySelector('#takesView .tk-viewport'); v.scrollTop = v.scrollHeight"); await page.wait_for_timeout(500)
        inside = await page.evaluate("""(() => { const f = document.querySelector('.tk-map-frame'), b = document.querySelector('.tk-map-body');
            if (!f || !b) return null; const r = f.getBoundingClientRect(), q = b.getBoundingClientRect();
            return r.bottom <= q.bottom + 1 && r.top >= q.top - 1; })()""")
        check("minimap: the frame stays inside, scrolled to the bottom", inside is not False, inside)
        await page.evaluate("document.querySelector('#takesView .tk-viewport').scrollTop = 0"); await page.wait_for_timeout(300)

        # 🗑 on 2a: 3 goes with it
        card = page.locator(f".tk-card[data-take='{t2a}']")
        await card.hover(); await card.locator(".tk-del").click()
        text = await confirm(page)
        check("the confirmation lists what goes with it", "clip 3" in text and "corbeille" in text.lower(), text)
        ids = {t["id"] for c in call(S, P + "/takes")["clips"] for t in c["takes"]}
        check("2a and 3 gone, 2b stays", t2a not in ids and t3 not in ids and t2b in ids)
        await page.click(".studio-trash-btn"); await page.wait_for_selector(".trash-row")
        check("the trash lists it", await page.locator(".trash-row").count() == 1)
        await page.click(".trash-row button.primary"); await page.wait_for_timeout(1500)
        ids = {t["id"] for c in call(S, P + "/takes")["clips"] for t in c["takes"]}
        check("restored from the trash", t2a in ids and t3 in ids and await page.locator(".trash-row").count() == 0)
        await page.evaluate("document.querySelectorAll('.tk-modal').forEach((m) => m.remove())")

        # Ctrl+Z: on the plan screen, not on the takes screen
        await plan_screen(page, master=True)
        name = page.locator("#editor .fields input").first
        old = await name.input_value()
        await name.fill(old + "_x"); await page.locator("#list").click(); await page.wait_for_timeout(900)
        await page.keyboard.press("Control+z"); await page.wait_for_timeout(500)
        check("Ctrl+Z on the plan screen undoes", (await page.locator("#editor .fields input").first.input_value()) == old)
        await page.keyboard.press("Control+y"); await page.wait_for_timeout(300)
        await takes_screen(page)
        before = await page.evaluate("JSON.stringify(H3Editor.state.plan)")
        await page.keyboard.press("Control+z"); await page.wait_for_timeout(300)
        check("Ctrl+Z on the takes screen changes nothing", before == await page.evaluate("JSON.stringify(H3Editor.state.plan)"))

        # a branch to the trash and back
        await page.locator(".tk-band-head button.danger").nth(2).click(); await page.wait_for_timeout(1500)   # empty: no question
        check("an empty branch deleted", len(call(S, P)["branches"]) == 2)
        tr = call(S, P + "/trash")["entries"]
        check("…in the trash", len(tr) == 1 and tr[0]["kind"] == "branch", tr)

        # 0.45: a generation still waiting can be chosen; « Utiliser ce plan… » makes a new branch from the selection
        j = call(S, P + "/generate", {"clip": 3, "after": t2b, "branch": "b1"})
        await page.evaluate("H3Takes.refresh()"); await page.wait_for_timeout(2500)
        ghost = page.locator(f".tk-ghost[data-take='{j['take_id']}']")
        await ghost.click(position={"x": 60, "y": 40}); await page.wait_for_timeout(1500)
        check("a waiting generation is chosen with a click", "chosen" in (await ghost.get_attribute("class") or ""))
        check("…the selection goes through it", "3" in await page.text_content(".tk-selbar"))
        await plan_screen(page)
        check("« Utiliser ce plan… » on the plan of the selection", await page.is_visible("#studioUsePlanBtn"))
        n = len(call(S, P)["branches"])
        await page.click("#studioUsePlanBtn"); await page.wait_for_selector(".use-plan")
        await page.fill(".use-plan input", "Prompts qui marchent"); await page.click(".use-plan .use-new"); await page.wait_for_timeout(1500)
        brs = call(S, P)["branches"]
        check("a new branch with the plan of the selection", len(brs) == n + 1 and brs[-1]["name"] == "Prompts qui marchent", [b["name"] for b in brs])
        await takes_screen(page)
        drain()
        await page.screenshot(path="a3_ui.png")
        print("ERRORS:", errs); await b.close()

try:
    asyncio.run(main())
finally:
    srv.terminate()
