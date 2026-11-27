# Encore's tests

```bash
python tests/run_tests.py                                   # unit tests (a few seconds)
python tests/run_tests.py --e2e                             # + end-to-end tests (~25 min)
python tests/run_tests.py --e2e v25                         # only the end-to-end tests whose name contains v25
```

The first line printed gives the version tested. Since 0.50 the tests no longer need the ComfyUI-H3-ClipPlan
plugin.

## Unit tests (`unit/`) — need node

| Test | What it checks |
|---|---|
| `sections_test.js` | the plan screen (plan v7): subjects a clip names, files in the order the server numbers them, file labels, renaming a subject, checks of the page |
| `parity_test.py` | the timing of a start video and the slices of an edited video are the same on the server (`encore/plan_core.py`) and in the page (`ui/plan_core.js`) |
| `cuts_test.py` | new scenes (✂) that fit after another take of the clip before |
| `latents_test.py` | 0.50: a take's latent written in MultiRef's `.safetensors` format; an old `.pt` of the plugin rewritten without torch (and refused when it holds anything else) |

## End-to-end tests (`e2e/`) — Linux or WSL

Each test starts Encore's server on its own port with a project folder in `/tmp`, the fake ComfyUI of
`mock/` (port 8771) and a headless browser. Needs `pip install pillow numpy playwright`, then
`playwright install chromium` (or `CHROME=/path/to/chrome`). The fake ComfyUI has fake models and fake nodes
(ComfyUI's own, MultiRef, VHS): each node checks what it gets like ComfyUI would, and writes outputs of the right
form (a `.safetensors` latent, a preview video); what the nodes received is kept for the tests. `ffmpeg` must be
on the PATH (Encore cuts the voices and the pieces of video with it, and assembles). Logs and screenshots: `e2e/out/`.

The tests are run in a fixed order (`run_tests.py`): some reuse the project made by the one before.
`v24_test`, `v25_test`, `v25_ui_test`, `v28_test`, `v29_test`, `v30_test` and `v31_test` check their results themselves (PASS / FAIL lines); the others are
mostly scenarios that must run through without error, page error or exception — their printed values are
for a human reader (`e2e/out/<test>.log`).

| Test | Scenario |
|---|---|
| `v20_test` | Plan screen: music video project, subjects, @ autocompletion, song passage |
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
| `a1_api_test`, `a1_ui_test` | plans of a branch and of each take, the plan of the selection, frozen clips |
| `a2_api_test`, `a2_ui_test` | the project's essence, branches (empty, from a file, duplicated with clips taken over), frozen settings |
| `a3_api_test`, `a3_ui_test` | deleting a take or a branch, the trash, « Use this plan… », choosing a generation still queued |
| `b1_api_test` | plan v7: the composed H3 prompt (numbers, definitions, anchors, speakers), a prompt written by hand, the subjects and files frozen in a take, ▶▶ during a generation, the state of the files and deleting the unused ones, deleting a project |
| `b2_ui_test` | plan screen v7: library, subject window, subjects of the clip, anchors, @ and / lists, « H3 prompt » tab and writing by hand, Resources window, deleting a project |
| `c1_ui_test` | 0.47: no columns mode, no Stop in the bar, ◎ to the generation running, branch name edited in place, scrolling down stops at the lowest take, the minimap filled by the graph, an assembly shown on the folded pane, assembled videos on a double click and looping, « Cancel all », the plan screen's own row |
| `d1_api_test` | 0.48: the master line (generated once, in order; no suite), the master plan frozen by the takes (clips, subjects, files; clips and subjects added), ▶▶ of a branch and of a selection, « New branch with this plan », a duplicated branch's line |
| `d2_ui_test` | 0.48: the master line on the takes screen (cells, row), ▶▶ of the branch and of the selection, the frozen master plan screen, « duplicate », « + new branch », « New branch with this plan… » |
| `e1_ui_test` | 0.48.2: pictures to supply (dashed box, picker, replace, « Images to supply »), import by drop from the computer, ↻ on a clip taken over, « Plan of the following clips », queue handle and « see the n jobs », minimap top, folded pane label |
| `f1_api_test` | 0.49: portions taken over in a duplicate (start of a scene), clips left free made by ▶▶ (lengths locked), the twig through them, assemblies |
| `f1_ui_test` | 0.49: the duplicate dialog (thumbnails by scene), the band (boxes of the clips left free), a clip left free editable in the master plan with its length locked (also in the launch panel) |
| `g1_setup_test` | 0.50: the installation screen without ComfyUI-H3-ClipPlan (MultiRef and VHS required with the nodes used, ComfyUI's own nodes, the ffmpeg found, an old plugin folder pointed out) |
| (0.50) | the rest: the whole suite runs on the new workflow (native nodes, MultiRef, VHS); `b1_api_test`, `v30_test` and `v37_test` check its nodes (pictures, start video, edited video) |
| `v31_test` | resources: big import piece by piece (progress window, cancel), no duplicate, deletion refused / with warning / direct |
| `v34_test` … `v40_test` | imported videos (light copies), the edited video (cut on the shots, common instruction, going on after the segment), assembling |

`fixtures/` holds the plans, pictures, song and short videos the tests use (the plans `robot_*` are those of
`examples/`).

## README screenshots (`screenshots/`)

```bash
CHROME=/path/to/chrome python tests/screenshots/make_screenshots.py
```

`render_videos.py` makes stand-in takes (the robot of `examples/` moving on the beach or in the
workshop, with Pillow and ffmpeg) into `screenshots/out/videos/`; the fake ComfyUI uses them when `MOCK_VIDEOS`
gives their folder. `make_screenshots.py` then builds a project from `examples/robot_beach.plan.json` (three
branches, the beach subject of « Workshop version » with the workshop picture, takes, an assembled video, two jobs waiting) and writes `docs/screenshots/*.png`.
