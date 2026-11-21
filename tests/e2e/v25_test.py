"""v0.25: the fixes of the audit (lot A)."""
import asyncio, glob, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
sys.path.insert(0, ENCORE)
S = "http://127.0.0.1:8237"; M = "http://127.0.0.1:8771"
OK = []
def check(name, cond, info=""):
    OK.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, info if not cond else "")
def raw_req(path, body=None, method=None, headers=None, base=S):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")
def call(path, body=None, method=None, base=S):
    return raw_req(path, body, method, {"Content-Type": "application/json", "X-Encore": "1"}, base)[1]
def run_mock():
    try: raw_req("/test/run", {}, base=M)
    except Exception: pass                     # nothing in the mock's queue
root = "/tmp/h3s_v25"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
restart_mock()
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8237", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open("/tmp/v25_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
def upload(path, data):
    req = urllib.request.Request(S + path, data=data, method="POST", headers={"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
def jobs():
    return call(P + "/jobs")["jobs"]
def takes():
    return {c["index"]: [t["record"] | {"id": t["id"]} for t in c["takes"]] for c in call(P + "/takes")["clips"]}
try:
    # ---- 5. requests from another page are refused
    code, _ = raw_req("/api/projects", {"name": "x"}, headers={"Content-Type": "text/plain"})
    check("POST without X-Encore refused", code == 403, code)
    code, _ = raw_req("/api/projects", {"name": "x"}, headers={"X-Encore": "1", "Origin": "http://evil.example"})
    check("POST from another origin refused", code == 403, code)
    code, _ = raw_req("/api/config", headers={"Host": "evil.example:8237"})
    check("GET with a foreign Host refused (DNS rebinding)", code == 403, code)
    code, _ = raw_req("/api/config", headers={"Host": "localhost:8237"})
    check("GET with Host localhost accepted", code == 200, code)
    code, _ = raw_req("/api/projects", {"name": "rue", "mode": "free"}, headers={"X-Encore": "1", "Origin": S})
    check("POST from Encore's own page accepted", code == 200, code)

    upload(P + "/import-plan?filename=rue.json", open(fixture("rue_test_v1.plan.json"), "rb").read())
    for f in (fixture("fillette.png"), fixture("rue.png")):
        upload(f"{P}/resources?kind=images&filename={os.path.basename(f)}", open(f, "rb").read())
    call(P + "/branches", {}); print("branch", call(P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT"))

    # ---- 1. ComfyUI unreachable at dispatch (English messages): the job waits, it does not fail
    call("/api/queue/pause", {})
    job = call(P + "/generate", {"clip": 1, "branch": "b1", "random": True}); print("gen", job)
    call("/api/config", {"comfy_url": "http://127.0.0.1:8799"}, "PUT")
    call("/api/queue/resume", {})
    time.sleep(4)
    j = next(x for x in jobs() if x["id"] == job["id"])
    check("unreachable ComfyUI: job still queued (EN)", j["status"] == "queued" and not j.get("error"), (j["status"], j.get("error")))
    call("/api/config", {"comfy_url": M}, "PUT")
    time.sleep(3); run_mock(); time.sleep(3)
    t1 = takes()[1][-1]
    check("after ComfyUI is back: take made", t1["id"].startswith("s"), t1["id"])

    # ---- 8. ComfyUI restarted while a job waits in it: requeued and made
    job = call(P + "/generate", {"clip": 2, "branch": "b1", "parent": t1["id"].split("_")[1], "random": True})
    time.sleep(2.5)
    j = next(x for x in jobs() if x["id"] == job["id"])
    check("job sent to ComfyUI", j.get("dispatched"), j)
    subprocess.run(["pkill", "-f", "mock_studio.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # ComfyUI stops
    time.sleep(3)
    restart_mock()                                   # a new ComfyUI: empty queue and history
    for _ in range(20):
        time.sleep(1.5)
        j = next(x for x in jobs() if x["id"] == job["id"])
        if j["status"] == "error" or (j.get("dispatched") and j.get("lost")):
            break
    check("lost job requeued and sent again", j["status"] != "error" and j.get("dispatched"), (j["status"], j.get("error")))
    run_mock(); time.sleep(3)
    j2 = next((x for x in jobs() if x["id"] == job["id"]), {"status": "done"})
    check("requeued job finished", j2["status"] == "done", (j2["status"], j2.get("error")))

    # ---- 7. the mirror follows the ComfyUI address
    from encore import server as srvmod
    from pathlib import Path
    st = srvmod.Studio(Path(cfg))
    eng = st.engine
    eng._mirror("rue", "b1").add((1, "x"))
    st.config["comfy_url"] = "http://127.0.0.1:9999"
    check("mirror forgotten when the ComfyUI address changes", eng._mirror("rue", "b1") == set())

    # ---- 4. fill busy: a code, not a French text
    t2 = takes()[2][-1]
    call(P + "/generate", {"clip": 1, "branch": "b1", "random": True})
    code, data = raw_req(P + "/branches/b1/fill", {"dry_run": True}, headers={"Content-Type": "application/json", "X-Encore": "1"})
    check("fill while generating: error code busy", data.get("code") == "busy", data)
    for _ in range(2):
        time.sleep(2); run_mock()
    time.sleep(3)

    # ---- 3. invalidated takes assembled after a reference was renamed
    plan = json.load(open(f"{root}/projets/rue/plan.json"))
    text = json.dumps(plan).replace("fillette", "girl")
    plan = json.loads(text); plan["clips"][0]["frames"] = 192
    call(P + "/plan", plan, "PUT")
    chk = call(P + "/assemble-check", {"clip": 2, "take": t2["id"]})
    check("check after a renamed reference: no error", not chk.get("error"), chk.get("error"))
    job = call(P + "/assemble", {"clip": 2, "take": t2["id"], "allow_invalid": True})
    time.sleep(2); run_mock(); time.sleep(4)
    a = [x for x in jobs() if x["kind"] == "assemble"]
    check("assembly with a renamed reference done", a and a[-1]["status"] == "done", [(x["status"], x.get("error")) for x in a])
    ex = a[-1].get("export") if a else None
    if ex:
        info = json.load(open(f"{root}/projets/rue/exports/{ex}.infos.json"))
        md = open(f"{root}/projets/rue/exports/{ex}.infos.md", encoding="utf-8").read()
        check("infos json: 'branch' key, clips is a number", "branch" in info and isinstance(info["video"]["clips"], int), (list(info), info["video"]["clips"]))
        check("infos md in English with '.' decimals", "## Invalidated takes" in md and ",7 s" not in md and ",0 s" not in md)
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
