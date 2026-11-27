"""0.49 (API): a duplicate takes over portions of a twig, each from the start of a scene; the clips left free are
made in the new branch (lengths locked), the portions after them follow its own takes."""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8252"; M = "http://127.0.0.1:8771"
FAILS = []


def call(base, path, body=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", "X-Encore": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read() or b"{}")}


def check(label, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(label)


restart_mock()
root = "/tmp/h3s_f1api"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
os.makedirs(os.path.join(ENCORE, "tests", "e2e", "out"), exist_ok=True)
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8252", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "f1_srv.log"), "w"))
time.sleep(1.5)
P = "/api/projects/rue"


def run():
    for _ in range(80):
        time.sleep(0.3)
        call(M, "/test/run", {})
        jobs = call(S, P + "/jobs")["jobs"]
        if not any(j["status"] in ("queued", "running", "harvest") for j in jobs):
            break
    time.sleep(0.3)


try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    master = call(S, P + "/plan?branch=b1")["plan"]
    master["clips"][2]["continue"] = False            # 1 → 2 | 3 → 4 | 5
    call(S, P + "/plan", {"branch": "b1", "leaf": None, "plan": master}, "PUT")
    call(S, P + "/branches/b1/fill", {"dry_run": False, "assemble": False}); run()
    line = {int(c["index"]): t["id"] for c in call(S, P + "/takes")["clips"] for t in c["takes"]}
    check("the master line of branch 1 is made", sorted(line) == [1, 2, 3, 4, 5], line)
    t = line
    call(S, P + "/selection", {"selection": {"branch": "b1", **{str(i): t[i] for i in t}}}, "PUT")
    before = json.dumps(call(S, P + "/plan?branch=b1"), sort_keys=True)

    # ---------------- what can be taken over: portions that start a scene
    dup = lambda keep: call(S, P + "/branches", {"how": "clips", "source": "b1", "leaf": t[5], "keep": keep})  # noqa: E731
    bad = dup([2])
    check("clip 2 alone is refused (it continues clip 1)", bad.get("HTTP") == 400 and "continues clip 1" in bad.get("error", ""), bad)
    check("clips 3 and 5 without 4 is fine, 4 without 3 is not", dup([4]).get("HTTP") == 400 and dup([]).get("HTTP") == 400)
    b = dup([1, 3, 4])
    B = b["branch"]["id"]
    check("portions 1 and 3 → 4 taken over, clip 2 left free", b["branch"]["base"]["takes"] == [t[1], None, t[3], t[4]], b["branch"].get("base"))
    mv = call(S, P + f"/plan?branch={B}")
    check("its master plan: clips taken over read-only, clip 2 left free and editable", mv.get("locked") == 4 and mv.get("holes") == [2] and mv.get("free") == [2]
          and mv.get("takes") == {"1": t[1], "3": t[3], "4": t[4]}, {k: mv.get(k) for k in ("locked", "holes", "takes")})
    m = mv["plan"]
    m["clips"][1]["frames"] = 121
    out = call(S, P + "/plan", {"branch": B, "leaf": None, "plan": m}, "PUT")
    check("the length of the clip left free is locked", out.get("HTTP") == 400 and "keep their length" in out.get("error", ""), out)
    out = call(S, P + "/generate", {"clip": 5, "after": t[4], "branch": B})
    check("clip 5 after the portion waits for clip 2 of the branch", out.get("HTTP") == 400 and "Clip 2 of this branch" in out.get("error", ""), out)
    todo = call(S, P + f"/branches/{B}/fill", {"dry_run": True})
    check("▶▶ fills clips 2 and 5 only", [i["clip"] for i in todo.get("items") or []] == [2, 5], todo)
    done = call(S, P + f"/branches/{B}/fill", {"dry_run": False, "assemble": True}); run()
    jobs = {j["id"]: j for j in call(S, P + "/jobs")["jobs"]}
    made = [jobs[i] for i in done.get("launched") or []]
    check("clip 2 is made after clip 1, clip 5 after the clip 4 taken over", [j.get("predecessor") for j in made] == [t[1], t[4]]
          and all(j["status"] == "done" for j in made), [(j.get("predecessor"), j["status"], j.get("error")) for j in made])
    n2, n5 = (j["take"] for j in made)
    tw = call(S, P + f"/plan?branch={B}&leaf={n5}")
    check("the twig goes through its own clip 2, then the portion", tw.get("chain") == [t[1], n2, t[3], t[4], n5], tw.get("chain"))
    asm = jobs.get(done.get("assembly")) or {}
    check("the assembly of the master line has the 5 clips", asm.get("clips") == 5 and asm.get("status") == "done", (asm.get("clips"), asm.get("status"), asm.get("error")))
    tw4 = call(S, P + f"/plan?branch={B}&leaf={t[4]}")
    check("the twig up to the clip 4 taken over goes through clip 2 of the branch", tw4.get("chain") == [t[1], n2, t[3], t[4]], tw4.get("chain"))
    entry = dict(call(S, P + f"/plan?branch={B}&leaf={n2}")["plan"]["clips"][1], frames=121)
    out = call(S, P + "/generate", {"clip": 2, "after": t[1], "branch": B, "entry": entry})
    check("a new take of clip 2 keeps its length", out.get("HTTP") == 400 and "keeps its length" in out.get("error", ""), out)
    out = call(S, P + "/generate", {"clip": 4, "after": t[3], "branch": B}); run()
    check("a new take of the clip 4 taken over is made in the branch", out.get("HTTP") is None and out["record"]["studio"]["branch"] == B, out)
    check("branch 1 does not change", json.dumps(call(S, P + "/plan?branch=b1"), sort_keys=True) == before)
    # ---------------- a portion at the end: 1 → 2 and 5, clips 3 → 4 free
    c = dup([1, 2, 5])
    C = c["branch"]["id"]
    check("portions 1 → 2 and 5", c["branch"]["base"]["takes"] == [t[1], t[2], None, None, t[5]], c["branch"].get("base"))
    done = call(S, P + f"/branches/{C}/fill", {"dry_run": False, "assemble": True}); run()
    jobs = {j["id"]: j for j in call(S, P + "/jobs")["jobs"]}
    check("▶▶ makes clips 3 and 4", [jobs[i]["clip"] for i in done.get("launched") or []] == [3, 4])
    asm = jobs.get(done.get("assembly")) or {}
    check("its assembly ends with the clip 5 taken over", asm.get("clips") == 5 and asm.get("status") == "done", (asm.get("clips"), asm.get("status"), asm.get("error")))
finally:
    srv.terminate()
print("FAILED" if FAILS else "ALL OK", len(FAILS))
sys.exit(1 if FAILS else 0)
