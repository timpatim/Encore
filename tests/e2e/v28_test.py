"""v0.27–0.28: plan (≡) of a « generate » box and of a queued generation with the « Generation » block, fixed ▶▶ label,
upscale settings of a take (the branch's, changed in the folded form of the ▾ dialog), no upscale at the column level,
version banner, no « null » written in the dialogs."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
from playwright.async_api import async_playwright
import re
VERSION = re.search(r'STUDIO_VERSION = "([^"]+)"', open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "encore", "projects.py")).read()).group(1)
S = "http://127.0.0.1:8238"; M = "http://127.0.0.1:8771"
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
def prompt():
    return json.load(open("/tmp/mock_last_prompt.json"))
def upscale_nodes(wf):
    """(start width, upscale model) of the workflow sent to ComfyUI, or None without upscale."""
    if not any(int(k) >= 60 for k in wf): return None
    models = [n["inputs"].get("model_name") for n in wf.values() if "model_name" in n.get("inputs", {})]
    return wf["61"]["inputs"]["width"], models[0] if models else None
root = "/tmp/h3s_v28"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8238", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v28_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
M3D, M2D = "minimax_h3_latent_upscaler_3d_fp16.safetensors", "minimax_h3_latent_upscaler_2d_conv_v1_fp16.safetensors"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
call(S, P + "/branches", {})
call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}},
                             "upscale": {"enabled": False, "model": M3D, "start_mp": 0.2, "upscaler": "lbh3d"}}, "PUT")
try:
    check("ping gives the version", call(S, "/api/ping").get("version") == VERSION)
    cps = call(S, P + "/checkpoints")
    check("checkpoint before an import is in English", any("before importing" in (c.get("reason") or c.get("name") or "") for c in cps.get("checkpoints", cps if isinstance(cps, list) else [])), cps)
    # a clip (column) no longer has upscale settings: what is sent is ignored, the branch decides (off)
    names = [c["name"] for c in call(S, P)["plan"]["clips"]]
    r = call(S, P + "/clip-defaults", {"clip": names[0], "value": {"loras": [], "upscale": "on",
             "upscale_settings": {"upscaler": "lbh2d", "model": M2D, "start_mp": 0.3}}}, "PUT")
    check("no upscale kept at the column level", "upscale_settings" not in json.dumps(r) and not (r.get("clip_defaults") or {}).get(names[0]), r)
    job = call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True})
    time.sleep(2); run_mock(); time.sleep(3)
    t1 = [c for c in call(S, P + "/takes")["clips"] if c["index"] == 1][0]["takes"][-1]
    check("plain click: the branch's upscale (off)", not t1["record"]["studio"].get("upscale") and upscale_nodes(prompt()) is None, t1["record"]["studio"].get("upscale"))
    # a take with its own settings (« enabled » included)
    job = call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True,
                                    "upscale_settings": {"enabled": True, "upscaler": "lbh3d", "model": M3D, "start_mp": 0.25}})
    time.sleep(2); run_mock(); time.sleep(3)
    t1b = [c for c in call(S, P + "/takes")["clips"] if c["index"] == 1][0]["takes"][-1]
    up = t1b["record"]["studio"].get("upscale") or {}
    check("take made with its own settings", up.get("source") == "take" and up.get("model") == M3D and up.get("settings", {}).get("start_mp") == 0.25, up)
    # clip 2 with its own settings too (its ▾ starts again from them, below)
    call(S, P + "/generate", {"clip": 2, "branch": "b1", "parent": t1b["id"].split("_")[1], "random": True,
                              "upscale_settings": {"enabled": True, "upscaler": "lbh3d", "model": M3D, "start_mp": 0.25}})
    time.sleep(2); run_mock(); time.sleep(3)
    t2 = [c for c in call(S, P + "/takes")["clips"] if c["index"] == 2][0]["takes"][-1]
    # plan of a queued generation
    call(S, "/api/queue/pause", {})
    job = call(S, P + "/generate", {"clip": 2, "branch": "b1", "parent": t1b["id"].split("_")[1], "random": True})
    jp = call(S, f"{P}/jobs/{job['id']}/plan")
    check("plan of a queued generation", jp.get("source") == "job" and jp.get("snapshot", {}).get("name") == names[1], jp)
    check("plan of a queued generation gives its models", ((jp.get("generation") or {}).get("models") or {}).get("unet_name"), jp.get("generation"))
    check("plan of an unknown generation refused", call(S, f"{P}/jobs/jnope/plan").get("HTTP") == 400)

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []; nulls = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            check("no version banner when page and server agree", await page.locator("#encoreVersionBanner").count() == 0)
            await page.click("#viewTabs >> text=Takes"); await page.wait_for_timeout(1200)
            # ▶▶: fixed label, inside the branch header
            fill = page.locator(".tk-band-head .tk-fill").first
            text, title = await fill.text_content(), await fill.get_attribute("title")
            fb, hb = await fill.bounding_box(), await page.locator(".tk-band-head").first.bounding_box()
            check("▶▶ fixed label, details in the tooltip", text.strip() == "▶▶ complete" and "\n" in (title or ""), (text, title))
            check("▶▶ inside the branch header", fb["x"] + fb["width"] <= hb["x"] + hb["width"] + 1, (fb, hb))
            # ≡ on the queued generation
            ghost = page.locator(".tk-ghost").first; await ghost.hover(); await ghost.locator(".tk-plan-btn").click(); await page.wait_for_timeout(800)
            head = await page.locator(".tk-plan-modal .tk-box-head b").text_content()
            check("≡ of a queued generation", "generation of clip 2" in head and await page.locator(".tk-plan-banner").count() == 1, head)
            check("≡ shows the « Generation » block", await page.locator(".tk-plan-modal .tk-plan-gen").count() == 1)
            nulls.append(await page.locator(".tk-plan-modal").inner_text())
            await page.screenshot(path="v28_jobplan.png")
            await page.click(".tk-plan-modal >> text=Close"); await page.wait_for_timeout(300)
            # ≡ on a « generate » box (placeholder) or « next clip » box
            ph = page.locator(".tk-placeholder").first; await ph.hover(); await ph.locator(".tk-plan-btn").click(); await page.wait_for_timeout(600)
            head = await page.locator(".tk-plan-modal .tk-box-head b").text_content()
            check("≡ of a « generate » box opens the clip's plan, nothing launched", "Plan of clip" in head and len([j for j in call(S, P + "/jobs")["jobs"] if j["status"] == "queued"]) == 1, head)
            check("≡ of a box: generation if launched now", "if launched now" in await page.locator(".tk-plan-modal .tk-plan-gen").inner_text())
            nulls.append(await page.locator(".tk-plan-modal").inner_text())
            await page.locator(".tk-plan-modal .tk-plan-gen").scroll_into_view_if_needed(); await page.screenshot(path="v28_boxplan.png")
            await page.click(".tk-plan-modal >> text=Close"); await page.wait_for_timeout(300)
            # ▾ dialog: own settings for one take
            card = page.locator(f".tk-card[data-take='{t2['id']}']"); await card.hover()
            await card.locator(".tk-split-arrow").first.click(); await page.wait_for_timeout(800)
            dl = page.locator(".tk-modal").last
            line = dl.locator(".studio-up-line")
            check("▾ dialog: folded, « changed for this take » from the take's settings", "Changed for this take" in await line.inner_text()
                  and await dl.locator(".studio-up-sum").count() == 0, await line.inner_text())
            await line.locator("button:has-text('modify')").click(); await page.wait_for_timeout(300)
            check("▾ dialog: « modify » unfolds the form with « enabled »", await dl.locator(".studio-up-sum").count() == 1
                  and await dl.locator(".tk-row:has(label:text('Enabled'))").count() == 1)
            await page.screenshot(path="v28_takedialog.png")
            nulls.append(await dl.inner_text())
            await line.locator("button:has-text('reset')").click(); await page.wait_for_timeout(300)
            check("▾ dialog: reset gives the branch's settings back", "Like branch" in await line.inner_text(), await line.inner_text())
            await dl.locator(".tk-box-head button").click(); await page.wait_for_timeout(400)
            # clip (column) dialog: LoRA only
            await page.locator(".tk-col-head").nth(1).locator(".tk-clipdef").click(); await page.wait_for_timeout(700)
            dl = page.locator(".tk-modal").last
            check("column dialog: LoRA only, no upscale", "upscale" not in (await dl.inner_text()).lower() and await dl.locator(".studio-loras").count() == 1, await dl.inner_text())
            nulls.append(await dl.inner_text())
            await dl.locator(".tk-box-head button").click(); await page.wait_for_timeout(500)
            # the queue window and the folder chooser had « null » parts too
            await page.click("#studioQueueBtn"); await page.wait_for_timeout(600)
            nulls.append(await page.locator(".tk-modal").last.inner_text())
            await page.locator(".tk-modal").last.locator(".tk-box-head button").click(); await page.wait_for_timeout(300)
            bad = [t[:80] for t in nulls if "null" in t]
            check("no « null » written in the windows", not bad, bad)
            # banner: a page built for another version
            await page.route("**/", lambda route: route.fulfill(body=urllib.request.urlopen(S + "/").read().decode().replace(f'window.ENCORE_BUILD = "{VERSION}"', 'window.ENCORE_BUILD = "0.20"'), content_type="text/html"))
            await page.goto(S + "/"); await page.wait_for_timeout(1500)
            check("version banner when the server is another version", await page.locator("#encoreVersionBanner").count() == 1)
            await page.screenshot(path="v28_banner.png")
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    call(S, "/api/queue/resume", {})
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
