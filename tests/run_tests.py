"""Runs Encore's tests.

    python tests/run_tests.py                       unit tests only (node and Python)
    H3_PLUGIN=/path/to/ComfyUI-H3-ClipPlan python tests/run_tests.py --e2e      + end-to-end tests
    python tests/run_tests.py --e2e v25_test        only the end-to-end tests whose name contains « v25_test »

Needs: Python 3.10+, node (unit tests); for --e2e also Pillow, numpy, playwright with its Chromium
(« pip install pillow numpy playwright » then « playwright install chromium », or CHROME=/path/to/chrome) and the
plugin folder (H3_PLUGIN). The end-to-end tests run on Linux (or WSL): they start Encore's server, a fake ComfyUI
that runs the real plugin code (tests/mock) and a headless browser. Screenshots and logs go to tests/e2e/out.
"""
import os
import re
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, ROOT)

UNIT = [
    ["node", "unit/sections_test.js"],
    ["node", "unit/sha_test.js"],
    ["node", "unit/roundtrip_test.js", "fixtures/rue_test_v1.plan.json", "fixtures/robot_beach.plan.json", "fixtures/robot_workshop.plan.json"],
    [sys.executable, "unit/parity_test.py"],
    [sys.executable, "unit/cuts_test.py"],
]
# order matters: v21*, v22 and v23 reuse the projects made by v20 and v20b; *_ui_test reuse the one of the test before
E2E = ["v20_test", "v20b_test", "v21_test", "v21b_test", "v22_test", "v23_test", "leaf_test", "infos_test", "upscale_test",
       "queue_ui_test", "a1_api_test", "a1_ui_test", "a2_api_test", "a2_ui_test", "a3_api_test", "a3_ui_test", "v25_test", "v25_ui_test", "v28_test", "v29_test", "v30_test", "v31_test", "v34_test", "v35_test", "v36_test", "v37_test", "v38_test", "v40_test"]
BAD = re.compile(r"^FAIL|Traceback \(most recent call last\)|ERRORS: \[[^\]]|^errors \[[^\]]|^\s*\d+/\d+ passed", re.M)


def failed(output, code):
    if code != 0:
        return True
    for m in BAD.finditer(output):
        text = m.group(0)
        if "passed" in text:
            done, total = map(int, re.findall(r"\d+", text)[:2])
            if done != total:
                return True
        else:
            return True
    return False


def run(cmd, cwd, timeout):
    started = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        out, code = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), -1
        out += f"\nTIMEOUT after {timeout} s"
    return out, code, time.time() - started


def versions():
    from encore import projects
    line = f"Encore {projects.STUDIO_VERSION}"
    plugin = os.environ.get("H3_PLUGIN")
    if plugin:
        try:
            m = re.search(r'APP_VERSION = "([^"]+)"', open(os.path.join(plugin, "nodes.py"), encoding="utf-8").read())
            line += f" · plugin ComfyUI-H3-ClipPlan {m.group(1) if m else '?'} ({plugin})"
        except OSError:
            line += f" · plugin not found in {plugin}"
    return line


def main(argv):
    e2e = "--e2e" in argv
    only = [a for a in argv if not a.startswith("--")]
    print(versions())
    results = []
    if not only:
        print("\n== unit tests")
        for cmd in UNIT:
            out, code, secs = run(cmd, TESTS, 120)
            ok = not failed(out, code)
            results.append((cmd[1], ok))
            print(f"{'PASS' if ok else 'FAIL'} {cmd[1]} ({secs:.0f} s)")
            if not ok:
                print("   " + out.strip().replace("\n", "\n   ")[-3000:])
    if e2e:
        if not os.environ.get("H3_PLUGIN"):
            sys.exit("--e2e needs H3_PLUGIN=/path/to/ComfyUI-H3-ClipPlan")
        print("\n== end-to-end tests")
        sys.path.insert(0, os.path.join(TESTS, "e2e"))
        os.makedirs(os.path.join(TESTS, "e2e", "out"), exist_ok=True)
        from common import restart_mock
        for name in E2E:
            if only and not any(o in name for o in only):
                continue
            restart_mock()
            out, code, secs = run([sys.executable, os.path.join(TESTS, "e2e", name + ".py")], os.path.join(TESTS, "e2e", "out"), 600)
            with open(os.path.join(TESTS, "e2e", "out", name + ".log"), "w", encoding="utf-8") as log:
                log.write(out)
            ok = not failed(out, code)
            results.append((name, ok))
            print(f"{'PASS' if ok else 'FAIL'} {name} ({secs:.0f} s)")
            if not ok:
                print("   " + out.strip().replace("\n", "\n   ")[-3000:])
        subprocess.run(["pkill", "-f", "mock_studio.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed" + (f" — failed: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
