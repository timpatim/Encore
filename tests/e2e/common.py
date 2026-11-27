"""Shared settings of the end-to-end tests (Encore's server + the fake ComfyUI + a headless Chrome)."""
import os
import socket
import subprocess
import sys
import time

E2E = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(E2E)
ENCORE = os.path.dirname(TESTS)                      # the Encore folder (python -m encore runs from here)
FIX = os.path.join(TESTS, "fixtures")
MOCK = os.path.join(TESTS, "mock")
CHROME = os.environ.get("CHROME") or None             # None: the Chromium installed by « playwright install »
MOCK_PORT = 8771


def fixture(name):
    return os.path.join(FIX, name)


def _port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def restart_mock():
    """A fresh fake ComfyUI (empty queue, history and folders) on MOCK_PORT."""
    subprocess.run(["pkill", "-f", "mock_studio.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if not _port_open(MOCK_PORT):
            break
        time.sleep(0.1)
    env = dict(os.environ, MOCK_PORT=str(MOCK_PORT))
    log = open(os.path.join(E2E, "out", "mock.log"), "a")
    subprocess.Popen([sys.executable, os.path.join(MOCK, "mock_studio.py")], cwd=MOCK, env=env, stdout=log, stderr=log,
                     start_new_session=True)
    for _ in range(100):
        if _port_open(MOCK_PORT):
            return
        time.sleep(0.1)
    raise RuntimeError("the fake ComfyUI did not start: see tests/e2e/out/mock.log")


# ---- chantier A (0.42): the Takes screen is the main screen; the plan editor is the plan screen
async def plan_screen(page, master=False, wait=900):
    """Opens the plan screen: the plan of the selection (or the master plan of the selected branch)."""
    if await page.is_visible("#studioBackBtn"):
        return
    await page.wait_for_selector(".tk-twigplan, .tk-master", timeout=15000)
    await page.click(".tk-master" if master else ".tk-twigplan")
    await page.wait_for_timeout(wait)


async def takes_screen(page, wait=900):
    """Back to the Takes screen (the plan screen saves what changed)."""
    if await page.is_visible("#studioBackBtn"):
        await page.click("#studioBackBtn")
        await page.wait_for_timeout(wait)


async def launch_go(page, wait=900):
    """The launch panel opened by a click on a take, a « + » box or « nouvelle prise »: generate."""
    await page.wait_for_selector("#launchPanel .launch-foot button.primary:not([disabled])", timeout=15000)
    await page.wait_for_timeout(400)
    await page.click("#launchPanel .launch-foot button.primary")
    await page.wait_for_timeout(wait)
