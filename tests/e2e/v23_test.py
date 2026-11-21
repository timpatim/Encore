import json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8236"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
root = "/tmp/h3s_v23"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
shutil.copytree("/tmp/h3s_v20/projets", root + "/projets")
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8236", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v23_srv.log", "w"))
time.sleep(1.5)
try:
    call(M, "/test/foreign", {"run": True}); call(M, "/test/foreign", {})
    P = "/api/projects/robot"
    call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True})
    call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True})
    time.sleep(2.5)
    q = call(S, "/api/queue")
    print("foreign", q["comfy_foreign"], "| sent", [(j["status"], j.get("comfy_ahead"), j.get("at_least"), j.get("start_in")) for j in q["sent"]],
          "| waiting", [(j.get("start_in"), j.get("at_least")) for g in q["groups"] for j in g["jobs"]])
    call(M, "/test/run", {}); time.sleep(2.5)
    q = call(S, "/api/queue"); print("after one foreign done:", q["comfy_foreign"], [(j.get("comfy_ahead")) for j in q["sent"]])
    call(M, "/test/run", {}); time.sleep(2.5)
    q = call(S, "/api/queue"); print("after both:", q["comfy_foreign"], [(j.get("comfy_ahead"), j["status"]) for j in q["sent"]])
    # ours runs, a foreign one waits behind it: « pause now » must only interrupt ours
    call(M, "/test/start", {}); call(M, "/test/foreign", {}); time.sleep(2.5)
    call(S, "/api/queue/pause", {"mode": "now"}); time.sleep(2.5)
    print("interrupts", call(M, "/test/interrupts", {}), "| comfy queue", [r[1][:8] for r in call(M, "/queue")["queue_pending"]])
finally:
    srv.terminate()
