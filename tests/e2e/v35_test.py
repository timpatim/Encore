"""v0.35: the side pane of the Takes tab with more assembled videos than its height: the thumbnails keep their size
(they were squeezed into thin strips) and the list scrolls, with the wheel too."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8244"; M = "http://127.0.0.1:8771"
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

root = "/tmp/h3s_v35"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8244", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v35_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    call(S, P + "/branches", {})
    branch = call(S, P)["branches"][0]
    exports = f"{root}/projets/rue/exports"; os.makedirs(exports, exist_ok=True)
    COUNT = 14
    for i in range(COUNT):
        name = f"rue_video_{i:02d}"
        json.dump({"name": name, "created": 1795000000 + i, "branch": branch["id"], "branch_name": branch["name"], "clips": 1,
                   "takes": {}, "size": [960, 544], "report": "test"}, open(f"{exports}/{name}.json", "w"))
        shutil.copy(fixture("v30_intro.mp4"), f"{exports}/{name}.mp4")

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1500, "height": 800}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await page.click("#viewTabs >> text=Takes"); await page.wait_for_timeout(1500)
            items = page.locator(".tk-pane-list .tk-pane-item")
            check("side pane: every assembled video listed", await items.count() == COUNT, await items.count())
            heights = await page.evaluate("[...document.querySelectorAll('.tk-pane-list .tk-pane-item')].map((e) => Math.round(e.getBoundingClientRect().height))")
            check("the thumbnails keep their size (not squeezed)", heights and min(heights) == max(heights) and min(heights) > 60, heights)
            sizes = await page.evaluate("(() => { const l = document.querySelector('.tk-pane-list'); return [l.clientHeight, l.scrollHeight]; })()")
            check("the list is taller than the pane: it scrolls", sizes[1] > sizes[0] + 100, sizes)
            last = items.nth(COUNT - 1)
            box = await page.locator(".tk-pane-list").bounding_box()
            check("the last video is out of sight at first", (await last.bounding_box())["y"] > box["y"] + box["height"])
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            for _ in range(20):
                await page.mouse.wheel(0, 400); await page.wait_for_timeout(50)
            await page.wait_for_timeout(400)
            lb = await last.bounding_box()
            check("…and comes into sight with the wheel", lb["y"] + lb["height"] <= box["y"] + box["height"] + 2 and lb["y"] >= box["y"] - 2, (lb, box))
            await page.screenshot(path="v35_pane.png")
            # 0.39: the last branch can be scrolled up to the top of the view, and no further
            await page.evaluate("document.querySelector('#takesView .tk-viewport').scrollTop = 1e9"); await page.wait_for_timeout(300)
            gap = await page.evaluate("""(() => { const vp = document.querySelector('#takesView .tk-viewport');
                const heads = [...document.querySelectorAll('#takesView .tk-band-head')]; const last = heads[heads.length - 1];
                return last.getBoundingClientRect().top - vp.getBoundingClientRect().top; })()""")
            check("Takes tab: scrolled to the bottom, the last branch is at the top of the view", 0 <= gap < 60, gap)
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
