"""Chantier B, lot B1 (API): plan v7 (files, subjects, anchors), the prompt composed by the server and the one written
by hand, what reaches ComfyUI, the files a plan uses (resources), ▶▶ while a generation of the branch runs."""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8243"; M = "http://127.0.0.1:8771"
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
root = "/tmp/h3s_b1api"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8243", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "b1_srv.log"), "w"))
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


def job_of(job):
    return next(x for x in call(S, P + "/jobs")["jobs"] if x["id"] == job["id"])


try:
    call(S, "/api/projects", {"name": "rue", "mode": "free"})
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png"), fixture("v20_beach.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    plan = call(S, P + "/plan?branch=b1")["plan"]
    check("the plan is a v7 plan", plan.get("version") == 7 and "fillette" in plan["subjects"] and "refs" not in plan, list(plan))

    # ---- a first-frame anchor, a retention, a note: the composed prompt
    plan["files"]["start"] = {"kind": "image", "file": "refs/images/rue.png"}
    plan["clips"][0]["anchors"] = {"first": "start"}
    plan["clips"][0]["subjects"] = [{"name": "fillette", "keep": "partial", "note": "wears a red cap"}]
    out = call(S, P + "/plan", {"branch": "b1", "plan": plan}, "PUT")
    check("plan saved", not out.get("HTTP") and not out.get("validation", {}).get("errors"), out.get("validation") or out)
    pre = call(S, P + "/plan/compose", {"plan": plan})
    c1 = pre["clips"][0]
    check("compose: no error", not pre["errors"], pre["errors"])
    check("compose: legend of clip 1", c1["legend"]["subjects"] == ["fillette", "homme", "rue"] and c1["legend"]["pictures"] == ["fillette", "rue", "start"],
          c1["legend"])
    check("compose: the anchor and the retention in the text",
          "<Picture 3> is the first frame of [Shot 1]." in c1["prompt"] and "[Shot 1] The shot begins from <Picture 3>." in c1["prompt"]
          and "partially_preserved - wears a red cap" in c1["prompt"] and c1["tasks"] == ["keyframe completion", "reference generation"],
          c1["prompt"][:400])
    bad = json.loads(json.dumps(plan)); bad["clips"][1]["summary"] += " @chien"
    check("compose: an unknown @ is an error", any("@chien" in e for e in call(S, P + "/plan/compose", {"plan": bad})["errors"]))

    # ---- what reaches ComfyUI: the same text, the three pictures
    j1 = call(S, P + "/generate", {"clip": 1, "branch": "b1"}); run()
    t1 = job_of(j1).get("take")
    cap = call(M, "/test/cap", {})
    check("clip 1 made", bool(t1), job_of(j1).get("error"))
    check("ComfyUI gets the composed prompt", (cap["r2v"]["prompt"] or "") == c1["prompt"], (cap["r2v"]["prompt"] or "")[:300])
    wf = json.load(open("/tmp/mock_last_prompt.json"))
    # 0.50: one LoadImage per picture of the clip, wired in the order of <Picture i>
    images = [k for k, n in wf.items() if n["class_type"] == "LoadImage"]
    r2v = next(n for n in wf.values() if n["class_type"] == "MiniMaxH3ReferenceToVideo")["inputs"]
    wired = sorted(k for k, v in r2v.items() if k.startswith("ref_images.") and isinstance(v, list))
    check("one LoadImage per picture, wired to the reference node", len(images) == 3 and len(wired) == 3, (images, wired))
    rec = next(t["record"] for c in call(S, P + "/takes")["clips"] for t in c["takes"] if t["id"] == t1)
    defs = rec["studio"]["portion"]["clip"]["defs"]
    check("the take keeps the subjects and files it was made with", set(defs["subjects"]) == {"fillette", "homme", "rue"}
          and defs["files"]["start"]["file"] == "refs/images/rue.png", defs)

    # ---- clip 2: a prompt written by hand
    twig = call(S, P + f"/plan?leaf={t1}")["plan"]
    twig["clips"][1]["prompt_override"] = ("subject_definitions:\n@fillette is the girl of <Picture 1>.\n\nsummary:\n[video continuation] "
                                           "@fillette laughs.\n\nretention_analysis:\n\ndetailed_description:\n[Shot 1] @fillette (S) laughs.\n\n"
                                           "overall_soundscape:\nstreet\n\nnon_diegetic_music:\nNone.")
    call(S, P + "/plan", {"branch": "b1", "leaf": t1, "plan": twig}, "PUT")
    j2 = call(S, P + "/generate", {"clip": 2, "after": t1}); run()
    t2 = job_of(j2).get("take")
    got = call(M, "/test/cap", {})["r2v"]["prompt"] or ""
    check("clip 2 made from the prompt written by hand", bool(t2) and "<Subject 1> is the girl of <Picture 1>." in got
          and "<Subject 1> (S1) laughs." in got and "@" not in got, got[:300])

    # ---- the files a plan uses: the project's resources
    use = call(S, P + "/resources/usage?path=refs/images/rue.png")
    check("a file of the plan is in use", use.get("current"), use)
    out = call(S, P + "/resources?path=refs/images/rue.png", method="DELETE")
    check("…and cannot be deleted", out.get("HTTP") == 400, out)
    use = call(S, P + "/resources/usage?path=refs/images/v20_beach.png")
    check("a file no plan uses is not in use", use.get("current") == [] and use.get("takes") == 0, use)

    # ---- ▶▶ while a generation of the branch is waiting
    j3 = call(S, P + "/generate", {"clip": 3, "after": t2})
    leaf = j3["take_id"]
    todo = call(S, P + "/branches/b1/fill", {"leaf": leaf, "dry_run": True})
    check("▶▶ answers while a generation of the branch waits", todo.get("items") and todo["items"][0]["clip"] == 4, todo)
    out = call(S, P + "/branches/b1/fill", {"leaf": leaf, "dry_run": False, "assemble": False})
    check("…and launches after it", len(out.get("launched") or []) == len(todo["items"]), out)
    for _ in range(len(todo["items"]) + 2):
        run()
    jobs = call(S, P + "/jobs")["jobs"]
    made = [j for j in jobs if j["id"] in (out.get("launched") or []) + [j3["id"]]]
    check("every clip made", made and all(j["status"] == "done" for j in made), [(j["clip"], j["status"], j.get("error")) for j in made])
    print("ERRORS:", [j.get("error") for j in call(S, P + "/jobs")["jobs"] if j.get("error")])

    # ---- speakers: S1, S2… in the order they speak (girl first in clip 1, the man first in clip 2)
    pre = call(S, P + "/plan/compose", {"plan": call(S, P + "/plan?branch=b1")["plan"]})
    check("speakers numbered in the order they speak", pre["clips"][0]["speakers"] == [["fillette", 1], ["homme", 2]]
          and pre["clips"][1]["speakers"] == [["homme", 1], ["fillette", 2]], [c.get("speakers") for c in pre["clips"][:2]])

    # ---- deleting a project: refused while one of its generations waits, then for good
    j = call(S, P + "/generate", {"clip": 1, "branch": "b1"})
    out = call(S, P, method="DELETE")
    check("a project with a generation waiting is not deleted", out.get("HTTP") == 400 and out.get("code") == "busy", out)
    run()
    summary = call(S, P + "/summary")
    out = call(S, P, method="DELETE")
    check("project deleted for good", out.get("deleted") and not os.path.isdir(root + "/projets/rue") and summary["takes"] >= 5, (out, summary))
    check("…and gone from the list", "rue" not in [p_["name"] for p_ in call(S, "/api/projects").get("projects", [])])
finally:
    srv.terminate()
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
