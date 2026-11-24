"""Chantier A, lot A2 (interface): « + clip suivant » after every take (pre-filled from the master plan or a new
clip); ↻ on a generation still waiting; « Importer un plan… » only on the master plan screen; the new branch window
(duplicate with the clips of the selection: dimmed in the new band); the branch settings window and the project
essence greyed once there are takes."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8245"; M = "http://127.0.0.1:8771"


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


root = "/tmp/h3s_a2ui"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8245", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "a2ui_srv.log"), "w"))
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
one = json.load(open(fixture("rue_test_v1.plan.json"))); one["clips"] = one["clips"][:1]
call(S, P + "/import-plan?filename=rue.json", raw=json.dumps(one).encode(), method="POST")
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


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1600, "height": 1000}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1800)
        check("no import button in the project bar", await page.locator(".studio-bar button:has-text('Importer un plan')").count() == 0)

        # clip 1, then the next clip although the master plan has only one clip
        await page.click(".tk-placeholder >> nth=0 >> .tk-plus"); await launch_go(page); drain(); await page.wait_for_timeout(2500)
        check("a « + clip suivant » box after the take", await page.locator(".tk-slot").count() == 1)
        await page.click(".tk-slot >> nth=0"); await page.wait_for_selector("#launchPanel")
        await page.wait_for_timeout(800)
        msg = " ".join(await page.locator("#launchPanel .warnline").all_text_contents())
        check("the panel offers a new clip 2", "nouveau clip" in (msg or "").lower() and await page.evaluate("H3Editor.state.plan.clips.length") == 2, msg)
        c1, c2 = await page.evaluate("[H3Editor.state.plan.clips[0], H3Editor.state.plan.clips[1]]")
        check("…a copy of clip 1 that continues it", c2["continue"] is True and c2["name"] == "clip_002" and c2["refs"] == c1["refs"]
              and c2.get("dialogue") == c1.get("dialogue") and c2["frames"] == c1["frames"] and c2["prompt"] != c1["prompt"], c2.get("name"))
        await launch_go(page); drain(); await page.wait_for_timeout(2500)
        sel = {c["index"]: c["selected"] for c in call(S, P + "/takes")["clips"]}
        check("clip 2 made after clip 1", bool(sel.get(2)), sel)

        # ↻ on a generation still waiting (the fake ComfyUI does not run it yet)
        t2 = sel[2]
        entry = dict(call(S, P + f"/plan?leaf={t2}")["plan"]["clips"][1], name="clip_003")
        out = call(S, P + "/generate", {"clip": 3, "after": t2, "entry": entry})
        check("clip 3 queued", out.get("status") == "queued", out)
        await page.evaluate("H3Takes.refresh()"); await page.wait_for_timeout(2500)
        ghost = page.locator(".tk-ghost .tk-retake")
        check("↻ on a waiting generation", await ghost.count() == 1)
        if await ghost.count():
            await ghost.first.click(); await page.wait_for_selector("#launchPanel")
            await page.wait_for_timeout(800)
            job = next(j for j in call(S, P + "/jobs")["jobs"] if j["kind"] == "clip" and j["status"] in ("queued", "running"))
            check("…pre-filled with its seed", (await page.input_value("#launchPanel .launch-seed")) == str(job["seed"]))
            await page.evaluate("H3Launch.close()")
        drain(); await page.wait_for_timeout(1500)

        # import: only on the master plan screen, greyed once the branch has takes
        await plan_screen(page, master=True)
        imp = page.locator("#studioImportBtn")
        check("import on the master plan screen, greyed (takes)", await imp.is_visible() and await imp.is_disabled() and "prises" in (await imp.get_attribute("title")))
        await takes_screen(page)

        # duplicate with the clips of the selection (1 → 2)
        await page.click(".tk-newbranch"); await page.wait_for_selector(".br-new")
        await page.click(".br-new label:has-text('avec les clips')")
        await page.wait_for_timeout(300)
        check("the window lists the references kept", await page.locator(".br-refs .br-kept").count() >= 1)
        await page.click(".tk-modal button.primary:has-text('Créer')"); await page.wait_for_timeout(2000)
        reused = page.locator(".tk-card.tk-reused")
        check("the new band shows the 3 clips taken over, dimmed", await reused.count() == 3, await reused.count())
        check("no ↻ on a clip taken over", await page.locator(".tk-card.tk-reused .tk-retake").count() == 0)
        check("a « + clip suivant » box after the last clip taken over", await page.locator(".tk-slot").count() >= 2)

        # branch settings: size and used references greyed with the reason; generation settings free
        await page.click(".tk-brsettings >> nth=0"); await page.wait_for_selector(".br-settings")
        size = page.locator(".br-settings .br-size input").first
        check("size greyed with the reason", await size.is_disabled() and "Figé" in (await size.get_attribute("title") or ""))
        used = page.locator(".br-settings .tk-ref select").first
        check("a used reference greyed", await used.is_disabled())
        check("LoRA still free", await page.locator(".br-settings .studio-upscale button:not([disabled])").count() >= 1)
        await page.keyboard.press("Escape"); await page.evaluate("document.querySelectorAll('.tk-modal').forEach((m) => m.remove())")

        # project settings: the essence is greyed once the project has takes
        await page.click("text=Réglages du projet"); await page.wait_for_selector(".br-essence select")
        check("project mode greyed (takes)", await page.locator(".br-essence select").first.is_disabled())
        await page.evaluate("document.querySelectorAll('.tk-modal').forEach((m) => m.remove())")
        await page.screenshot(path="a2_ui.png")
        print("ERRORS:", errs); await b.close()

try:
    asyncio.run(main())
finally:
    srv.terminate()
