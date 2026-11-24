"""The validity of the takes is computed twice: by Encore's server (encore/takes.py, studio_resolve) and in the
page (ui/plan_core.js, studioResolveTakes). Both must give the same verdict: same state of every take, same chosen
take, same branch. The fingerprints of the clips must be the same too (plan_core.py / plan_core.js)."""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from encore import plan_core, takes  # noqa: E402

RAW = json.load(open(os.path.join(ROOT, "tests", "fixtures", "rue_test_v1.plan.json"), encoding="utf-8"))
PLAN = plan_core.normalize(copy.deepcopy(RAW))
FP = {c["index"]: plan_core.take_fingerprint(PLAN, c["index"]) for c in PLAN["clips"]}
CONT = {c["index"]: c["continue"] for c in PLAN["clips"]}
REFS = {"fillette": {"image": "img-a", "voice": "voice-a"}, "rue": {"image": "img-r", "voice": None}}


def current(**over):
    branches = {"b1": {"refs": copy.deepcopy(REFS), "song": None, "size": [960, 544], "ref_image_size": "max"},
                "b2": {"refs": copy.deepcopy(REFS), "song": None, "size": [960, 544], "ref_image_size": "max"}}
    for key, value in over.items():
        bid, field = key.split("__")
        branches[bid][field] = value
    return {"branches": branches, "default_branch": "b1", "legacy_ref_image_size": "match", "fingerprints": FP}


def take(index, tid, t, parent=None, branch="b1", **over):
    record = {"id": tid, "seed": 1, "saved_at": t, "fingerprint": FP[index], "frames": PLAN["clips"][index - 1]["frames"],
              "width": 960, "height": 544, "parent": parent,
              "studio": {"branch": branch, "refs": copy.deepcopy(REFS), "ref_image_size": "max"}}
    for key, value in over.items():
        if key.startswith("studio__"):
            record["studio"][key[8:]] = value
        else:
            record[key] = value
    return record


def chain(prefix, t0=1, branch="b1", over=None):
    """One take per clip, each continuing the previous one where the plan says so."""
    out, previous = {}, None
    for i in range(1, len(PLAN["clips"]) + 1):
        tid = f"{prefix}{i}"
        out[i] = [take(i, tid, t0 + i, previous if CONT[i] and i > 1 else None, branch, **(over or {}).get(i, {}))]
        previous = tid
    return out


def merge(*parts):
    out = {}
    for part in parts:
        for i, records in part.items():
            out.setdefault(i, []).extend(records)
    return out


other_refs = copy.deepcopy(REFS); other_refs["fillette"]["image"] = "img-b"
CASES = [
    ("all valid", chain("a"), {}, current()),
    ("plan of clip 2 changed", chain("a", over={2: {"fingerprint": "x"}}), {}, current()),
    ("picture changed in the branch", chain("a"), {}, current(b1__refs={**copy.deepcopy(REFS), "fillette": {"image": "img-z", "voice": "voice-a"}})),
    ("size changed", chain("a"), {}, current(b1__size=[768, 768])),
    ("reference size changed", chain("a"), {}, current(b1__ref_image_size="match")),
    ("a later take with another picture", merge(chain("a"), {1: [take(1, "n1", 50, studio__refs=other_refs)]}), {}, current()),
    ("two branches, selection in b2", merge(chain("a"), chain("b", 20, "b2")), {"branch": "b2"}, current()),
    ("two branches, selection by take", merge(chain("a"), chain("b", 20, "b2")), {1: "b1"}, current()),
    ("parent missing", {i: v for i, v in chain("a").items() if i != 1}, {}, current()),
    ("a second take of clip 1 chosen", merge(chain("a"), {1: [take(1, "c1", 40)]}), {1: "c1"}, current()),
    ("old take without ref_image_size", chain("a", over={1: {"studio__ref_image_size": None}}), {}, current(b1__ref_image_size="match")),
    ("width differs from the branch", chain("a", over={3: {"width": 512}}), {}, current()),
]


# a plan that starts from a video: clip 1 continues it, its takes record the video's SHA
def with_video(**spec):
    raw = copy.deepcopy(RAW)
    raw["version"] = 4
    raw["refs"]["intro"] = "filmed intro"
    raw["start_video"] = {"ref": "intro", "start": 0.5, "end": 7.25, **spec}
    raw["clips"][0]["continue"] = True
    return raw


VIDEO_VARIANTS = [with_video(), with_video(in_assembly=False), with_video(start=1.3, end=9.0),
                  dict(with_video(song="after_video"), mode="music_video", song={"file": "s.mp3"}),
                  dict(with_video(), mode="music_video", song={"file": "s.mp3"}),
                  dict(with_video(in_assembly=False), mode="music_video", song={"file": "s.mp3"})]
