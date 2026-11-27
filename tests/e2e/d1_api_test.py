"""0.48 (API): the master line of a branch (takes made from the master plan itself, one per clip, in order), the
master plan frozen once the branch has takes (its clips and subjects; clips and subjects can be added), ▶▶ of a
branch = the master line, ▶▶ of the selection, « New branch with this plan », the masters in the takes listing."""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8244"; M = "http://127.0.0.1:8771"
OK = []


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
    OK.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))


restart_mock()
root = "/tmp/h3s_d1api"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "en"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8244", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "d1_srv.log"), "w"))
time.sleep(1.5)
P = "/api/projects/rue"


def run():
    for _ in range(120):
        time.sleep(0.3)
        call(M, "/test/run", {})
        jobs = call(S, P + "/jobs")["jobs"]
        if not any(j["status"] in ("queued", "running", "harvest") for j in jobs):
            break
    time.sleep(0.3)


def take_of(job):
    run()
    return next((j for j in call(S, P + "/jobs")["jobs"] if j["id"] == job.get("id")), {}).get("take")


def records():
    return {t["id"]: t["record"] for c in call(S, P + "/takes")["clips"] for t in c["takes"]}


try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    master = call(S, P + "/plan?branch=b1")
    n = len(master["plan"]["clips"])
    check("a branch without takes: master plan free", master["locked"] == 0 and not master.get("frozen"), master.get("locked"))

    # ---- the master line: clip 1, in order, once
    j1 = call(S, P + "/generate", {"clip": 1, "branch": "b1", "line": True})
    check("clip 1 of the master line launched", j1.get("take_id") and j1["record"]["studio"].get("line"), j1)
    again = call(S, P + "/generate", {"clip": 1, "branch": "b1", "line": True})
    check("a cell of the line is generated once", again.get("HTTP") == 400, again)
    skip = call(S, P + "/generate", {"clip": 3, "branch": "b1", "line": True})
    check("the line is generated in order", skip.get("HTTP") == 400, skip)
    l1 = take_of(j1)
    check("the take is a take of the master line", records()[l1]["studio"].get("line") is True)

    # ---- the master plan is frozen
    m = call(S, P + "/plan?branch=b1")
    check("master plan frozen: its clips read-only", m["locked"] == n and m["frozen"]["clips"] == n, (m["locked"], m.get("frozen")))
    check("… the take of the line for clip 1", m["takes"].get("1") == l1 or m["takes"].get(1) == l1, m["takes"])
    plan = m["plan"]
    bad = json.loads(json.dumps(plan)); bad["clips"][1]["summary"] = "changed"
    r = call(S, P + "/plan", {"branch": "b1", "plan": bad}, "PUT")
    check("a frozen clip cannot change", r.get("HTTP") == 400 and "clips 1" in r.get("error", ""), r)
    bad = json.loads(json.dumps(plan)); first = sorted(bad["subjects"])[0]; bad["subjects"][first]["description"] = "another"
    r = call(S, P + "/plan", {"branch": "b1", "plan": bad}, "PUT")
    check("a frozen subject cannot change", r.get("HTTP") == 400 and "@" + first in r.get("error", ""), r)
    bad = json.loads(json.dumps(plan)); bad["clips"] = bad["clips"][:-1]
    r = call(S, P + "/plan", {"branch": "b1", "plan": bad}, "PUT")
    check("a frozen clip cannot be removed", r.get("HTTP") == 400, r)
    good = json.loads(json.dumps(plan))
    extra = json.loads(json.dumps(good["clips"][-1])); extra["name"] = "added_clip"; extra["continue"] = False
    good["clips"].append(extra)
    good["subjects"]["chien"] = {"kind": "person", "description": "a small dog", "pictures": []}
    r = call(S, P + "/plan", {"branch": "b1", "plan": good}, "PUT")
    check("clips can be added at the end, and new subjects", "HTTP" not in r, r)
    m = call(S, P + "/plan?branch=b1")
    check("the added clip stays free", m["locked"] == n and len(m["plan"]["clips"]) == n + 1, (m["locked"], len(m["plan"]["clips"])))
    good = json.loads(json.dumps(m["plan"])); good["clips"][-1]["summary"] = "the added clip, changed"
    good["subjects"]["chien"]["description"] = "a big dog"
    r = call(S, P + "/plan", {"branch": "b1", "plan": good}, "PUT")
    check("… and can still change, like the new subject", "HTTP" not in r, r)

    # ---- the takes listing knows the masters
    listing = call(S, P + "/takes")
    check("listing: master line of each branch", listing["masters"]["b1"]["frozen"] == n and len(listing["masters"]["b1"]["clips"]) == n + 1,
          listing.get("masters"))

    # ---- a fork of the line: a take of clip 2 from the launch panel (not on the line)
    fork = call(S, P + "/generate", {"clip": 2, "branch": "b1", "after": l1, "plan_from": l1})
    f2 = take_of(fork)
    check("a fork is not on the master line", not records()[f2]["studio"].get("line"))

    # ---- ▶▶ of the branch: the master line
    dry = call(S, P + "/branches/b1/fill", {"dry_run": True, "assemble": False})
    check("▶▶ of a branch fills the master line", dry["line"] and [i["clip"] for i in dry["items"]] == list(range(2, n + 2)), dry)
    out = call(S, P + "/branches/b1/fill", {"dry_run": False, "assemble": False})
    run()
    recs = records()
    line = sorted((r["id"] for r in recs.values() if r["studio"].get("line")), key=lambda t: recs[t]["saved_at"])
    check("every clip of the master line generated", len(line) == n + 1, len(line))
    check("each one after the line take before it", all(recs[line[k]]["studio"]["predecessor"] == line[k - 1] for k in range(1, len(line))))
    m = call(S, P + "/plan?branch=b1")
    check("the clips the line generated are frozen", m["locked"] == n + 1, m["locked"])
    check("▶▶ again: nothing left", call(S, P + "/branches/b1/fill", {"dry_run": True})["items"] == [])

    # ---- ▶▶ of the selection: a twig ending with the fork
    dry = call(S, P + "/branches/b1/fill", {"dry_run": True, "leaf": f2, "assemble": False})
    check("▶▶ of a selection off the line is not the line", not dry["line"] and dry["items"] and dry["items"][0]["clip"] == 3, dry)
    dry = call(S, P + "/branches/b1/fill", {"dry_run": True, "leaf": line[-1]})
    check("the selection ending the line has nothing left", dry["line"] and dry["items"] == [], dry)

    # ---- « New branch with this plan »: a branch whose master plan is free
    nb = call(S, P + "/use-plan", {"branch": "b1", "leaf": f2, "name": "Essai"})
    bid = nb["branch"]["id"]
    m = call(S, P + f"/plan?branch={bid}")
    check("new branch with the plan of a twig: master plan free", m["locked"] == 0 and not m.get("frozen") and m["plan"]["clips"][1]["summary"], m.get("locked"))
    check("the old « use as master plan » is gone", call(S, P + "/use-plan", {"branch": "b1", "leaf": f2, "target": "master"})["branch"]["id"] != "b1")

    # ---- a duplicated branch with its clips: its line starts after them
    dup = call(S, P + "/branches", {"how": "clips", "source": "b1", "leaf": line[1], "upto": 2})
    did = dup["branch"]["id"]
    dry = call(S, P + f"/branches/{did}/fill", {"dry_run": True, "assemble": False})
    check("a duplicated branch: its line goes on after the clips it takes over", dry["line"] and dry["items"][0]["clip"] == 3, dry)
    m = call(S, P + f"/plan?branch={did}")
    check("… its master plan stays free after them", m["locked"] == 2 and not m.get("frozen"), (m["locked"], m.get("frozen")))
    j = call(S, P + "/generate", {"clip": 3, "branch": did, "line": True})
    t3 = take_of(j)
    check("… clip 3 of its line follows clip 2 taken over", records()[t3]["studio"]["predecessor"] == line[1])
    m = call(S, P + f"/plan?branch={did}")
    check("… then its master plan is frozen", m["locked"] >= 3 and m.get("frozen"), (m["locked"], m.get("frozen")))
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
