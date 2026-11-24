"""Screenshots of the README (docs/screenshots/*.png), made with the fake ComfyUI of the tests and the robot example
of the plugin: the takes are fake videos of the robot on the beach or in the workshop (render_videos.py).

    H3_PLUGIN=/path/to/ComfyUI-H3-ClipPlan CHROME=/path/to/chrome python tests/screenshots/make_screenshots.py
"""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "e2e"))
from common import ENCORE, CHROME, PLUGIN, restart_mock  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

DOCS = os.path.join(ENCORE, "docs", "screenshots")
S = "http://127.0.0.1:8240"; M = "http://127.0.0.1:8771"
M3D = "minimax_h3_latent_upscaler_3d_fp16.safetensors"


def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}


def run_one():
    time.sleep(1.2)
    try: call(M, "/test/run", {})
    except Exception: pass
    time.sleep(2.2)


P = "/api/projects/robot_beach"
SRV = None


def take_of(job):
    for _ in range(40):
        j = next((x for x in call(S, P + "/jobs")["jobs"] if x["id"] == job.get("id")), {})
        if j.get("take"):
            return j["take"]
        run_one()
    sys.exit(f"no take: {job}")


def gen(index, branch, after=None):
    body = {"clip": index, "branch": branch}
    if after:
        body["after"] = after
    job = call(S, P + "/generate", body); run_one()
    return take_of(job)


