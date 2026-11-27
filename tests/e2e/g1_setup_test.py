"""0.50: the installation screen without ComfyUI-H3-ClipPlan: the packs Encore asks for (MultiRef and VHS required,
no plugin), ComfyUI's own nodes it needs, the ffmpeg it found, and an old ComfyUI-H3-ClipPlan folder pointed out."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, restart_mock  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8254"; M = "http://127.0.0.1:8771"
OK = []
def check(name, cond, info=""):
    OK.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
def call(path):
    req = urllib.request.Request(S + path, headers={"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
restart_mock()
root = "/tmp/h3s_g1"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
comfy = root + "/ComfyUI"
for d in ("custom_nodes/ComfyUI-H3-ClipPlan", "custom_nodes/ComfyUI-H3-Motion-Context-MultiRef", "custom_nodes/ComfyUI-VideoHelperSuite", "models"):
    os.makedirs(os.path.join(comfy, d))
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en", "comfy_dir": comfy}, open(cfg, "w"))
ffmpeg = shutil.which("ffmpeg") or ""
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8254", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL,
                       stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "g1_srv.log"), "w"), env=dict(os.environ, H3_FFMPEG=ffmpeg))
time.sleep(1.5)
try:
    st = call("/api/setup")
    ids = {p["id"]: p for p in st["packs"]}
    check("ComfyUI-H3-ClipPlan is no longer asked for", "h3clipplan" not in ids, sorted(ids))
    check("MultiRef and VideoHelperSuite stay required", ids.get("multiref", {}).get("required") and ids.get("vhs", {}).get("required"))
    check("…with the nodes Encore now uses", {"MiniMaxH3MotionContextSaveLatent", "MiniMaxH3MotionContextLoadLatent", "MiniMaxH3GeneratedAVMaskedContext",
          "MiniMaxH3SongMaskedAVContext", "MiniMaxH3ExistingVideoMaskedContext"} <= set(ids["multiref"].get("nodes") or [])
          and "VHS_LoadVideo" in (ids["vhs"].get("nodes") or []), (ids["multiref"].get("nodes"), ids["vhs"].get("nodes")))
    check("the fake ComfyUI has every node needed: Encore can be used", st["required_ok"] and not st["core_missing"], (st["required_ok"], st["core_missing"]))
    check("the ffmpeg found is given", st.get("ffmpeg") == ffmpeg and ffmpeg, st.get("ffmpeg"))
    check("an old ComfyUI-H3-ClipPlan folder is seen", st.get("old_plugin") is True)

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1400, "height": 1000}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.wait_for_timeout(1500)
            home = page.locator("#studioHome button", has_text="Installation")
            await (home.first if await home.count() else page.locator("text=Installation…").first).click(); await page.wait_for_timeout(1500)
            check("the screen lists no ComfyUI-H3-ClipPlan pack", "ComfyUI-H3-ClipPlan" not in await page.inner_text(".studio-packs"))
            check("the screen shows ffmpeg", ffmpeg in await page.inner_text(".setup-ffmpeg .ok"))
            check("…and says the old plugin is no longer used", await page.locator(".setup-old-plugin").count() == 1
                  and "no longer uses it since 0.50" in await page.inner_text(".setup-old-plugin"))
            await page.screenshot(path=os.path.join(ENCORE, "tests", "e2e", "out", "g1_setup.png"), full_page=True)
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
