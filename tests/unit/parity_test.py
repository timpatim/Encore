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


def python_side():
    out = []
    for _name, local, selection, cur in CASES:
        r = takes.studio_resolve(PLAN, copy.deepcopy(local), dict(selection), cur)
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
    for (name, *_rest), py, j in zip(CASES, python_side(), js):
        if py != j:
            bad += 1; print(f"FAIL {name}\n  python {py}\n  js     {j}")
        else:
            states = sorted({s for c in py["clips"].values() for s in c["states"].values()})
            print(f"PASS {name} ({', '.join(states)})")
    print(f"\n{len(CASES) + 1 - bad}/{len(CASES) + 1} passed (fingerprints + {len(CASES)} cases)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