VRAW = VIDEO_VARIANTS[0]


# a plan that edits a video: every clip gets its slice of the segment
def with_edit(**spec):
    raw = copy.deepcopy(RAW)
    raw["version"] = 5
    raw["refs"]["source"] = "filmed video"
    total = plan_core.total_frames(plan_core.normalize(copy.deepcopy(RAW)))
    raw["edit_video"] = {"ref": "source", "start": 3.3, "end": 3.3 + total / 24 + 0.5, **spec}
    return raw


EDIT_VARIANTS = [with_edit(), with_edit(start=0.27, end=60.0, sound="h3"),
                 with_edit(end=5.0), with_edit(sound="loud"), dict(with_edit(), mode="music_video"),
                 dict(with_edit(), start_video={"ref": "source", "start": 0, "end": 4})]


def with_instruction(**spec):           # {edit} in clip 1, a picture named only in the instruction
    raw = with_edit(**spec)
    first = raw["refs"] and sorted(r for r in raw["refs"] if r != "source")[0]
    raw["edit_video"]["instruction"] = "the footage becomes a cartoon with {picture:%s}" % first
    raw["clips"][0]["prompt"] = raw["clips"][0]["prompt"].replace("summary:", "summary:\nAn edit of <Video 1>: {edit}.", 1)
    raw["clips"][0]["refs"] = [r for r in raw["clips"][0].get("refs", []) if r != first]
    return raw


def ends_early(**spec):                 # the segment ends inside the plan: the last clips continue the video
    raw = with_edit(**spec)
    raw["edit_video"]["end"] = raw["edit_video"]["start"] + 14.0
    return raw


EDIT_VARIANTS += [with_instruction(), ends_early(), dict(ends_early(), clips=[dict(c, prompt=c["prompt"] + " <Video 1>") for c in with_edit()["clips"]]),
                  dict(with_instruction(), edit_video=dict(with_instruction()["edit_video"], instruction=None))]
VPLAN = plan_core.normalize(copy.deepcopy(VRAW))
VFP = {c["index"]: plan_core.take_fingerprint(VPLAN, c["index"]) for c in VPLAN["clips"]}
VREFS = {**copy.deepcopy(REFS), "intro": {"image": None, "voice": None, "video": "vid-a"}}


def vtake(index, tid, t, parent=None, video="vid-a"):
    refs = copy.deepcopy(REFS)
    if index == 1:
        refs["intro"] = {"image": None, "voice": None, "video": video}
    return {"id": tid, "seed": 1, "saved_at": t, "fingerprint": VFP[index], "frames": VPLAN["clips"][index - 1]["frames"],
            "width": 960, "height": 544, "parent": parent, "studio": {"branch": "b1", "refs": refs, "ref_image_size": "max"}}


def vcurrent(video="vid-a"):
    refs = copy.deepcopy(VREFS); refs["intro"]["video"] = video
    return {"branches": {"b1": {"refs": refs, "song": None, "size": [960, 544], "ref_image_size": "max"}},
            "default_branch": "b1", "legacy_ref_image_size": "match", "fingerprints": VFP}


VCHAIN = {1: [vtake(1, "v1", 1)], 2: [vtake(2, "v2", 2, "v1" if VPLAN["clips"][1]["continue"] else None)]}
VCASES = [
    ("start video: all valid", VCHAIN, {}, vcurrent()),
    ("start video: the branch's video changed", VCHAIN, {}, vcurrent("vid-b")),
    ("start video: a later take with another video", {1: VCHAIN[1] + [vtake(1, "w1", 5, video="vid-b")], 2: VCHAIN[2]}, {}, vcurrent("vid-b")),
]


def python_side(plan=None, cases=None):
    out = []
    for _name, local, selection, cur in (cases or CASES):
        r = takes.studio_resolve(plan or PLAN, copy.deepcopy(local), dict(selection), cur)
        out.append({"branch": r["branch"], "clips": {str(i): {"chosen": v["chosen"], "states": {k: s[0] for k, s in v["takes"].items()}}
                                                      for i, v in r.items() if i != "branch"}})
    return out


