"""Chantier A, lot A1 (API): takes carry their portion of plan; a twig's plan is composed from them.
Free mode (rue plan): clip 1, clip 2 after it, a fork of clip 2 with another prompt, clip 3 after the fork, the
suite of a twig changed without touching the master plan, an assembly of the twig, ▶▶ compléter."""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8241"; M = "http://127.0.0.1:8771"


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


restart_mock()
root = "/tmp/h3s_a1api"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8241", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "a1_srv.log"), "w"))
time.sleep(1.5)
P = "/api/projects/rue"


def run():
    """Let the mock ComfyUI run every job sent to it, until none is waiting (a job is only sent to ComfyUI a moment
    after it is queued: run again while one is still queued)."""
    for _ in range(60):
        time.sleep(0.3)
        call(M, "/test/run", {})
        jobs = call(S, P + "/jobs")["jobs"]
        if not any(j["status"] in ("queued", "running", "harvest") for j in jobs):
            break
    time.sleep(0.3)


def take_of(job):
    for _ in range(20):
        j = next(x for x in call(S, P + "/jobs")["jobs"] if x["id"] == job["id"])
        if j.get("take"):
            return j["take"]
        time.sleep(0.3)
    return None


try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    out = call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    check("import into the first branch (no take yet)", out.get("branch") == "b1" and not out.get("created_branch"), out)
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    master = call(S, P + "/plan?branch=b1")
    n = len(master["plan"]["clips"])
    check("master plan, nothing locked", master["locked"] == 0 and n >= 4, master.get("locked"))

    j1 = call(S, P + "/generate", {"clip": 1, "branch": "b1"}); run(); t1 = take_of(j1)
    check("clip 1 made", bool(t1), j1)
    j2 = call(S, P + "/generate", {"clip": 2, "after": t1}); run(); t2 = take_of(j2)
    check("clip 2 after clip 1", bool(t2), j2)
    tw = call(S, P + f"/plan?leaf={t2}")
    check("twig 1→2: two clips locked", tw["locked"] == 2 and tw["chain"] == [t1, t2], tw.get("chain"))
    check("twig plan = master plan (nothing changed yet)", [c["summary"] for c in tw["plan"]["clips"][2:]] == [c["summary"] for c in master["plan"]["clips"][2:]])

    # fork of clip 2: same predecessor, another prompt, seed of the take forked
    entry = dict(tw["plan"]["clips"][1], summary=tw["plan"]["clips"][1]["summary"] + "\nA red umbrella.")
    seed2 = next(x for x in call(S, P + "/jobs")["jobs"] if x["id"] == j2["id"])["seed"]
    j2b = call(S, P + "/generate", {"clip": 2, "after": t1, "plan_from": t2, "entry": entry, "seed": seed2}); run(); t2b = take_of(j2b)
    check("fork of clip 2 made with the same seed", bool(t2b) and t2b.startswith(f"s{seed2}_"), (t2b, seed2))
    tw2b = call(S, P + f"/plan?leaf={t2b}")
    check("the fork keeps its own prompt", tw2b["plan"]["clips"][1]["summary"].endswith("A red umbrella."))
    check("the first take keeps its prompt", not call(S, P + f"/plan?leaf={t2}")["plan"]["clips"][1]["summary"].endswith("A red umbrella."))

    # the suite of a twig changes; the master plan and the other twig do not
    plan = tw2b["plan"]; plan["clips"][3]["summary"] = "CHANGED clip 4"
    out = call(S, P + "/plan", {"branch": "b1", "leaf": t2b, "plan": plan}, "PUT")
    check("suite saved", out.get("locked") == 2 and out["plan"]["clips"][3]["summary"] == "CHANGED clip 4", out.get("HTTP"))
    check("master unchanged", call(S, P + "/plan?branch=b1")["plan"]["clips"][3]["summary"] != "CHANGED clip 4")
    check("other twig unchanged", call(S, P + f"/plan?leaf={t2}")["plan"]["clips"][3]["summary"] != "CHANGED clip 4")
    locked_edit = dict(plan); locked_edit["clips"] = [dict(c) for c in plan["clips"]]; locked_edit["clips"][0]["summary"] = "nope"
    call(S, P + "/plan", {"branch": "b1", "leaf": t2b, "plan": locked_edit}, "PUT")
    check("a generated clip is not changed by saving", not call(S, P + f"/plan?leaf={t2b}")["plan"]["clips"][0]["summary"] == "nope")

    # clip 3 after the fork, then its suite came from the fork's twig
    j3 = call(S, P + "/generate", {"clip": 3, "after": t2b}); run(); t3 = take_of(j3)
    tw3 = call(S, P + f"/plan?leaf={t3}")
    check("clip 3 after the fork: suite inherited", tw3["locked"] == 3 and tw3["plan"]["clips"][3]["summary"] == "CHANGED clip 4", tw3.get("locked"))
    sel = call(S, P + "/takes")
    chosen = {c["index"]: c["selected"] for c in sel["clips"]}
    check("selection follows the new take", chosen.get(1) == t1 and chosen.get(2) == t2b and chosen.get(3) == t3, chosen)
    check("project plan = plan of the selection", call(S, P)["plan_leaf"] == t3)

    # frozen settings of a branch with takes
    out = call(S, P + "/branches/b1", {"width": 640, "height": 384}, "PUT")
    check("size frozen", out.get("HTTP") == 400 or "error" in out, out)
    # (B1) the subjects are in the plan: a picture changed in a suite only goes to the clips after
    plan = call(S, P + f"/plan?leaf={t3}")["plan"]
    plan["subjects"]["fillette"]["pictures"][0]["file"] = "rue"
    call(S, P + "/plan", {"branch": "b1", "leaf": t3, "plan": plan}, "PUT")
    again = call(S, P + f"/plan?leaf={t3}")["plan"]
    check("the clips already made keep their subjects", again["clips"][0]["defs"]["subjects"]["fillette"]["pictures"][0]["file"] == "fillette"
          and again["subjects"]["fillette"]["pictures"][0]["file"] == "rue", again["clips"][0].get("defs"))
    plan["subjects"]["fillette"]["pictures"][0]["file"] = "fillette"
    call(S, P + "/plan", {"branch": "b1", "leaf": t3, "plan": plan}, "PUT")

    # assembly of the twig 1 → 2b → 3
    a = call(S, P + "/assemble", {"clip": 3, "take": t3}); run()
    ex = call(S, P + "/exports")["exports"]
    check("assembly of the twig", ex and ex[0]["takes"] == {"1": t1, "2": t2b, "3": t3}, [e.get("takes") for e in ex] or a)

    # ▶▶ compléter from the twig: clips 4.. with the twig's suite
    todo = call(S, P + "/branches/b1/fill", {"leaf": t3, "dry_run": True})
    check("compléter lists the rest of the twig", [i["clip"] for i in todo["items"]] == list(range(4, n + 1)), todo)
    out = call(S, P + "/branches/b1/fill", {"leaf": t3, "dry_run": False, "assemble": True})
    for _ in range(len(todo["items"]) + 1):
        run()
    jobs = call(S, P + "/jobs")["jobs"]
    made = [j for j in jobs if j["id"] in out.get("launched", [])]
    check("compléter: every clip made", made and all(j["status"] == "done" for j in made), [(j["clip"], j["status"], j.get("error")) for j in made])
    last = made[-1]["take"] if made else None
    twl = call(S, P + f"/plan?leaf={last}") if last else {}
    check("the twig goes to the end", twl.get("locked") == n and twl["plan"]["clips"][3]["summary"] == "CHANGED clip 4", twl.get("locked"))
    ex = call(S, P + "/exports")["exports"]
    check("assembly after compléter", len(ex) == 2 and ex[0]["clips"] == n, [(e["clips"]) for e in ex])
    print("ERRORS:", [j.get("error") for j in call(S, P + "/jobs")["jobs"] if j.get("error")])
finally:
    srv.terminate()
