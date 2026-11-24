"""The plan is read twice: by Encore's server (encore/plan_core.py) and in the page (ui/plan_core.js). Both must give
the same fingerprints, the same timing with a start video and the same slices of an edited video. (Since 0.42 a take
never becomes invalid: the rules of validity that were checked here are gone.)"""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from encore import plan_core  # noqa: E402

RAW = json.load(open(os.path.join(ROOT, "tests", "fixtures", "rue_test_v1.plan.json"), encoding="utf-8"))
PLAN = plan_core.normalize(copy.deepcopy(RAW))
FP = {c["index"]: plan_core.take_fingerprint(PLAN, c["index"]) for c in PLAN["clips"]}


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




def main():
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
    total = 1 + len(VIDEO_VARIANTS) + len(EDIT_VARIANTS)
    print(f"\n{total - bad}/{total} passed (fingerprints + start video {len(VIDEO_VARIANTS)} variants + edited video {len(EDIT_VARIANTS)} variants)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
