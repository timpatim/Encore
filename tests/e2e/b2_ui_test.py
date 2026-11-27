"""Chantier B, lot B2 (interface): the library of the plan screen (subjects, files), a subject created from an unknown
@ in its window, the settings of a subject in a clip, anchors, the H3 prompt composed by the server and written by
hand, the speakers found (S1, S2…), the « / » menu of the camera, the Resources window (unused files) and deleting a
project."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8249"; M = "http://127.0.0.1:8771"
OK = []


def call(path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(S + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}


def check(label, cond, detail=""):
    OK.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))


root = "/tmp/h3s_b2ui"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8249", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "b2ui_srv.log"), "w"))
time.sleep(1.5)
P = "/api/projects/rue"
call("/api/projects", {"name": "rue", "mode": "free"})
call(P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png"), fixture("v20_beach.png"), fixture("v20_robot.png")):
    call(f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1680, "height": 1050})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
        await plan_screen(page, master=True, wait=1500)
        check("library: the subjects of the plan", await page.eval_on_selector_all("#side .sx-lib-subject", "e => e.map(x => x.dataset.subject)") == ["fillette", "homme", "rue"])
        check("library: the pictures of the project", await page.locator("#side .sx-files .sx-file").count() == 4)

        # an unknown @ → « create »: the subject window
        ta = page.locator('textarea[data-sec="summary"]')
        await ta.click(); await page.keyboard.press("End"); await page.keyboard.type(" Avec @chie")
        await page.wait_for_timeout(300)
        check("@ completion", await page.is_visible(".sx-ac"))
        await page.keyboard.type("n."); await page.wait_for_timeout(600)
        check("an unknown subject is shown with « create »", await page.locator("#sxUses .sx-chipX").count() == 1)
        await page.click("#sxUses button"); await page.wait_for_timeout(400)
        await page.fill(".sx-sdesc", "a small brown dog")
        await page.select_option(".sx-skind", "object")
        await page.select_option(".sx-addpic", "refs/images/v20_robot.png")
        await page.fill(".sx-role", "fur")
        await page.click(".sx-save"); await page.wait_for_timeout(800)
        subj = await page.evaluate("H3Editor.state.plan.subjects.chien")
        check("subject created with its kind, description and picture", subj and subj["kind"] == "object" and subj["pictures"][0]["role"] == "fur", subj)

        # settings of a subject in the clip, last-frame anchor
        await page.select_option('.sx-use[data-subject="rue"] .sx-keep', "loose")
        await page.fill('.sx-use[data-subject="rue"] .sx-note', "only the shop fronts"); await page.wait_for_timeout(300)
        await page.select_option(".sx-anchor >> nth=1 >> select", "refs/images/rue.png"); await page.wait_for_timeout(1500)
        check("speakers found in the lines", await page.eval_on_selector_all(".sx-speaker", "e => e.map(x => x.textContent + ' ' + x.closest('.sx-use').dataset.subject)")
              == ["🗣 S1 fillette", "🗣 S2 homme"])

        # « / »: the camera
        d = page.locator('textarea[data-sec="description"]')
        await d.click(); await page.keyboard.press("Control+End"); await page.keyboard.type(" /push")
        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter"); await page.wait_for_timeout(200)
        check("a move asks its amplitude and speed", await page.locator(".sx-ac-item").count() == 9)
        for _ in range(4):
            await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter"); await page.wait_for_timeout(200)
        await page.keyboard.type("@rue. /coupe"); await page.wait_for_timeout(300)
        await page.keyboard.press("Enter"); await page.keyboard.type("00:05.000"); await page.wait_for_timeout(300)
        text = await d.input_value()
        check("camera sentence and cut inserted", "The camera pushes in with small amplitude at slow speed toward @rue." in text
              and text.endswith("[Shot 2] At 00:05.000, the shot cuts to "), repr(text[-160:]))
        await page.wait_for_timeout(1500)

        # the H3 prompt, then written by hand
        await page.click(".sx-tab-h3"); await page.wait_for_timeout(800)
        h3 = await page.input_value("textarea.sx-h3")
        check("composed prompt: subject, anchor, retention", "is an object: a small brown dog; fur from <Picture" in h3 and "is the last frame of [Shot 2]" in h3
              and "weak_reference - only the shop fronts" in h3 and "<Subject 2> (S1), excited" in h3 and "@" not in h3, h3[:300])
        check("legend of the numbers", await page.locator("#sxLegend .sx-chip").count() >= 5)
        check("no stray text in the legend", "null" not in await page.locator("#sxLegend").inner_text())
        await page.click("textarea.sx-h3"); await page.keyboard.press("Control+End"); await page.keyboard.type("\nEXTRA")
        await page.wait_for_timeout(500)
        await page.click("button:has-text('Champs')"); await page.wait_for_timeout(500)
        check("a prompt written by hand: banner", await page.is_visible(".sx-override"))
        await page.click("#studioBackBtn"); await page.wait_for_timeout(1500)
        plan = call(P + "/plan?branch=b1")["plan"]
        c1 = plan["clips"][0]
        check("saved: anchor, settings, prompt written by hand", c1.get("anchors") == {"last": "rue"}
              and c1.get("subjects") == [{"name": "rue", "keep": "loose", "note": "only the shop fronts"}]
              and (c1.get("prompt_override") or "").endswith("EXTRA") and "v20_robot" in plan["files"], c1)

        # Resources: states, delete the unused files
        await page.click("text=Ressources…"); await page.wait_for_timeout(1200)
        states = await page.eval_on_selector_all(".studio-res", "e => e.map(x => x.dataset.path + ':' + (x.querySelector('.res-state') || {}).textContent)")
        check("resources: used / unused", "refs/images/rue.png:utilisé" in states and "refs/images/v20_beach.png:inutilisé" in states, states)
        page.once("dialog", lambda d_: asyncio.ensure_future(d_.accept()))
        await page.click(".res-delete-unused"); await page.wait_for_timeout(500)
        await page.click(".h3-dlg button:has-text('Oui')"); await page.wait_for_timeout(1200)
        left = [r["path"] for r in call(P + "/resources")["images"]]
        check("unused file deleted, the others kept", "refs/images/v20_beach.png" not in left and "refs/images/rue.png" in left, left)
        await page.evaluate("document.querySelectorAll('.tk-modal').forEach((m) => m.remove())")

        # delete the project (for good)
        await page.click("text=Projets"); await page.wait_for_timeout(800)
        await page.click(".studio-card-del"); await page.wait_for_timeout(600)
        check("delete project: a confirmation that says what goes", "irréversible" in (await page.text_content(".h3-dlg")))
        await page.click(".h3-dlg button:has-text('Oui')"); await page.wait_for_timeout(1000)
        check("project deleted", await page.locator(".studio-card").count() == 0 and not os.path.isdir(root + "/projets/rue"))
        check("no page error", not errs, errs)
        await b.close()

try:
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
