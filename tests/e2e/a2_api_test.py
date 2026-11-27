"""Chantier A, lot A2 (API): new scenes (✂) follow the selected twig; import only into a branch without takes;
a waiting generation shows the take it will make; branches made empty, from a plan file or by duplication."""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, fixture, restart_mock  # noqa: E402
S = "http://127.0.0.1:8244"; M = "http://127.0.0.1:8771"


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
root = "/tmp/h3s_a2api"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
cfg = root + "/config.json"
json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True, "language": "fr"}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8244", "--no-browser", "--config", cfg], cwd=ENCORE,
                       stdout=subprocess.DEVNULL, stderr=open(os.path.join(ENCORE, "tests", "e2e", "out", "a2_srv.log"), "w"))
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
    master = call(S, P + "/plan?branch=b1")["plan"]
    master["clips"][2]["continue"] = False            # clip 3: a new scene
    call(S, P + "/plan", {"branch": "b1", "leaf": None, "plan": master}, "PUT")

    # ---------------- a waiting generation: the take it will make is known (↻ before it is finished)
    j1 = call(S, P + "/generate", {"clip": 1, "branch": "b1"})
    rec = j1.get("record") or {}
    check("a waiting job shows its future take", rec.get("id") == j1.get("take_id") and rec.get("pending") and "portion" in rec.get("studio", {}), rec)
    run(); t1 = take_of(j1)

    # ---------------- new scenes follow the selection
    j2a = call(S, P + "/generate", {"clip": 2, "after": t1}); run(); t2a = take_of(j2a)
    j2b = call(S, P + "/generate", {"clip": 2, "after": t1}); run(); t2b = take_of(j2b)
    call(S, P + "/selection", {"selection": {"branch": "b1", "1": t1, "2": t2a}}, "PUT")
    j3 = call(S, P + "/generate", {"clip": 3, "after": t2a}); run(); t3 = take_of(j3)
    listing = call(S, P + "/takes")
    check("the new scene fits after the other take of clip 2 (free mode)", t2b in listing["fits"].get(t3, []), listing.get("fits"))
    check("a continuation is not listed", t2b not in listing["fits"])
    out = call(S, P + "/selection", {"selection": {"branch": "b1", "1": t1, "2": t2b, "3": t3}}, "PUT")
    sel = {c["index"]: c["selected"] for c in out["clips"]}
    check("selection 1 → 2b → 3 (✂) kept", sel.get(3) == t3 and sel.get(2) == t2b, sel)
    tw = call(S, P + f"/plan?leaf={t3}")
    check("plan of the twig follows the selection at the cut", tw["chain"] == [t1, t2b, t3], tw.get("chain"))
    j4 = call(S, P + "/generate", {"clip": 4, "after": t3}); run(); t4 = take_of(j4)
    sel = {c["index"]: c["selected"] for c in call(S, P + "/takes")["clips"]}
    check("next clip after the cut: chosen with 2b kept", [sel.get(i) for i in (1, 2, 3, 4)] == [t1, t2b, t3, t4], sel)
    call(S, P + "/assemble", {"clip": 4, "take": t4}); run()
    ex = call(S, P + "/exports")["exports"]
    check("assembly of 1 → 2b → 3 → 4", ex and ex[0]["takes"] == {"1": t1, "2": t2b, "3": t3, "4": t4}, [e.get("takes") for e in ex])
    call(S, P + "/selection", {"selection": {"branch": "b1", "1": t1, "2": t2a, "3": t3, "4": t4}}, "PUT")
    check("back to 2a: the cut follows", call(S, P + f"/plan?leaf={t4}")["chain"] == [t1, t2a, t3, t4])

    # ---------------- import: only into a branch without takes
    out = call(S, P + "/import-plan?filename=rue.json&branch=b1", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    check("import refused into a branch with takes", out.get("HTTP") == 400 and "prises" in out.get("error", ""), out)

    # ---------------- new branches: duplicate without clips, from a plan file, with the clips of the selection
    b2 = call(S, P + "/branches", {"how": "copy", "source": "b1", "name": "Copie"})
    st = b2["project"]["branch_states"][b2["branch"]["id"]]
    check("duplicate without clips: same master, no take, free", b2["branch"]["name"] == "Copie" and not st["has_takes"]
          and call(S, P + f"/plan?branch={b2['branch']['id']}")["plan"]["clips"][2]["continue"] is False, st)
    bf = call(S, P + "/branches?how=file&filename=rue.json", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    check("new branch from a plan file", bf.get("branch", {}).get("id") and call(S, P + f"/plan?branch={bf['branch']['id']}")["plan"]["clips"][2]["continue"] is True, bf)
    b3 = call(S, P + "/branches", {"how": "clips", "source": "b1", "leaf": t4, "upto": 3})
    B3 = b3["branch"]["id"]
    st = b3["project"]["branch_states"][B3]
    check("duplicate with clips 1-3: taken over by reference", st["base"] == [t1, t2a, t3] and st["has_takes"], st)
    m3 = call(S, P + f"/plan?branch={B3}")
    check("its master plan: clips 1-3 read-only", m3["locked"] == 3 and m3["chain"] == [t1, t2a, t3], m3.get("locked"))
    # (before its own first take: its master plan is still free, 0.48)
    m3["plan"]["subjects"]["rue"]["pictures"][0]["file"] = "fillette"
    call(S, P + "/plan", {"branch": B3, "plan": m3["plan"]}, "PUT")
    m3b = call(S, P + f"/plan?branch={B3}")["plan"]
    check("a clip taken over keeps the subjects it was made with", m3b["clips"][0]["defs"]["subjects"]["rue"]["pictures"][0]["file"] == "rue"
          and m3b["subjects"]["rue"]["pictures"][0]["file"] == "fillette", m3b["clips"][0].get("defs"))
    out = call(S, P + "/generate", {"clip": 2, "after": t1, "branch": B3})
    check("0.48.2: a clip taken over gets a new take, a variant of this branch", out.get("HTTP") is None and out.get("record", {}).get("studio", {}).get("branch") == B3, out)
    run()
    jb = call(S, P + "/generate", {"clip": 4, "after": t3, "branch": B3}); run(); t4c = take_of(jb)
    rec = next((t["record"] for c in call(S, P + "/takes")["clips"] for t in c["takes"] if t["id"] == t4c), {})
    check("clip 4 in the new branch, after the clip taken over", t4c and rec.get("studio", {}).get("branch") == B3 and rec["studio"]["predecessor"] == t3, rec.get("studio", {}).get("branch"))
    check("its twig goes through the clips taken over", call(S, P + f"/plan?branch={B3}&leaf={t4c}")["chain"] == [t1, t2a, t3, t4c])
    out = call(S, P + "/branches/b1", method="DELETE")
    check("deleting a branch keeps the takes another one takes over", out.get("needs_confirm") and out.get("kept") == 3, out)
    b4 = call(S, P + "/branches", {"how": "clips", "source": "b1", "leaf": t4, "upto": 2})
    todo = call(S, P + f"/branches/{b4['branch']['id']}/fill", {"dry_run": True})
    check("▶▶ in a duplicated branch starts after the clips taken over", todo.get("items") and todo["items"][0]["clip"] == 3, todo)
    call(S, P + "/assemble", {"clip": 4, "take": t4c}); run()
    ex = call(S, P + "/exports")["exports"]
    check("assembly in the duplicated branch", ex and ex[0]["takes"] == {"1": t1, "2": t2a, "3": t3, "4": t4c}, [e.get("takes") for e in ex][:1])

    # ---------------- the essence of the project: mode, video, song, context; the same for every branch
    out = call(S, P + "/essence", {"context_frames": 90}, "PUT")
    check("the essence of a project with takes is frozen", out.get("HTTP") == 400, out)
    Q = "/api/projects/ess"
    call(S, "/api/projects", {"name": "ess", "mode": "music_video"})
    call(S, Q + "/branches", {"how": "empty"})
    pr = call(S, Q)
    check("a new project: its essence", pr["essence"] == {"mode": "music_video", "video": "none", "context_frames": 39}, pr.get("essence"))
    call(S, f"{Q}/resources?kind=songs&filename=chanson.wav", raw=open(fixture("v20_song.wav"), "rb").read(), method="POST")
    pr = call(S, Q + "/essence", {"video": "continue", "context_frames": 22, "song": "refs/songs/chanson.wav"}, "PUT")
    m1, m2 = (call(S, Q + f"/plan?branch={b}")["plan"] for b in ("b1", "b2"))
    check("every master plan follows the essence", all(m.get("start_video") and m["context_frames"] == 22 and m["mode"] == "music_video" for m in (m1, m2)), (m1.get("start_video"), m2.get("context_frames")))
    check("the song is the project's, in every branch", pr["song"] == "refs/songs/chanson.wav" and all(b["song"] == "refs/songs/chanson.wav" for b in pr["branches"]), pr.get("song"))
    m1["start_video"]["start"] = 2.0
    call(S, Q + "/plan", {"branch": "b1", "leaf": None, "plan": m1}, "PUT")
    check("the segment is the branch's", call(S, Q)["segments"]["b1"]["start"] == 2.0 and call(S, Q)["segments"]["b2"].get("start", 0) == 0, call(S, Q)["segments"])
    out = call(S, Q + "/import-plan?filename=rue.json&branch=b2", raw=open(fixture("rue_test_v1.plan.json"), "rb").read(), method="POST")
    pr = call(S, Q)
    check("no take yet: an imported plan sets the essence", pr["essence"]["mode"] == "free" and call(S, Q + "/plan?branch=b1")["plan"]["mode"] == "free", pr.get("essence"))
    print("ERRORS:", [j.get("error") for j in call(S, P + "/jobs")["jobs"] if j.get("error")])
finally:
    srv.terminate()
