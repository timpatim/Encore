"""Chantier A, lot A3 (API): a take is deleted with the takes made after it (a branch that took it over keeps the
clips before it); a branch is deleted without the takes another branch takes over; everything goes to the trash,
from which it is restored or erased."""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8246"; M = "http://127.0.0.1:8771"


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
root = "/tmp/h3s_a3api"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8246", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "a3_srv.log"), "w"))
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
    call(S, P + "/import-plan?filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    for f in (fixture("fillette.png"), fixture("rue.png")):
        call(S, f"{P}/resources?kind=images&filename={os.path.basename(f)}", raw=open(f, "rb").read(), method="POST")
    root_p = root + "/projets/rue"
    gen = lambda body: (lambda j: (run(), take_of(j))[1])(call(S, P + "/generate", body))
    t1 = gen({"clip": 1, "branch": "b1"})
    t2a = gen({"clip": 2, "after": t1}); t2b = gen({"clip": 2, "after": t1})
    t3 = gen({"clip": 3, "after": t2a}); t4 = gen({"clip": 4, "after": t3})
    B2 = call(S, P + "/branches", {"how": "clips", "source": "b1", "leaf": t3, "upto": 3})["branch"]["id"]
    t4c = gen({"clip": 4, "after": t3, "branch": B2})
    check("set up: 1, 2a, 2b, 3, 4 in b1; b2 takes 1-3 over, 4c", all((t1, t2a, t2b, t3, t4, t4c)))
    on_disk = lambda tid, i: os.path.isfile(f"{root_p}/takes/clip_{i:03d}/{tid}.json")

    # ---------------- a take with what follows it
    out = call(S, P + "/takes/delete", {"take": t2a})
    ids = sorted(t for _i, t, _b in out.get("takes", []))
    check("deleting 2a: it, 3, 4 and 4c (made after it), not 2b", out.get("needs_confirm") and ids == sorted([t2a, t3, t4, t4c]), ids)
    check("…and the branch that took it over keeps clip 1", list(out.get("bases", {}).values()) == [1], out.get("bases"))
    out = call(S, P + "/takes/delete", {"take": t2a, "confirm": True})
    check("deleted: the files leave the takes", out.get("deleted") and not on_disk(t2a, 2) and not on_disk(t4c, 4) and on_disk(t2b, 2), out.get("error"))
    pr = out["project"]
    check("b2 now takes over clip 1 only", pr["branch_states"][B2]["base"] == [t1], pr["branch_states"][B2])
    tr = call(S, P + "/trash")["entries"]
    check("one entry in the trash, with 4 takes", len(tr) == 1 and tr[0]["takes"] == 4 and tr[0]["kind"] == "take", tr)
    out = call(S, P + f"/trash/{tr[0]['id']}/restore", {})
    check("restored: files, the clips b2 took over", out.get("restored") and on_disk(t2a, 2) and on_disk(t4c, 4)
          and out["project"]["branch_states"][B2]["base"] == [t1, t2a, t3], out.get("error"))
    check("the twig of 4c is whole again", call(S, P + f"/plan?branch={B2}&leaf={t4c}")["chain"] == [t1, t2a, t3, t4c])
    check("the trash is empty again", call(S, P + "/trash")["entries"] == [])

    # ---------------- a branch: the takes another branch takes over stay
    out = call(S, P + "/branches/b1?confirm=1", method="DELETE")
    check("b1 deleted; 1, 2a, 3 kept (taken over by b2), 2b and 4 in the trash",
          out.get("deleted") and out.get("kept") == 3 and out.get("delete") == 2 and on_disk(t3, 3) and not on_disk(t2b, 2) and not on_disk(t4, 4), out)
    check("b2 still goes through the clips it took over", call(S, P + f"/plan?branch={B2}&leaf={t4c}")["chain"] == [t1, t2a, t3, t4c])
    t5 = gen({"clip": 5, "after": t4c, "branch": B2})
    check("b2 goes on generating", bool(t5))
    tr = call(S, P + "/trash")["entries"]
    out = call(S, P + f"/trash/{tr[0]['id']}/restore", {})
    check("b1 restored with its takes and master plan", out.get("restored") and any(b["id"] == "b1" for b in out["project"]["branches"])
          and on_disk(t2b, 2) and call(S, P + "/plan?branch=b1")["plan"]["clips"], out.get("error"))

    # ---------------- erased for good; a take a waiting generation needs is not deleted
    call(S, P + "/takes/delete", {"take": t2b, "confirm": True})
    tr = call(S, P + "/trash")["entries"]
    out = call(S, P + f"/trash/{tr[0]['id']}", method="DELETE")
    check("erased: gone from the trash and the disk", out.get("entries") == [] and not os.path.isdir(f"{root_p}/trash/{tr[0]['id']}") and not on_disk(t2b, 2), out)
    entry = dict(call(S, P + f"/plan?branch={B2}&leaf={t5}")["plan"]["clips"][4], name="clip_006")
    j6 = call(S, P + "/generate", {"clip": 6, "after": t5, "branch": B2, "entry": entry})
    out = call(S, P + "/takes/delete", {"take": t5, "confirm": True})
    check("refused while a generation needs it", j6.get("status") == "queued" and out.get("HTTP") == 400 and on_disk(t5, 5), (j6.get("error"), out.get("error")))
    run()

    # ---------------- « Nouvelle branche avec ce plan… » (0.48: a master plan is no longer replaced)
    old = call(S, P + "/plan?branch=b1")["plan"]
    twig = call(S, P + f"/plan?branch=b1&leaf={t4}")
    out = call(S, P + "/use-plan", {"branch": "b1", "leaf": t4, "name": "Essai"})
    nb = out.get("branch") or {}
    st = (out.get("project") or {}).get("branch_states", {}).get(nb.get("id"), {})
    check("a new branch with this master plan, nothing taken over", nb.get("name") == "Essai" and not st.get("has_takes")
          and [c["summary"] for c in call(S, P + f"/plan?branch={nb['id']}")["plan"]["clips"]] == [c["summary"] for c in twig["plan"]["clips"]], out.get("error"))
    check("…the branch it comes from keeps its master plan", [c["summary"] for c in call(S, P + "/plan?branch=b1")["plan"]["clips"]] == [c["summary"] for c in old["clips"]])

    # ---------------- a selection through a generation still waiting
    j5 = call(S, P + "/generate", {"clip": 5, "after": t4, "branch": "b1"})
    p5 = j5.get("take_id")
    out = call(S, P + "/selection", {"selection": {"branch": "b1", "1": t1, "2": t2a, "3": t3, "4": t4, "5": p5}}, "PUT")
    sel = {c["index"]: c["selected"] for c in out["clips"]}
    check("a waiting generation can be selected", sel.get(5) == p5, sel)
    tw = call(S, P + f"/plan?branch=b1&leaf={p5}")
    check("…the plan of the selection goes through it", tw.get("chain") == [t1, t2a, t3, t4, p5] and call(S, P)["plan_leaf"] == p5, tw.get("error"))
    out = call(S, P + "/use-plan", {"branch": "b1", "leaf": p5, "name": "Essai 2"})
    check("…and « Utiliser ce plan » works with it", (out.get("branch") or {}).get("name") == "Essai 2", out.get("error"))
    run()
    check("once made, the take is still selected", {c["index"]: c["selected"] for c in call(S, P + "/takes")["clips"]}.get(5) == p5)

    # ---------------- the settings of the project are saved (0.44.1: lost in 0.42) and used by the next generation
    st = call(S, P)["settings"]
    out = call(S, P + "/settings", dict(st, unet_name="autre_modele_h3.safetensors", steps=6), "PUT")
    pr = call(S, P)["settings"]
    check("project settings saved", out.get("settings", {}).get("unet_name") == "autre_modele_h3.safetensors"
          and pr["unet_name"] == "autre_modele_h3.safetensors" and pr["steps"] == 6, out.get("error"))
    call(S, P + "/generate", {"clip": 2, "after": t1, "branch": "b1"}); run()
    wf = json.load(open("/tmp/mock_last_prompt.json"))
    check("…and sent to ComfyUI with the next generation",
          any(n.get("class_type") == "UNETLoader" and n["inputs"].get("unet_name") == "autre_modele_h3.safetensors" for n in wf.values()))
    print("ERRORS:", [j.get("error") for j in call(S, P + "/jobs")["jobs"] if j.get("error")])
finally:
    srv.terminate()
