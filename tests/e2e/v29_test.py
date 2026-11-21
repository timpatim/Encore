"""v0.29: folded branches — same width, no « selection » label, a folded branch never holds the selection
(it moves to an unfolded branch), at least one branch stays unfolded."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8239"; M = "http://127.0.0.1:8771"
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
root = "/tmp/h3s_v29"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8239", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("v29_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
call(S, "/api/projects", {"name": "rue", "mode": "free"})
call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
for f in (fixture("fillette.png"), fixture("rue.png")):
    call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
refs = {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}
ids = []
for k in range(3):
    br = call(S, P + "/branches", {})
    bid = (br.get("branch") or br).get("id") if isinstance(br, dict) else None
    bid = bid or [b["id"] for b in call(S, P)["branches"]][-1]
    ids.append(bid)
    call(S, f"{P}/branches/{bid}", {"refs": refs, **({"name": "A much longer branch name"} if k == 1 else {})}, "PUT")
    call(S, P + "/generate", {"clip": 1, "branch": bid, "random": True}); time.sleep(1.5); run_mock(); time.sleep(2.5)
takes = {t["record"]["studio"].get("branch"): t["id"] for c in call(S, P + "/takes")["clips"] if c["index"] == 1 for t in c["takes"]}
try:
    check("three branches with a take each", len(set(ids)) == 3 and all(b in takes for b in ids), (ids, list(takes)))

    async def main():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await b.new_page(viewport={"width": 1600, "height": 950}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
            await page.click("#viewTabs >> text=Takes"); await page.wait_for_timeout(1500)
            # select the take of the middle branch, then fold that branch
            card = page.locator(f".tk-card[data-take='{takes[ids[1]]}']"); await card.click(); await page.wait_for_timeout(800)
            check("selection in the middle branch", await page.evaluate("H3Takes.activeBranch()") == ids[1])
            folds = page.locator(".tk-band-head .tk-fold")
            await folds.nth(1).click(); await page.wait_for_timeout(1200)
            active = await page.evaluate("H3Takes.activeBranch()")
            check("folding the selected branch moves the selection to an unfolded branch", active in (ids[0], ids[2]), active)
            check("folded header shows no « selection »", "selection" not in await page.locator(".tk-band-head.folded").first.inner_text())
            saved = call(S, P + "/takes").get("selection_branch")
            check("the moved selection is saved", saved == active, (saved, active))
            # fold a second one: the last unfolded branch cannot be folded
            await page.locator(".tk-band-head:not(.folded) .tk-fold").first.click(); await page.wait_for_timeout(1200)
            heads = page.locator(".tk-band-head.folded")
            check("two branches folded", await heads.count() == 2)
            last = page.locator(".tk-band-head:not(.folded) .tk-fold")
            check("the last unfolded branch cannot be folded", await last.count() == 1 and await last.is_disabled())
            check("selection is in the only unfolded branch", await page.evaluate("H3Takes.activeBranch()") not in [None] and
                  await page.locator(".tk-band-head:not(.folded).active").count() == 1)
            await last.evaluate("e => e.click()"); await page.wait_for_timeout(500)
            check("clicking it anyway changes nothing", await page.locator(".tk-band-head.folded").count() == 2)
            # same width, ▶▶ lined up
            boxes = [await heads.nth(k).bounding_box() for k in range(2)]
            fills = [await heads.nth(k).locator(".tk-fill").bounding_box() for k in range(2)]
            check("folded headers have the same width", abs(boxes[0]["width"] - boxes[1]["width"]) < 1, boxes)
            check("▶▶ lined up on the right", abs((fills[0]["x"] + fills[0]["width"]) - (fills[1]["x"] + fills[1]["width"])) < 1, fills)
            await page.screenshot(path="v29_folded.png")
            # all folded in the browser's memory (e.g. from an older visit): one is unfolded again
            await page.evaluate(f"localStorage.setItem('encore.folded.rue', JSON.stringify({json.dumps(ids)}))")
            await page.reload(); await page.wait_for_timeout(1500)
            await page.click("#viewTabs >> text=Takes"); await page.wait_for_timeout(1500)
            check("never every branch folded", await page.locator(".tk-band-head:not(.folded)").count() == 1)
            act = await page.evaluate("H3Takes.activeBranch()")
            folded_ids = json.loads(await page.evaluate("localStorage.getItem('encore.folded.rue')"))
            check("the selected branch is the unfolded one", act not in folded_ids, (act, folded_ids))
            check("no page error", not errs, errs)
            await b.close()
    asyncio.run(main())
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
