# Encore's tests

```bash
python tests/run_tests.py                                   # unit tests (a few seconds)
H3_PLUGIN=/path/to/ComfyUI-H3-ClipPlan python tests/run_tests.py --e2e        # + end-to-end tests (~5 min)
H3_PLUGIN=... python tests/run_tests.py --e2e v25           # only the end-to-end tests whose name contains v25
```

The first line printed gives the versions tested: Encore's, and the plugin's when `H3_PLUGIN` is set.

## Unit tests (`unit/`) — need node

| Test | What it checks |
|---|---|
| `sections_test.js` | the Plan tab's prompt sections: parsing and writing back subjects, retention, summary, shots |
| `roundtrip_test.js` | opening a plan's prompts in the Plan tab and editing without change gives back the same text (otherwise the takes would be invalidated) |
| `sha_test.js` | the SHA-256 written in JS (used when the page is not in a secure context) gives node's digests |
| `parity_test.py` | the validity of the takes computed by the server (`encore/takes.py`) and by the page (`ui/plan_core.js`) is the same, and so are the fingerprints of the clips |

## End-to-end tests (`e2e/`) — Linux or WSL

Each test starts Encore's server on its own port with a project folder in `/tmp`, the fake ComfyUI of
`mock/` (port 8771) and a headless browser. Needs `pip install pillow numpy playwright`, then
`playwright install chromium` (or `CHROME=/path/to/chrome`), and the plugin folder in `H3_PLUGIN`: the fake
ComfyUI runs the plugin's real nodes (plan, takes, assembly) with a numpy stand-in for torch
(`mock/shim`) and fake models. `ffmpeg` must be on the PATH (`v30_test` reads a real video). Logs and screenshots: `e2e/out/`.

The tests are run in a fixed order (`run_tests.py`): some reuse the project made by the one before.
`v24_test`, `v25_test`, `v25_ui_test`, `v28_test`, `v29_test`, `v30_test` and `v31_test` check their results themselves (PASS / FAIL lines); the others are
mostly scenarios that must run through without error, page error or exception — their printed values are
for a human reader (`e2e/out/<test>.log`).

| Test | Scenario |
|---|---|
| `v20_test` | Plan tab: music video project, subjects, @ autocompletion, song passage |
| `v20b_test` | Plan tab on a free-mode plan (prompts untouched by viewing), tuned take dialog, filtered lists |
| `v21_test`, `v21b_test` | English interface: no French text left |
| `v22_test` | light theme |
| `v23_test` | ComfyUI busy with other work, targeted interrupt |
| `leaf_test`, `infos_test` | assembling from a take, assembled videos and their info sheets, checkpoints |
| `upscale_test` | latent upscale settings and the workflow sent to ComfyUI |
| `queue_ui_test` | queue: groups, moving, cancelling |
| `v24_test`, `v24_ui_test` | plan of a take, assembling invalidated takes, folding branches |
| `v25_test`, `v25_ui_test` | refusing other pages' requests, ComfyUI unreachable / restarted, buttons of an invalidated take, page opened by network address |
| `v28_test` | ≡ on « generate » boxes and queued generations with the « Generation » block, ▶▶ label, upscale settings of a take (folded form of ▾), LoRA-only column settings, version banner, no « null » in the windows |
| `v29_test` | folded branches: same width, no « selection » label, the selection moves to an unfolded branch, at least one branch stays unfolded |
| `v30_test` | start video: the project's video (plan settings), clip 1 continuing the segment (read and encoded), validity, assembly with and without the segment, plan settings without « null », timeline, start video column |
| `v31_test` | resources: big import piece by piece (progress window, cancel), no duplicate, deletion refused / with warning / direct |

`fixtures/` holds the plans, pictures, song and short videos the tests use (the plans `robot_*` are the
plugin's examples).

## README screenshots (`screenshots/`)

```bash
H3_PLUGIN=/path/to/ComfyUI-H3-ClipPlan CHROME=/path/to/chrome python tests/screenshots/make_screenshots.py
```

`render_videos.py` makes stand-in takes (the robot of the plugin's `examples/` moving on the beach or in the
workshop, with Pillow and ffmpeg) into `screenshots/out/videos/`; the fake ComfyUI uses them when `MOCK_VIDEOS`
gives their folder. `make_screenshots.py` then builds a project from `examples/robot_beach.plan.json` (three
branches, takes, an assembled video, two jobs waiting) and writes `docs/screenshots/*.png`.