def main():
    payload = {"plan": RAW, "fingerprints": {str(k): v for k, v in FP.items()},
               "cases": [{"takes": {str(i): v for i, v in local.items()}, "selection": {str(k): v for k, v in sel.items()}, "current": cur}
                         for _n, local, sel, cur in CASES]}
    js = json.loads(subprocess.run(["node", os.path.join(HERE, "parity.js")], input=json.dumps(payload), capture_output=True,
                                   text=True, check=True).stdout)
    js_fp = json.loads(subprocess.run(["node", "-e", "const H3=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d);"
                                       "process.stdin.on('end',async()=>process.stdout.write(JSON.stringify(await H3.takeFingerprints(JSON.parse(s)))))",
                                       os.path.join(ROOT, "ui", "plan_core.js")], input=json.dumps(RAW), capture_output=True, text=True, check=True).stdout)
    bad = 0
    for i, fp in FP.items():
        if js_fp.get(str(i)) != fp:
            bad += 1; print(f"FAIL fingerprint of clip {i}: js {js_fp.get(str(i))} / python {fp}")
    for number, raw in enumerate(VIDEO_VARIANTS, start=1):     # start video: fingerprints and timing
        normal = plan_core.normalize(copy.deepcopy(raw))
        want = {str(c["index"]): plan_core.take_fingerprint(normal, c["index"]) for c in normal["clips"]}
        want["final_start"], want["song_offset"] = plan_core.final_start(normal), plan_core.song_offset(normal)
        got = json.loads(subprocess.run(["node", "-e", "const H3=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d);"
                                         "process.stdin.on('end',async()=>{const p=JSON.parse(s);const f=await H3.takeFingerprints(p);"
                                         "f.final_start=H3.finalStart(p);f.song_offset=H3.songOffset(p);process.stdout.write(JSON.stringify(f))})",
                                         os.path.join(ROOT, "ui", "plan_core.js")], input=json.dumps(raw), capture_output=True, text=True,
                                        check=True).stdout)
        if got != want:
            bad += 1; print(f"FAIL start video variant {number}: js {got} / python {want}")
        else:
            print(f"PASS start video variant {number} (fingerprints, final start {want['final_start']}, song offset {want['song_offset']})")
    for number, raw in enumerate(EDIT_VARIANTS, start=1):     # edited video: fingerprints, slices, number of errors
        errors, _warnings = plan_core.validate(copy.deepcopy(raw))
        want = {"errors": len(errors)}
        if not errors:
            normal = plan_core.normalize(copy.deepcopy(raw))
            want.update({str(c["index"]): plan_core.take_fingerprint(normal, c["index"]) for c in normal["clips"]})
            want["slices"] = [list(x) if (x := plan_core.edit_slice(normal, c["index"])) else None for c in normal["clips"]]
        got = json.loads(subprocess.run(["node", "-e", "const H3=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d);"
                                         "process.stdin.on('end',async()=>{const p=JSON.parse(s);const e=H3.validate(p).filter(m=>m.level==='error');"
                                         "const f={errors:e.length};if(!e.length){Object.assign(f,await H3.takeFingerprints(p));"
                                         "f.slices=p.clips.map((c,i)=>H3.editSlice(p,i+1));}process.stdout.write(JSON.stringify(f))})",
                                         os.path.join(ROOT, "ui", "plan_core.js")], input=json.dumps(raw), capture_output=True, text=True,
                                        check=True).stdout)
        if got != want:
            bad += 1; print(f"FAIL edit video variant {number}: js {got} / python {want}")
        else:
            print(f"PASS edit video variant {number} ({want['errors']} error(s))")
    vpayload = {"plan": VRAW, "fingerprints": {str(k): v for k, v in VFP.items()},
                "cases": [{"takes": {str(i): v for i, v in local.items()}, "selection": {str(k): v for k, v in sel.items()}, "current": cur}
                          for _n, local, sel, cur in VCASES]}
    vjs = json.loads(subprocess.run(["node", os.path.join(HERE, "parity.js")], input=json.dumps(vpayload), capture_output=True,
                                    text=True, check=True).stdout)
    for (name, *_rest), py, j in zip(VCASES, python_side(VPLAN, VCASES), vjs):
        if py != j:
            bad += 1; print(f"FAIL {name}\n  python {py}\n  js     {j}")
        else:
            states = sorted({s for c in py["clips"].values() for s in c["states"].values()})
            print(f"PASS {name} ({', '.join(states)})")
    for (name, *_rest), py, j in zip(CASES, python_side(), js):
        if py != j:
            bad += 1; print(f"FAIL {name}\n  python {py}\n  js     {j}")
        else:
            states = sorted({s for c in py["clips"].values() for s in c["states"].values()})
            print(f"PASS {name} ({', '.join(states)})")
    total = len(CASES) + 1 + len(VIDEO_VARIANTS) + len(VCASES) + len(EDIT_VARIANTS)
    print(f"\n{total - bad}/{total} passed (fingerprints + {len(CASES)} cases + start video {len(VIDEO_VARIANTS)} variants, {len(VCASES)} cases)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
