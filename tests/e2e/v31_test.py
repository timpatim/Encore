"""v0.31: resources — big files imported piece by piece (progress window, cancel leaves nothing), deletion refused
while the project uses a file, after a warning when only a checkpoint or takes need it, directly otherwise."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, plan_screen, takes_screen, launch_go  # noqa: E402
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
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}

root = "/tmp/h3s_v31"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8242", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v31_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
VID = f"{root}/projets/rue/refs/videos"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
LONG = "a_very_long_file_name_for_a_song_that_never_fits_in_its_box_at_all.wav"
call(S, f"{P}/resources?kind=songs&filename={LONG}", raw=open(fixture("v20_song.wav"), "rb").read(), method="POST")
call(S, f"{P}/resources?kind=images&filename=another_picture_with_a_name_much_too_long_for_the_grid.png", raw=open(fixture("rue.png"), "rb").read() + b"x", method="POST")
big = "/tmp/v31_big.mp4"
with open(big, "wb") as handle:
    handle.write(open(fixture("v30_intro.mp4"), "rb").read())
    handle.write(os.urandom(40 * 1024 * 1024))
try:
    # ---- streaming import (API): a 40 MB file, then the same content again
    t0 = time.time()
    first = call(S, f"{P}/resources?kind=videos&filename=big.mp4", raw=open(big, "rb").read(), method="POST")
    check("a 40 MB video imported", first.get("path") == "refs/videos/big.mp4" and os.path.getsize(f"{VID}/big.mp4") == os.path.getsize(big), first)
    again = call(S, f"{P}/resources?kind=videos&filename=other_name.mp4", raw=open(big, "rb").read(), method="POST")
    check("the same content under another name: not copied twice", again.get("reused") and again.get("path") == "refs/videos/big.mp4", again)
    check("no piece left behind", not [f for f in os.listdir(VID) if f.endswith(".part")], os.listdir(VID))
    wrong = call(S, f"{P}/resources?kind=images&filename=fake.png", raw=b"not a picture at all", method="POST")
    check("a wrong picture is refused and leaves nothing", "error" in wrong and not os.path.exists(f"{root}/projets/rue/refs/images/fake.png")
          and not [f for f in os.listdir(f"{root}/projets/rue/refs/images") if f.endswith(".part")], wrong)

    # ---- deletion
    call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")
    use = call(S, f"{P}/resources/usage?path=refs/images/fillette.png")
    check("usage: the picture of « fillette » in Branch 1", use["current"] and "fillette" in use["current"][0], use)
    refused = call(S, f"{P}/resources?path=refs/images/fillette.png", method="DELETE")
    check("deleting a picture the branch uses: refused, says where", refused.get("code") == "in_use" and "Branch 1" in refused.get("error", "")
          and os.path.exists(f"{root}/projets/rue/refs/images/fillette.png"), refused)
    plan = call(S, P)["plan"]
    plan["refs"]["intro"] = "start video"; plan["start_video"] = {"ref": "intro", "start": 0, "end": 4}; plan["clips"][0]["continue"] = True
    call(S, P + "/plan", plan, "PUT")
    call(S, P + "/start-video", {"file": "refs/videos/big.mp4"}, "PUT")
    refused = call(S, f"{P}/resources?path=refs/videos/big.mp4", method="DELETE")
    check("deleting the start video: refused", refused.get("code") == "in_use" and "start video" in refused.get("error", ""), refused)
    call(S, P + "/start-video", {"file": None}, "PUT")
    # 0.42: no checkpoints any more; no take was made with it: deleted at once
    done = call(S, f"{P}/resources?path=refs/videos/big.mp4", method="DELETE")
    check("a file nothing uses any more: deleted at once", done.get("deleted") == "refs/videos/big.mp4" and not os.path.exists(f"{VID}/big.mp4"), done)
    shutil.copy(fixture("v30_intro.mp4"), "/tmp/v31_small.mp4")
    call(S, f"{P}/resources?kind=videos&filename=small.mp4", raw=open("/tmp/v31_small.mp4", "rb").read(), method="POST")
    free = call(S, f"{P}/resources?path=refs/videos/small.mp4", method="DELETE")
    check("an unused file: deleted at once", free.get("deleted") and not os.path.exists(f"{VID}/small.mp4"), free)
    check("a path outside the resources is refused", "error" in call(S, f"{P}/resources?path=plan.json", method="DELETE"))

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1500, "height": 950}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await page.click("text=Resources…"); await page.wait_for_timeout(700)
            dlg = page.locator(".tk-modal").last
            check("resources: total size shown", "file(s)" in await dlg.inner_text())
            check("resources: a 🗑 button on each file", await dlg.locator(".studio-res-del").count() == 4)
            visible = await page.evaluate("""() => [...document.querySelectorAll('.studio-res')].map((res) => {
                const b = res.querySelector('.studio-res-del').getBoundingClientRect(), box = res.getBoundingClientRect();
                return b.width > 10 && b.left >= box.left - 1 && b.right <= box.right + 1; })""")
            check("every 🗑 is inside its box, even with a long name", visible and all(visible), visible)
            await dlg.screenshot(path="v32_resources.png")
            # the start video picture is used: a click says so, nothing deleted
            await dlg.locator(".studio-res", has_text="fillette").locator(".studio-res-del").click(); await page.wait_for_timeout(500)
            alert = page.locator(".h3-dlg").last
            check("🗑 on a used picture: the message says where it is used", "Branch 1" in await alert.inner_text())
            await page.keyboard.press("Enter"); await page.wait_for_timeout(300)
            # a slow import: progress window, then cancel
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Network.enable")
            await cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": 2 * 1024 * 1024})
            async with page.expect_file_chooser() as fc:
                await dlg.locator("button", has_text="Import").last.click()
            chooser = await fc.value
            await chooser.set_files(big)
            await page.wait_for_timeout(2500)
            prog = page.locator(".studio-progress")
            text = await prog.inner_text() if await prog.count() else ""
            check("a big import shows a progress window (file, %, MB)", await prog.count() == 1 and "v31_big.mp4" in text and "%" in text and "MB" in text, text)
            width = await page.evaluate("parseFloat(document.querySelector('.studio-progress-bar').style.width) || 0")
            check("the bar moves", 0 < width < 100, width)
            await prog.locator("button", has_text="Cancel").click(); await page.wait_for_timeout(2000)
            check("cancel: the window closes", await page.locator(".studio-progress").count() == 0)
            await cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
            await page.wait_for_timeout(1500)
            check("cancel: nothing imported, no piece left", sorted(os.listdir(VID)) == [] or not [f for f in os.listdir(VID) if f.startswith("v31_big") or f.endswith(".part")],
                  os.listdir(VID))
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
