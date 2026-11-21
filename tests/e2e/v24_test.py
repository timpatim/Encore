import json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8237"; M = "http://127.0.0.1:8771"
def call(base, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "body": e.read().decode()[:300]}
root = "/tmp/h3s_v24"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8237", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v24_srv.log", "w"))
time.sleep(1.5)
P = "/api/projects/rue"
def upload(path, raw):
    req = urllib.request.Request(S + path, data=raw, method="POST", headers={"X-Encore": "1"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
call(S, "/api/projects", {"name": "rue", "mode": "free"})
upload(P + "/import-plan?filename=rue.json", open(fixture("rue_test_v1.plan.json"), "rb").read())
for f in (fixture("fillette.png"), fixture("rue.png")):
    upload(f"{P}/resources?kind=images&filename={os.path.basename(f)}", open(f, "rb").read())
call(S, P + "/branches", {}); call(S, P + "/branches/b1", {"refs": {"fillette": {"image": "refs/images/fillette.png"}, "rue": {"image": "refs/images/rue.png"}}}, "PUT")
def takes():
    return {c["index"]: [t["record"] | {"id": t["id"]} for t in c["takes"]] for c in call(S, P + "/takes")["clips"]}
def wait_done(n=1):
    for _ in range(n):
        time.sleep(1.5); call(M, "/test/run", {}); time.sleep(2.5)
try:
    print("gen1", call(S, P + "/generate", {"clip": 1, "branch": "b1", "random": True})); time.sleep(1.5); wait_done()
    t1 = takes()[1][-1]
    print("clip1 take", t1["id"], "plan_clip recorded:", bool(t1["studio"].get("plan_clip")), "raw_start", t1["studio"].get("raw_start"))
    print("gen2", call(S, P + "/generate", {"clip": 2, "branch": "b1", "parent": t1["id"].split("_")[1], "random": True}).get("status")); wait_done()
    t2 = takes()[2][-1]
    print("clip2 take", t2["id"], "parent", t2["parent"])
    # an old take: no plan_clip → found again by fingerprint
    meta = f"{root}/projets/rue/takes/clip_002/{t2['id']}.json"
    rec = json.load(open(meta)); rec["studio"].pop("plan_clip"); rec["studio"].pop("raw_start"); json.dump(rec, open(meta, "w"))
    tp = call(S, f"{P}/takes/2/{t2['id']}/plan")
    print("take plan (old):", tp["source"], tp["snapshot"]["name"] if tp["snapshot"] else None, "raw_start", tp["raw_start"], tp["now_raw_start"])
    # change the plan: clip 1 shorter and its prompt edited → both takes invalid
    plan = json.load(open(f"{root}/projets/rue/plan.json"))
    old_prompt = plan["clips"][0]["prompt"]
    plan["clips"][0]["frames"] = 192
    plan["clips"][0]["prompt"] = old_prompt.replace("summary:", "summary:\n[reference generation] A NEW SENTENCE.", 1)
    print("save", (call(S, P + "/plan", plan, "PUT").get("validation") or {}).get("errors"))
    tp = call(S, f"{P}/takes/1/{t1['id']}/plan")
    print("take plan (new):", tp["source"], "frames then/now", tp["snapshot"]["frames"], tp["current"]["frames"], "refs", list(tp["refs"]))
    tp2 = call(S, f"{P}/takes/2/{t2['id']}/plan")
    print("take plan clip 2 after change:", tp2["source"], tp2["raw_start"], tp2["now_raw_start"])
    print("normal assemble:", call(S, P + "/assemble", {"clip": 2, "take": t2["id"]}))
    chk = call(S, P + "/assemble-check", {"clip": 2, "take": t2["id"]})
    print("check:", json.dumps(chk, ensure_ascii=False))
    job = call(S, P + "/assemble", {"clip": 2, "take": t2["id"], "allow_invalid": True})
    print("job:", job.get("status"), job.get("with_invalid"), job.get("frames"))
    wait_done()
    jobs = [j for j in call(S, P + "/jobs")["jobs"] if j["kind"] == "assemble"]
    print("assembly:", [(j["status"], j.get("error"), j.get("export")) for j in jobs])
    ex = jobs[-1].get("export")
    md = open(f"{root}/projets/rue/exports/{ex}.infos.md", encoding="utf-8").read()
    i = md.find("## Prises invalidées"); print(md[i:i + 700])
    info = json.load(open(f"{root}/projets/rue/exports/{ex}.infos.json"))
    print("infos json invalid:", info["invalidated_takes"], "| plan frames", [c["frames"] for c in info["plan"]["clips"]], "| video frames", info["video"]["frames"])
    # size differs → refused
    rec = json.load(open(f"{root}/projets/rue/takes/clip_001/{t1['id']}.json")); rec["width"] = 512; json.dump(rec, open(f"{root}/projets/rue/takes/clip_001/{t1['id']}.json", "w"))
    print("size check:", call(S, P + "/assemble-check", {"clip": 2, "take": t2["id"]}).get("error"))
    print("size assemble:", call(S, P + "/assemble", {"clip": 2, "take": t2["id"], "allow_invalid": True}))
finally:
    srv.terminate()
