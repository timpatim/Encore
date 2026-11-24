"""Chantier A, A2: when a new-scene take (✂) fits after another take of the clip before (plans.cut_fits).
A music video: the new scene must start at the same moment of the song; free mode: anywhere."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from encore import plan_core, plans  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def take(raw_start, frames, cont=False, pred=None):
    return {"frames": frames, "parent": None if not cont else pred,
            "studio": {"raw_start": raw_start, "predecessor": pred, "portion": {"clip": {"continue": cont}}}}


music = {"mode": "music", "context_frames": 39}
ctx = plan_core.snap_context(39, 121, 97)
t2a = take(82, 121)                       # clip 2 made after a clip 1: ends at 203
t2b = take(82, 121)                       # same length: ends at 203 too
t2c = take(82, 169)                       # longer: ends at 251
t3 = take(203 - ctx, 97, pred="2a")       # new scene timed after 2a

check("is_cut: a new scene", plans.is_cut(3, t3))
check("is_cut: a continuation is not", not plans.is_cut(3, take(0, 97, cont=True, pred="2a")))
check("is_cut: clip 1 is not", not plans.is_cut(1, take(0, 97)))
check("fits after its own take", plans.cut_fits(music, t3, t2a))
check("fits after a take of the same length", plans.cut_fits(music, t3, t2b))
check("does not fit after a longer take", not plans.cut_fits(music, t3, t2c))
check("free mode: fits anywhere", plans.cut_fits({"mode": "free"}, t3, t2c))
check("free mode with an edited video: the moment counts", not plans.cut_fits({"mode": "free", "edit_video": {"ref": "v"}}, t3, t2c))
check("a take without timing never fits (music)", not plans.cut_fits(music, {"frames": 97, "studio": {}}, t2a))

print("ERRORS:", fails)
