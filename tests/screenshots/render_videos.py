"""Fake takes for the README screenshots: the robot of the plugin examples (examples/robot.png, cut out) moving
on the beach or in the workshop (examples/beach.png, workshop.png). Writes out/videos/<scene>_<n>.mp4.
Needs H3_PLUGIN (the ComfyUI-H3-ClipPlan folder), Pillow and ffmpeg."""
import math, os, random, subprocess, sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
W, H, N = 960, 544, 72


def cut_robot(path):
    robot = Image.open(path).convert("RGB")
    mark = robot.copy(); w, h = mark.size
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (5, h // 2), (w - 6, h // 2), (w // 2, int(h * 0.78))]:
        ImageDraw.floodfill(mark, xy, (255, 0, 255), thresh=40)
    alpha = Image.new("L", (w, h), 255)
    mp, px = alpha.load(), mark.load()
    for y in range(h):
        for x in range(w):
            if px[x, y] == (255, 0, 255): mp[x, y] = 0
    out = robot.convert("RGBA"); out.putalpha(alpha)
    return out.crop(out.getbbox())


def main():
    examples = os.path.join(os.environ.get("H3_PLUGIN") or sys.exit("set H3_PLUGIN"), "examples")
    robot = cut_robot(os.path.join(examples, "robot.png"))
    os.makedirs(os.path.join(OUT, "videos"), exist_ok=True)
    for scene in ("beach", "workshop"):
        bg = Image.open(os.path.join(examples, scene + ".png")).convert("RGB")
        for k in range(5):
            dst = os.path.join(OUT, "videos", f"{scene}_{k}.mp4")
            if os.path.exists(dst): continue
            rnd = random.Random(f"{scene}{k}")
            scale, x0, dx = rnd.uniform(0.42, 0.6), rnd.uniform(0.12, 0.55), rnd.uniform(-0.12, 0.12)
            zoom0, dz = rnd.uniform(1.0, 1.08), rnd.uniform(0.02, 0.08)
            frames = os.path.join(OUT, "frames", f"{scene}{k}"); os.makedirs(frames, exist_ok=True)
            for f in range(N):
                t = f / (N - 1); z = zoom0 + dz * t
                bw, bh = int(W * z), int(H * z)
                fr = bg.resize((bw, bh)).crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))
                rh = int(H * scale * z); rb = robot.resize((int(robot.width * rh / robot.height), rh))
                fr.paste(rb, (int((x0 + dx * t) * W), int(H * 0.93 - rh + 6 * math.sin(t * math.pi * 4))), rb)
                fr.save(os.path.join(frames, f"{f:03d}.png"))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24", "-i", os.path.join(frames, "%03d.png"),
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", dst], check=True)


if __name__ == "__main__":
    main()
