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
PLUGIN = os.environ.get("H3_PLUGIN", "")
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
    env = dict(os.environ, PYTHONPATH=os.path.join(MOCK, "shim"), MOCK_PORT=str(MOCK_PORT), H3_PLUGIN=PLUGIN)
    log = open(os.path.join(E2E, "out", "mock.log"), "a")
    subprocess.Popen([sys.executable, os.path.join(MOCK, "mock_studio.py")], cwd=MOCK, env=env, stdout=log, stderr=log,
                     start_new_session=True)
    for _ in range(100):
        if _port_open(MOCK_PORT):
            return
        time.sleep(0.1)
    raise RuntimeError("the fake ComfyUI did not start: see tests/e2e/out/mock.log")
