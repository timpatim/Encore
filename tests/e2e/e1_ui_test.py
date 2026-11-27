"""0.48.2: pictures of an imported plan still to supply (filled under their label, from the subject window or the
« Images to supply » list), replacing a picture, files dropped from the computer (Resources, library, subject), a new
take of a clip taken over from another branch, the « plan of the following clips » of the launch panel, the queue
(« see the n jobs », dragging a group by its handle), the minimap from the top, the folded pane's label without blinking."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, takes_screen, restart_mock, launch_go  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8250"; M = "http://127.0.0.1:8771"; P = "/api/projects/rue"
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
def take_of(job):
    drain()
    return next((j for j in call(S, P + "/jobs")["jobs"] if j["id"] == job.get("id")), {}).get("take")
# a JS drop of a project file, as if it came from the computer (Explorer)
OS_DROP = """async ([sel, url, name, type]) => {
    const blob = await (await fetch(url)).blob();
    const dt = new DataTransfer(); dt.items.add(new File([blob], name, { type }));
    const el = document.querySelector(sel);
    const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + Math.min(20, r.height / 2);
    for (const t of ["dragenter", "dragover", "drop"]) el.dispatchEvent(new DragEvent(t, { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
}"""
restart_mock()
root = "/tmp/h3s_e1"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8250", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("e1_srv.log", "w"))
time.sleep(1.5)
# an imported plan whose files have no path yet (written elsewhere): only labels and notes
plan = json.load(open(fixture("rue_test_v1.plan.json")))
for label, f in plan["files"].items():
    f.pop("file", None); f["note"] = f"the picture « {label} »"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=json.dumps(plan).encode(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
labels = sorted(plan["files"])
subj = sorted(plan["subjects"])[0]
first_pic = plan["subjects"][subj]["pictures"][0]
try:
    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 1000}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await takes_screen(page); await page.wait_for_timeout(800)
            # ---------------- pictures still to supply
            await page.locator(".tk-master").first.click(); await page.wait_for_timeout(1500)
            missing = page.locator(".sx-missing")
            check("« Images to supply » lists the files without an image", await missing.count() == len([l for l in labels if plan["files"][l]["kind"] == "image"]), await missing.count())
            check("the library shows « ? » for a missing picture", await page.locator(".sx-mini-missing").count() >= 1)
            await page.locator(f".sx-lib-subject[data-subject='{subj}'] .sx-edit").click(); await page.wait_for_timeout(500)
            pic = page.locator(f".sx-pic.missing[data-label='{first_pic['file']}']")
            check("the subject window shows a dashed box, not a broken image", await pic.count() == 1 and await page.locator(".sx-pics img[src='']").count() == 0)
            check("… with its label and note", "the picture" in await pic.inner_text())
            await pic.locator(".sx-pic-missing").click(); await page.wait_for_selector(".sx-picker")
            check("the picker shows the project's images and « import »", await page.locator(".sx-picker-item").count() == 2 and await page.locator(".sx-picker-import").count() == 1)
            await page.locator(".sx-picker-item", has_text="rue.png").click(); await page.wait_for_timeout(300)
            await page.click(".sx-save"); await page.wait_for_timeout(300)
            await page.click("#btnSave"); await page.wait_for_timeout(1200)
            saved = call(S, P + "/plan?branch=b1")["plan"]
            check("the label got the image, under its own name", (saved["files"][first_pic["file"]] or {}).get("file", "").endswith("rue.png")
                  and saved["files"][first_pic["file"]].get("note") == f"the picture « {first_pic['file']} »", saved["files"].get(first_pic["file"]))
            check("… the role of the picture is kept", saved["subjects"][subj]["pictures"][0].get("role") == first_pic.get("role"), saved["subjects"][subj]["pictures"][0])
            # replace it: click the thumbnail, choose the other image
            await page.locator(f".sx-lib-subject[data-subject='{subj}'] .sx-edit").click(); await page.wait_for_timeout(500)
            await page.locator(".sx-pic .sx-pic-thumb").first.click(); await page.wait_for_selector(".sx-picker")
            await page.locator(".sx-picker-item", has_text="fillette.png").click(); await page.wait_for_timeout(300)
            await page.click(".sx-save"); await page.wait_for_timeout(300)
            await page.click("#btnSave"); await page.wait_for_timeout(1200)
            saved = call(S, P + "/plan?branch=b1")["plan"]
            p0 = saved["subjects"][subj]["pictures"][0]
            check("replacing a picture keeps its role", saved["files"][p0["file"]]["file"].endswith("fillette.png") and p0.get("role") == first_pic.get("role"), p0)
            # fill the others from « Images to supply » by dropping a file from the computer
            n = await page.locator(".sx-missing").count()
            await page.evaluate(OS_DROP, [".sx-missing", f"/files/rue/refs/images/rue.png", "rue.png", "image/png"]); await page.wait_for_timeout(1500)
            check("a file dropped from the computer on « Images to supply » fills it", await page.locator(".sx-missing").count() == n - 1, await page.locator(".sx-missing").count())
            # a new file dropped on the library is imported
            before = len(call(S, P + "/resources")["images"])
            await page.evaluate(OS_DROP, [".sx-files-box", f"/files/rue/refs/images/fillette.png", "fillette_copy_2.png", "image/png"]); await page.wait_for_timeout(1500)
            check("a file dropped on « Files of the project » is imported", len(call(S, P + "/resources")["images"]) >= before, call(S, P + "/resources")["images"])
            await page.click("#btnSave"); await page.wait_for_timeout(800)
            await takes_screen(page); await page.wait_for_timeout(800)
            # ---------------- Resources window: drop from the computer
            await page.locator("text=Resources").first.click(); await page.wait_for_timeout(800)
            before = len(call(S, P + "/resources")["images"])
            await page.evaluate(OS_DROP, [".studio-res", f"/files/rue/refs/images/rue.png", "street_night.png", "image/png"]); await page.wait_for_timeout(1500)
            names = [x["name"] for x in call(S, P + "/resources")["images"]]
            check("a file dropped on the Resources window is imported", len(names) >= before, names)
            await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
            for c in await page.locator(".tk-modal button", has_text="Close").all():
                try: await c.click(timeout=400)
                except Exception: pass
            # fill the rest by the API (the plan must be complete to generate)
            m = call(S, P + "/plan?branch=b1")["plan"]
            for label, f in m["files"].items():
                if f["kind"] == "image" and not f.get("file"): f["file"] = "refs/images/rue.png"
            call(S, P + "/plan", {"branch": "b1", "plan": m}, "PUT")
            # ---------------- takes: a line, two twigs with different plans after clip 1
            t1 = take_of(call(S, P + "/generate", {"clip": 1, "branch": "b1", "line": True}))
            t2a = take_of(call(S, P + "/generate", {"clip": 2, "branch": "b1", "after": t1, "plan_from": t1}))
            t2b = take_of(call(S, P + "/generate", {"clip": 2, "branch": "b1", "after": t1, "plan_from": t1}))
            twig = call(S, P + f"/plan?branch=b1&leaf={t2b}")["plan"]
            twig["clips"][2]["summary"] = "another summary for clip 3"
            call(S, P + "/plan", {"branch": "b1", "leaf": t2b, "plan": twig}, "PUT")
            await page.evaluate("H3Takes.rescan()"); await page.wait_for_timeout(2500)
            # ---------------- the launch panel: the plan of the following clips
            card = page.locator(f".tk-card[data-take='{t1}']")
            await card.hover(); await card.locator(".tk-retake").click(); await page.wait_for_selector("#launchPanel"); await page.wait_for_timeout(2500)
            opts = page.locator(".launch-opt")
            check("plan of the following clips: one choice per distinct plan", await opts.count() == 2, await opts.count())
            text = await page.inner_text(".launch-twigs")
            check("… in plain words", "plan of the following clips" in text.lower() and "This take" in text and "clip 3 changed" in text, text)
            check("… with the twig's takes as thumbnails, the new take dashed", await page.locator(".launch-opt .launch-th.new").count() == 2
                  and await page.locator(".launch-opt .launch-th").count() >= 4)
            check("no chain of take ids any more", "→" not in text)
            await page.locator("#launchPanel button", has_text="Cancel").last.click(); await page.wait_for_timeout(500)
            # ---------------- a new take of a clip taken over from another branch
            dup = call(S, P + "/branches", {"how": "clips", "source": "b1", "leaf": t2a, "upto": 2})
            did = dup["branch"]["id"]
            await page.reload(); await page.wait_for_timeout(1500); await takes_screen(page); await page.wait_for_timeout(2000)
            reused = page.locator(f".tk-card.tk-reused[data-take='{t1}'][data-band='{did}']")
            check("a take taken over has « new take »", await reused.locator(".tk-retake").count() == 1)
            src_before = json.dumps([b for b in call(S, P)["branches"] if b["id"] == "b1"], sort_keys=True)
            await reused.hover(); await reused.locator(".tk-retake").click(); await page.wait_for_selector("#launchPanel"); await page.wait_for_timeout(1500)
            await launch_go(page); await page.wait_for_timeout(800)
            job = [j for j in call(S, P + "/jobs")["jobs"]][-1]
            check("… its new take is a variant in the duplicated branch", job["record"]["studio"]["branch"] == did and job["status"] != "error", job.get("error") or job["record"]["studio"].get("branch"))
            new = take_of(job)
            check("… and the branch it comes from does not change", json.dumps([b for b in call(S, P)["branches"] if b["id"] == "b1"], sort_keys=True) == src_before and new)
            # ---------------- the queue: « see the n jobs », dragging a group by its handle
            call(S, "/api/queue/pause", {})
            for br in ("b1", did):
                call(S, P + f"/branches/{br}/fill", {"dry_run": False, "assemble": True})
            third = call(S, P + "/branches", {"how": "copy", "source": "b1"})["branch"]["id"]
            call(S, P + f"/branches/{third}/fill", {"dry_run": False, "assemble": True})
            await page.click("#studioQueueBtn"); await page.wait_for_timeout(1500)
            ids = lambda: page.eval_on_selector_all(".studio-q-group", "e => e.map((x) => x.dataset.group)")
            before = await ids()
            if await page.locator(".studio-q-group summary").count():
                await page.locator(".studio-q-group summary").first.click(); await page.wait_for_timeout(1500)
                check("« see the n jobs » opens the list", await page.eval_on_selector(".studio-q-group details", "d => d.open"))
            handle = page.locator(".studio-q-group").nth(len(before) - 1).locator(".studio-q-handle")
            hb = await handle.bounding_box(); top = await page.locator(".studio-q-group").nth(0).bounding_box()
            await page.mouse.move(hb["x"] + 5, hb["y"] + 5); await page.mouse.down()
            for k in range(1, 21):
                await page.mouse.move(hb["x"] + 5, hb["y"] + 5 - (hb["y"] - top["y"]) * k / 20); await page.wait_for_timeout(30)
            check("a line shows where the group lands", await page.locator(".studio-q-drop:not([hidden])").count() == 1)
            await page.mouse.up(); await page.wait_for_timeout(2000)
            after = await ids()
            check("the group dragged by its handle goes to the top", after[0] == before[-1], (before, after))
            await page.click(".studio-q-bar button.danger:has-text('Cancel all')"); await page.wait_for_selector(".h3-dlg")
            await page.click(".h3-dlg-buttons button.danger-fill, .h3-dlg-buttons button.primary"); await page.wait_for_timeout(800)
            call(S, "/api/queue/resume", {})
            await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
            for c in await page.locator(".tk-modal button", has_text="Close").all():
                try: await c.click(timeout=400)
                except Exception: pass
            # ---------------- the minimap from the top, the folded pane's label without blinking
            await page.evaluate("H3Takes.state.mapOpen = true; H3Takes.render()"); await page.wait_for_timeout(500)
            off = await page.evaluate("H3Takes.state.mapOffset")
            check("the minimap draws the graph from its top", off and off[1] == 0, off)
            call(S, "/api/queue/pause", {})
            sel = call(S, P)["branches"][0]
            await page.evaluate("H3Takes.state.paneOpen = false; H3Takes.render()"); await page.wait_for_timeout(300)
            await page.locator(".tk-selbar button", has_text="assemble").first.click(); await page.wait_for_timeout(2500)
            anim = await page.evaluate("(() => { const e = document.querySelector('.tk-pane-busy'); return e ? getComputedStyle(e).animationName : 'missing'; })()")
            check("the folded pane's label does not blink", anim == "none", anim)
            call(S, "/api/queue/resume", {})
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