def setup():
    subprocess.run([sys.executable, os.path.join(HERE, "render_videos.py")], check=True)
    os.environ["MOCK_VIDEOS"] = os.path.join(HERE, "out", "videos")
    os.makedirs(os.path.join(HERE, "..", "e2e", "out"), exist_ok=True)
    restart_mock()
    root = os.path.join(HERE, "out", "encore"); shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
    cfg = os.path.join(root, "config.json")
    json.dump({"projects_root": os.path.join(root, "projects"), "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
    global SRV
    SRV = srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8240", "--no-browser", "--config", cfg], cwd=ENCORE,
                           stdout=subprocess.DEVNULL, stderr=open(os.path.join(HERE, "out", "server.log"), "w"))
    time.sleep(1.5)
    ex = os.path.join(PLUGIN, "examples")
    call(S, "/api/projects", {"name": "robot_beach", "mode": "music_video"})
    call(S, P + "/import-plan?filename=robot_beach.plan.json", raw=open(os.path.join(ex, "robot_beach.plan.json"), "rb").read(), method="POST")
    for kind, name in (("images", "robot.png"), ("images", "beach.png"), ("images", "workshop.png"), ("songs", "robot_beach_song.mp3")):
        call(S, f"{P}/resources?kind={kind}&filename={name}", raw=open(os.path.join(ex, name), "rb").read(), method="POST")
    call(S, P + "/essence", {"song": "refs/songs/robot_beach_song.mp3"}, "PUT")       # the song is the project's
    for _ in range(2):
        call(S, P + "/branches", {"how": "empty"})
    b1, b2, b3 = [b["id"] for b in call(S, P)["branches"]][:3]
    call(S, f"{P}/branches/{b1}", {"name": "Sunset", "refs": {"robot": {"image": "refs/images/robot.png"}, "beach": {"image": "refs/images/beach.png"}},
                                   "upscale": {"enabled": True, "model": M3D, "start_mp": 0.25, "upscaler": "lbh3d"}}, "PUT")
    call(S, f"{P}/branches/{b2}", {"name": "Workshop version", "refs": {"robot": {"image": "refs/images/robot.png"}, "beach": {"image": "refs/images/workshop.png"}}}, "PUT")
    call(S, f"{P}/branches/{b3}", {"name": "First draft", "refs": {"robot": {"image": "refs/images/robot.png"}, "beach": {"image": "refs/images/beach.png"}}}, "PUT")
    # Sunset: two takes of clip 1, two continuations of the second, two takes of clip 3 (a new scene)
    a1 = gen(1, b1); a2 = gen(1, b1)
    gen(2, b1, a1); c1 = gen(2, b1, a2); gen(2, b1, a2)
    gen(3, b1, c1); d2 = gen(3, b1, c1)
    w1 = gen(1, b2); w2 = gen(2, b2, w1); gen(1, b2)
    gen(1, b3)
    call(S, P + "/selection", {"selection": {"branch": b1, "1": a2, "2": c1, "3": d2}}, "PUT")
    job = call(S, P + "/assemble", {"clip": 3, "take": d2}); run_one(); run_one()
    # something waiting in the queue
    call(S, "/api/queue/pause", {})
    call(S, P + "/generate", {"clip": 3, "after": w2, "branch": b2})
    return srv, (b1, b2, b3), c1, d2


async def shots(branches, c1, d2):
    b1, b2, b3 = branches
    os.makedirs(DOCS, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1680, "height": 1000})
        await page.goto(S + "/")
        await page.evaluate(f"localStorage.setItem('h3studio.project','robot_beach'); localStorage.setItem('encore.folded.robot_beach', JSON.stringify(['{b3}']))")
        await page.reload(); await page.wait_for_timeout(2500)
        # the takes screen (the main screen), the twig 1 → 2 → 3 of Sunset chosen
        await page.locator(f".tk-card[data-take='{d2}']").first.click(); await page.wait_for_timeout(1500)
        # the takes screen (the main screen)
        close = page.locator(".tk-map-btn:has-text('✕')")
        if await close.count(): await close.first.click(); await page.wait_for_timeout(300)
        await page.mouse.move(5, 5); await page.wait_for_timeout(1500)
        await page.set_viewport_size({"width": 1680, "height": 1260}); await page.wait_for_timeout(1500)
        await page.screenshot(path=os.path.join(DOCS, "takes.png"))
        await page.set_viewport_size({"width": 1680, "height": 1000}); await page.wait_for_timeout(800)
        # the launch panel: the next clip after a take
        card = page.locator(f".tk-card[data-take='{c1}']").first
        await card.hover(); await card.locator(".tk-retake").click(); await page.wait_for_timeout(2000)
        await page.mouse.move(5, 300); await page.wait_for_timeout(500)
        await page.screenshot(path=os.path.join(DOCS, "launch.png"))
        await page.evaluate("H3Launch.close()"); await page.wait_for_timeout(500)
        # plan window of a take
        card = page.locator(f".tk-card[data-take='{d2}']").first; await card.hover()
        await card.locator(".tk-plan-btn").click(); await page.wait_for_timeout(900)
        await page.locator(".tk-plan-modal .tk-plan-gen").scroll_into_view_if_needed(); await page.wait_for_timeout(300)
        await page.locator(".tk-plan-modal > *").first.screenshot(path=os.path.join(DOCS, "plan_window.png"))
        await page.click(".tk-plan-modal >> text=Close"); await page.wait_for_timeout(300)
        # the plan of the selection: generated clips locked, then what follows
        await page.click(".tk-twigplan"); await page.wait_for_timeout(1500)
        await page.locator(".clipitem").nth(1).click(); await page.wait_for_timeout(800)
        await page.screenshot(path=os.path.join(DOCS, "plan_editor.png"))
        await page.click("#studioBackBtn"); await page.wait_for_timeout(800)
        # queue
        await page.click("#studioQueueBtn"); await page.wait_for_timeout(800)
        await page.locator(".tk-modal").last.locator("> *").first.screenshot(path=os.path.join(DOCS, "queue.png"))
        await b.close()


def main():
    if not PLUGIN: sys.exit("set H3_PLUGIN to the ComfyUI-H3-ClipPlan folder")
    try:
        srv, branches, c1, d2 = setup()
        asyncio.run(shots(branches, c1, d2))
    finally:
        call(S, "/api/queue/resume", {})
        if SRV: SRV.terminate()
        subprocess.run(["pkill", "-f", "mock_studio.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("screenshots in", DOCS)


if __name__ == "__main__":
    main()
