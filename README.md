<p align="center">
  <img src="web/encore_icon.png" alt="Encore" width="128">
</p>

<h1 align="center">Encore</h1>

<p align="center">
  <b>A local studio for MiniMax H3 music videos and shorts, driven through ComfyUI.</b><br>
  Plans, branches, takes, a generation queue and assembly, in your browser.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: GPL v3" src="https://img.shields.io/badge/license-GPL--3.0-blue"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="Windows **Plan editor: clips over the song, prompts by section, references and checks**

![Plan editor](docs/screenshots/plan_editor.png)

**Plan window ≡ of a take: the plan it was made with and everything used to generate it**

![Plan window of a take](docs/screenshots/plan_window.png)

**« Tuned take » (▾): other LoRA, upscale settings or seed for one take**

![Tuned take dialog](docs/screenshots/tuned_take.png)

**Generation queue: reorder, suspend, pause, resume**

![Generation queue](docs/screenshots/queue.png)

*(Screenshots made with the robot example of the plugin; the takes there are stand-in animations,
not real H3 renders.)*

## Requirements

- **Windows** or **Linux** (Mac not supported for now), **Python 3.10** or newer.
- A working **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)** with MiniMax H3 support, on
  this PC or reachable on the network, and **git** (for the node packs).
- The node packs below; Encore's installation screen can install them for you:
  [ComfyUI-H3-ClipPlan](https://github.com/timpatim/ComfyUI-H3-ClipPlan) **3.6 or newer**,
  ComfyUI-H3-Motion-Context-MultiRef, ComfyUI-VideoHelperSuite; optional: ComfyUI-KJNodes
  (animated preview), the LBH latent upscaler nodes (upscale).
- The H3 models (diffusion model, text encoder, VAE, turbo LoRA): the installation screen downloads
  the default ones.

Encore itself only uses Python's standard library: nothing to `pip install`.

## Quick start

1. Get Encore: `git clone https://github.com/timpatim/Encore.git`, or **Code > Download ZIP** on
   GitHub and unzip it (anywhere, not inside ComfyUI).
2. Install and start it (details in [Installing Encore](#installing-encore)): on Windows,
   double-click `install.bat` then `Encore.bat`; on Linux, `./install.sh` then `./encore.sh`.
   Encore opens `http://127.0.0.1:8190` in your browser.
3. **Welcome screen**: give ComfyUI's address and folder, install the missing node packs, restart
   ComfyUI, download the default models.
4. **☰ Projects > New project**: a name, *free* mode (H3 makes picture and sound) or *music video*
   (a song is laid under the clips).
5. **Import a plan…**: a plan written by hand, by an LLM (the plugin gives the
   [system prompt](https://github.com/timpatim/ComfyUI-H3-ClipPlan/blob/main/docs/LLM_SYSTEM_PROMPT.md)
   for that) or one of the plugin's `examples/`. Or write it in the **Plan** tab.
6. **Resources…**: import the pictures (and the song or voices); then, in the **Takes** tab, the
   branch's **references…** button gives a picture to each reference of the plan.
7. **Takes** tab: click the box of clip 1 to generate a take, the box to its right for the next
   clip, or **▶▶ complete** to queue the whole branch. Click a take to choose it.
8. Hover the last take: **▶ assemble 1–k** makes the video; it shows up in the **▶ Videos** pane.

The rest of this page is the full user guide.

# User guide

*Encore was called « H3 Studio » up to its version 0.16.* ComfyUI's address is
`http://127.0.0.1:8188` by default.

Messages, confirmations and inputs open in an Encore window in the middle of the screen
(Enter confirms, Esc cancels; for a deletion or a restore, « No » has the focus). Only the warning
when closing the tab with an unsaved plan is still the browser's own.

## Language

Encore is in English by default. Home page > **Default settings…** > **Language**: the page reloads
in the chosen language, including the server's messages, the `.infos.md` sheets and the queue labels
(what was already written, such as a checkpoint name, stays as it is).

The texts are in `encore/locales/<code>.json` (`en.json`, `fr.json`): `{"id": "text"}`, with
`{name}` values filled in when shown. To add a language, copy `en.json` to `de.json` for example,
translate the texts and the `_name` key (the name shown in the list): it appears at the next start.
A text missing from a file is shown in English. H3 terms (`subject_definitions`, `fully_preserved`…)
and the content of the prompts are not translated.

## Light or dark theme

Dark by default. The **☀ / ☾** button of the top bar switches at once; the choice is also in
**Default settings… > Theme**, and it is kept in `config.json`. The video info pages follow it.
The light style sheet is derived from the dark one when the page is built (`encore/theme.py`).

## Installing Encore

Encore only uses Python's standard library: no package to download.

**With venv** (Python 3.10 or newer installed on the PC):

1. Get the `Encore` folder wherever you like (not inside ComfyUI): `git clone https://github.com/timpatim/Encore.git`,
   or download the ZIP from GitHub and unzip it.
2. Double-click `install.bat`: it creates the `.venv` environment in this folder.
3. Double-click `Encore.bat`: it starts Encore and opens `http://127.0.0.1:8190`.

**With conda**:

```text
conda env create -f environment.yml
conda activate encore
Encore.bat
```

**On Linux** (Python 3.10 or newer, with the venv module: `sudo apt install python3-venv`
on Debian/Ubuntu):

```bash
./install.sh     # creates .venv in the folder
./encore.sh      # starts Encore (or, with conda: conda activate encore, then ./encore.sh)
```

The Mac is not supported for now (you can try `python3 -m encore` from the folder, no guarantee).

Start options: `Encore.bat --port 8191` (or `./encore.sh --port 8191`), `--no-browser`.
The console window must stay open while you use it; Ctrl+C stops it.

**You had H3 Studio?** Unzip `Encore` next to the `H3Studio` folder (in the same parent folder):
at the first start, Encore takes over `config.json`, `defaults.json` and the queue (`queue.json`).
Projects do not move. (In ComfyUI, the working copy keeps its `h3studio_…` name.)

## First start: the « Welcome to Encore » screen

Encore goes no further until ComfyUI has everything it needs. The screen can be opened again
later with the **Installation…** button of the top bar (without blocking).

1. **ComfyUI**: its address, and its **installation folder** (the one that holds `custom_nodes`
   and `models`; for the portable version, the `ComfyUI_windows_portable` folder is enough).
   Encore finds **ComfyUI's Python**: `python_embeded` (portable version), `.venv` or `venv`
   (manual install, Desktop app). Otherwise, give the path of its `python.exe` (conda for
   example); « Check » runs it and makes sure torch is there. **git** is also needed (Git for
   Windows, git-scm.com).
2. **Custom nodes**: the packs Encore uses, with their state (loaded, installed but ComfyUI not
   restarted yet, missing, version too old). The required ones (ComfyUI-H3-ClipPlan,
   ComfyUI-H3-Motion-Context-MultiRef, ComfyUI-VideoHelperSuite) are checked from the start; the
   optional ones (ComfyUI-KJNodes for the animated preview, LBH nodes for the upscale) are checked
   as you like; a pack already in ComfyUI is checked and cannot be unchecked. Each name links to
   the pack's repository: **you can also install the packs yourself** (ComfyUI-Manager, git
   clone…), Encore detects them when ComfyUI restarts. **Install** does a `git clone` into
   `custom_nodes`, then installs the dependencies (`requirements.txt`) with ComfyUI's Python (`-s`
   for the portable version), without ComfyUI-Manager. The log shows below. A pack already present
   is recognized by its folder name or by the address of its git repository.
3. **Restart ComfyUI**: Encore does not restart it itself. It detects it going down and coming
   back, reads the node list again, and the **Continue** button turns on when all the required
   packs are loaded.
4. **Default models** (optional here): see below.

The pack list is in `encore/data/node_packs.json` (name, git repository, folder, expected nodes,
required or not): more can be added without touching the code.

## Default models: download

In the installation screen, and in the settings (**⬇ download the default model** button under
a model list when the default file is not in ComfyUI):

- ref2va pruned int8 diffusion model, Qwen3-VL 32B int8 text encoder, video and audio VAE, 8-step
  turbo LoRA (Hugging Face repository `Comfy-Org/MiniMax-H3`), and the LBH 3D upscale model
  (`LBH-123-AI/Minimax_h3_latent_Upscaler`);
- each file goes into its subfolder of `ComfyUI/models`;
- **before starting**, Encore reads the real size of the file on Hugging Face and compares it with
  the free space of the disk, with a 2 GB margin and counting the downloads in progress; when space
  is short, it refuses and gives the figures;
- progress, speed, cancel; an interrupted download resumes where it stopped (`.part` file);
- a protected repository needs a Hugging Face token (`hf_token` in `config.json`).

The list is in `encore/data/models.json`.

## Connection to ComfyUI

A permanent pill in the top bar: green « ComfyUI connected », orange « reconnecting… », red
« ComfyUI unreachable ». A click: address, version, since when, « Try again ». Generations started
during an outage wait in the queue. When ComfyUI comes back (after a restart), Encore reads the
node and model lists again.

## A project

```text
<projects folder>\<name>\
  project.json      settings: models, size, which file goes with which reference
  plan.json         the plan (plan.previous.json: the plan replaced by the last import)
  refs\images\      imported pictures
  refs\voices\      imported voices
  refs\songs\       imported songs
  takes\clip_NNN\   takes: latent (.pt), signature (.json), preview (.mp4)
  selection.json    chosen take of each clip
  jobs.json         waiting generations (only there while there are some)
  hidden_takes.json takes hidden by restoring a checkpoint (still on disk)
  checkpoints\      checkpoints
  exports\          assembled videos (.mp4) and their sheet (.json)
  store\            (reserved)
```

- **☰ Projects**: list, creation (name = folder name; free mode or music video).
- **Import a plan…**: copies a plan file into the project. The project name in the plan becomes
  the folder's.
- **Resources…**: imports pictures, voices and songs (copied into `refs\`). An identical file is
  not copied twice. Nothing is deleted (checkpoints need them). Accepted pictures: PNG, JPEG, WebP,
  BMP; the content is checked, and JPEG files named `.jfif`, `.jfi`, `.jpe`, `.pjpeg` or `.pjp`
  are saved as `.jpg` (same bytes).
- **Project settings…**: preview quality, models and sampling, live preview. Buttons « Save as
  default settings » and « Apply the default settings ».

## Plan tab

Three columns: the clip list, the clip editor, and on the right what the clip can use (references
with their thumbnails, subjects, lines or lyrics, stock sentences) and the checks. The plan
settings (mode, context, crossfade, seed, song, declared references) are in **⚙ Plan settings**.

- **@ and drag and drop**: in the sections, `<Subject N>` shows as `@name`. Typing `@` opens a
  filtered list (subjects, `{picture:…}`, lines or lyrics, stock sentences): arrows, Enter or Tab,
  Esc. The labels of the right column can be dragged into any text. H3 always receives
  `<Subject N>`: the numbers are recomputed when the prompt is written.
- **subject_definitions**: one block per subject (working name, references, definition); ↑ ↓
  renumber everywhere; renaming does not change the prompt (the name is kept in `_subjects`,
  ignored by the nodes and by the take checks).
- **retention_analysis**: one line per subject (mode in a list), added or removed with it. A
  section of another shape is edited as text.
- **summary**: the `[reference generation]` prefix is added automatically.
- **detailed_description**: style, then one block per `[Shot N]`. The required opening sentence
  (continuation, or lead-in of a new scene) follows how the clip is linked to the previous one, and
  changes with it. An opening sentence written by hand (plans made by an LLM) is kept.
- **« ↺ from the previous clip »** on the style, the overall_soundscape and the non_diegetic_music.
- **+ clip** takes over the references, subjects, retention_analysis, style and overall_soundscape
  of the selected clip; ▾ offers an empty clip.
- **Passage of the song** (music video): « ▶ whole passage » (overlap included) and « ▶ new part »,
  played from the branch's song; bars of the passage in the song and of the overlap. The clip
  lyrics are below.
- Thumbnails, voices (▶) and song come from the branch of the selection (else the first one).
- Showing a clip never changes its prompt: it is only written again for the section you edit.

Everywhere in the application, a drop-down list of at least 8 items (LoRA, models…) opens with a
filter field (several words allowed), arrows and Enter.

## Default settings

Home page > **Default settings…**: the language, the settings template (models, LoRA, sampling,
previews), and the picture size and reference size of the first branch. Each new project gets a
copy when it is created; they serve nothing else and do not change existing projects. Saved in
`defaults.json`, next to `config.json`. **LoRA**: a list (« + add a LoRA »); each LoRA has its
strength and a box to turn it off without removing it; they are applied one after the other. The
LoRA and models used are recorded in each take (visible in the larger preview); changing them
deletes no take. The model lists come from ComfyUI when it answers; otherwise names are typed by
hand.

- **Save** (Ctrl+S): saves the plan in the project.

## Branches

The picture size, the references (picture and voice of each name of the plan) and, for a music
video, the song are not project settings: they belong to **branches**. The size is chosen in the
« references… » screen of the branch: presets by format (16:9, 9:16, 4:3, 3:4, 3:2, 2:3) and
megapixels (0.2 to 2; 0.5 MP by default, that is 960 × 544 in 16:9; same sizes as ComfyUI,
1 MP = 1024 × 1024 pixels), or a free size in multiples of 32. A 0.2 MP branch lets you test a
prompt quickly before a 1 MP branch (the same seed does not give the same video at another size).
The same screen sets the **reference size** (`max` by default, or `match`), passed to the H3
reference encoder: it is no longer a field of the plan (`ref_image_size` is removed from the plan
on import or save; in an existing project, its value becomes the one of the branches already
made). A branch starts at clip 1 and keeps its set of references to the end; several branches let
you try other pictures, voices or versions of the track side by side.

- Empty Takes tab: **+ new branch**. The first one opens the screen of its references; the next
  ones copy those of the last branch made (« references… » button to change them). Making a branch
  starts no generation.
- Each branch is a horizontal band (tree or columns), with on the left its color, its name
  (double-click or « rename »), its pictures, its voices, its song (hover a thumbnail: the large
  picture).
- **delete** (branch header, not while the branch is generating): the takes of the branch listed
  by a checkpoint stay on disk, hidden (restoring the checkpoint brings the branch back); the
  others are deleted for good, after a warning that counts them. Its assembled videos leave the
  ▶ Videos panel (marked « branch removed » in « Assembled videos… ») and come back with the
  branch; they are only deleted when no checkpoint holds the branch any more. A branch number is
  never used again.
- When the automatic checkpoint limit removes one, the hidden takes no checkpoint lists any more
  are deleted (they could no longer come back).
- **generate**: clip 1 of a branch, and the first clip of each new scene (✂), when the branch does
  not have one yet.
- **« + clip k following » box**: to the right of each take that has no continuation yet (even a
  take still queued), a dotted box starts the next clip from this take. Its settings (▾ tuned:
  LoRA, upscale, seed) are those of the clip to make. No box when the next clip starts a new scene
  (✂), on the last clip, or after an invalidated take.
- **↻** (orange arrow on a take): a new take of the same clip, from the same take of the previous
  clip (not on clip 1: another version of clip 1 = a new branch).
- **▶▶ (branch header)**: fills every gap of the branch, in plan order: clips without a usable
  take, invalidated takes, and every clip that continues a redone clip. It starts from the
  selection when it is in this branch (else from the latest usable takes). Its label is always « ▶▶ complete »;
  its tooltip says what it will do (« generate all », « generate the clips 5 to 16 », « branch
  complete »); a summary
  (clips, reason, estimated time) asks for confirmation, with the box « assemble the branch at the
  end » (checked by default): the assembly of clips 1 to the end starts by itself after the
  generations. Random seeds, branch and clip settings. Refused while generations of the branch are
  already queued.
- **▶ assemble 1–k** also exists on hover of a take still queued: the assembly is planned and
  starts as soon as this generation (and those it depends on) are finished.
- The selection (click on a take, ✓) is used for the assembly (scenes before a cut ✂) and by the
  ▶▶ button. Choosing a take of another branch moves the selection there (`selection.json` records
  the branch).
- Changing the references or the song of a branch invalidates only its takes (same rules as
  below).

Projects of earlier versions are converted when opened: their takes make « Branch 1 », with the
size, references and song they had.

### Folding a branch

The ▾ arrow at the top left of a branch header folds it: the branch becomes a thin band (color,
name, number of takes, generations waiting, ▶▶ still available). ▸ or a double click unfolds it.
The folded branches are remembered per project in this browser; the overview map follows. Centering
the view on a take of a folded branch (« ⌖ takes ») unfolds it.
At least one branch always stays unfolded (the arrow of the last one is greyed out). A folded branch
never holds the selection: folding the branch of the selection moves it to an unfolded branch (the one
of the latest valid take of clip 1). The folded bands all have the same width, ▶▶ lined up on the
right.

## Generation queue (indicator on the right of the top bar)

Encore keeps its own queue, shared by all projects, and sends ComfyUI one job at a time. Each
generation or assembly is frozen at the time of the click (plan, settings, references, seed,
upscale) and sent when its turn comes. The queue survives an Encore restart.

- Groups: a job and those that continue it (« following » box or ↻ started on a waiting job).
  Their order is fixed; the whole group moves (drag ≡, or ⤒ ↑ ↓ ⤓).
- **Batches**: everything a branch ▶▶ starts (generations and final assembly) makes one block,
  « ▶▶ Branch 1: clips 3 to 16 + assembly ». It is moved, suspended or cancelled as a whole; above
  5 jobs, the list folds. A generation started after a job of the batch joins it; another
  generation goes after the batch (it can be moved up).
- **Planned assembly**: it waits until every generation it needs is finished, and takes their
  takes at that moment (the checkpoint is made when the assembly starts). If a generation fails,
  only the jobs that depend on it stop (its continuations, and the assembly: « clip 6 it depends
  on has failed »); clips of another scene go on. Starting ▶▶ again only redoes the gaps, assembly
  included.
- **Pause after the running job**: it finishes, nothing else starts.
- **Pause now**: the running job is interrupted and goes back to the top of the queue; it will
  start again from the beginning, with the same seed.
- **Suspend** a group: the queue skips it until « resume ».
- **Cancel**: a job, and those that depend on it (after confirmation). If a generation fails, those
  that depended on it are removed from the queue.
- The indicator, always visible on the right of the « Encore » bar, sums up the state at a glance:
  « Empty queue » (gray), « ▶ generating · project · clip · step 3/8 · ≈ … left · +n waiting »
  with a progress bar (green), « ⏸ Queue paused · n waiting » (orange), « ✖ failed » (red, until
  the manager is opened). A click opens it. The browser tab title shows the state too (« ▶ 3/8 ·
  … »), visible even from another tab.
- Each job shows the length of the clip to generate.
- ComfyUI can run work of its own: a job sent by Encore then waits behind it (« sent to ComfyUI,
  waits behind n job(s) of its own »), and the start estimates become a minimum (« start in … or
  more »). Cancel and « Pause now » only touch Encore's jobs: the interruption names Encore's job
  (recent ComfyUI versions interrupt nothing else).

## Latent upscale (optional, per branch)

**upscale…** button of the branch (« ⇧ upscale… » when it is on): first pass at a reduced size (in
megapixels, same proportions as the branch), latent upscale, second pass at the branch size. Off by
default.

- Pass 1: the first N steps of the settings schedule (scheduler, number of steps, SigmaShift), or a
  manual list of noise levels.
- Upscaler: LBH-123-AI 3D or 2D nodes (`Comfyui_Minimax_h3_latent_Upscaler` pack), or ComfyUI's node
  (MiniMax H3 Latent Upscale With Model); model in `models/latent_upscale_models`.
- Pass 2: manual list (default `0.9035, 0.8000, 0.6316, 0.3158, 0`, in 4 steps) or rest of the
  schedule; sampler and LoRA of pass 2 can be set apart (by default those of the settings).
- The seam with the previous clip and the song are put back as they are before pass 2 (ComfyUI's
  Separate/Concat AV Latent, Latent Cut, Replace Video Latent Frames nodes; plugin unchanged).
- Changing these settings invalidates no take; takes made with it carry the ⇧ mark (details on
  hover). A single take can use other settings, or none (see below).
- Time left is estimated separately for generations with upscale.

## LoRA and upscale per branch, per clip, per take

The LoRA stack of the Project settings always applies. « Extra » LoRA can be added:

- **Branch**: **LoRA…** button of the branch header. Added to every take of the branch. The
  branch's **Upscale…** button holds the upscale settings of its takes.
- **Clip**: ⚙ button of the column header (Takes tab), valid in every branch: clip LoRA and box
  « without the branch LoRA ». Kept by Encore under the clip's name: survives a plan re-import. The
  button shows L, L×2. A clip has no upscale settings of its own (since 0.28: the « with / without
  upscale » choice of older projects is ignored).
- **Take**: the **▾** arrow next to ↻, and « ▾ tuned » on the « generate » and « following » boxes,
  opens « tuned take »: the LoRA list, the upscale and the seed, for this take only. The upscale line
  is folded and says « like branch « X » » or « changed for this take »; **modify…** unfolds the
  full form (on/off, model, start size, passes…), started from the branch's settings; **reset to the
  branch's settings** goes back to them. From ↻ ▾ of a take, the window is pre-filled with that
  take's LoRA and upscale; elsewhere, with those of the branch and the clip.

Rules: branch and clip add up; for the same file, the clip's strength wins. The list of the ▾
window replaces branch + clip for the take. Upscale: the take's settings if it changed them, else
the branch's. A single click uses branch + clip (hovering the button says what will be used). A
continuation does not inherit the LoRA of the previous clip. These LoRA also apply to pass 2 of the
upscale. None of this invalidates a take: each thumbnail carries its badges (L, L×2: extra LoRA, ⇧:
upscale; details on hover), like the queue and the video info. « ⟲ redo » makes a take again with
the same LoRA and upscale as it had. The plugin is not modified: Encore adds the LoRA loaders to
the workflow it sends.

The plan window **≡** (on a take, a generation in progress, a placeholder or a column header) ends
with a **Generation** block: models, LoRA, upscale settings (and where they come from), seed, size,
reference image size and song — those used for a take, or those that would be used if launched now.

## Assembly

On hover, each take shows a **▶ assemble 1–k** button: it adds to the queue the assembly of clips 1
to k along this chain (earlier scenes, after a cut: takes of the selection if it is in the same
branch). The selection does not change. If a clip of the chain has no usable
take, the button becomes ⚠ (see below). Encore sends these takes to ComfyUI and runs the plugin's assembly node
(same result as in ComfyUI): the branch's song for a music video, the sound generated by the clips
in free mode, the branch size.

- The video is copied into `exports\`: `project_branch_YYYY-MM-DD_HHhMM.mp4`, with a sheet (branch,
  takes, clips covered).
- It appears in the « ▶ Videos » panel on the right of the Takes tab, under its branch name (hover:
  play and source takes highlighted; click: large; « ⌖ takes »: center the view).
- **Assembled videos…** (top bar) lists them all, with a player.
- Next to the video, `<name>.infos.md` (readable summary: table of the clips with start/end in the
  video, take, seed, size, model, LoRA, sampler, steps, upscale; then the details and prompt of
  each clip) and `<name>.infos.json` (all the details, plus a copy of the plan at the time of the
  assembly). « infos » button in the player and in « Assembled videos… »: a page in Encore's
  colors (summary, clip table with their length, one card per clip with its branch dot, prompts),
  with links to the .md and the .json. Videos assembled before v0.11 have none.
- Each assembly makes an automatic checkpoint whose selection is the assembled chain: « restore the
  state of this video » goes back to it.
- Each assembly has its own working copy in ComfyUI (purged at the end): several can be queued,
  even during generations; ComfyUI handles them in order. A copy of the video also stays in
  `ComfyUI\output\h3_clip_plan\h3studio_…\`.

### Assembling invalidated takes

On an invalidated take (or a chain that holds one) the button reads **⚠ ▶ assemble 1–k**: it
assembles the takes **really made**, following the real parents of the take (before a cut: the
selection when usable, otherwise the latest take of the branch). A confirmation lists the
invalidated takes and why. Encore sends ComfyUI a working copy of the plan rebuilt from the takes
(each clip with the length, link and prompt it was made with), so the plugin accepts them; your
plan and your takes do not change.

- Refused if the takes were not made at the same picture size.
- Warnings: a continuation whose take of the previous clip no longer exists (jump at the seam);
  for a music video, clip lengths changed since a take was made (its song passage is shifted, the
  singing will not match).
- The info sheet has an « Invalidated takes » section, the takes are marked ⚠ in its table, and the
  queue shows ⚠ next to such an assembly.
- ▶▶ is unchanged: it only fills with valid takes.

### Plan of a clip, plan of a take

- **≡** before the name of a clip (column header of the Takes tab): the clip as it is in the plan,
  read only (length, link, place in the video, references with their pictures in the branch shown,
  lyrics or lines, the prompt by section).
- **≡** on a « generate » or « following » box (on hover): the plan of the clip now, with the pictures
  of that branch — to read the prompt again before launching.
- **≡** on a generation still queued or running (on hover): the plan it was launched with, compared
  with the plan now (same window as for a take).
- **≡** at the top left of a take (on hover): the plan this take was made with, compared with the
  plan now: changed fields highlighted, prompt compared word by word per section (removed / added),
  reference pictures then and now (« another file now », « file modified since »), song passage
  shifted. Takes made since v0.24 record their plan; for older ones Encore looks for it by its
  fingerprint in the current plan, the previous imported plan, the checkpoints and the info sheets
  of the assembled videos (« plan not found » otherwise).

## Checkpoints

**Checkpoints…** button in the top bar.

- **create a checkpoint** (optional name): records the plan, the settings, the branches (size,
  references, song), the selection and the list of the takes present. Nothing is copied: takes and
  imported files are never changed or deleted.
- **restore**: puts the project back exactly as it was. An automatic checkpoint of the current
  state is made just before (« before restoring … »); the takes made since the restored checkpoint
  are hidden, and come back if that automatic checkpoint is restored. Refused while generations are
  waiting.
- Automatic checkpoints: before a restore, before a plan import and at each assembly. Their number
  per project is limited on the home page (0 = no limit); manual checkpoints are never removed.

## Generating (Takes tab)

Each take thumbnail shows the length of its clip (e.g. « 8.7 s »).

Navigation: the wheel scrolls up and down, Shift + wheel zooms (25 to 200 %) around the cursor;
dragging (on the background or a thumbnail) scrolls left / right, up to the edges of the graph; the
scroll bar scrolls up and down. « fit » fits the width of the graph to the window. The branch
column (left) and the row of clip names (top) always stay visible when scrolling; they follow the
zoom.

Overview (corner of the area, bottom right by default, ⚙ to change corner, ✕ to minimize): the
whole area (graph and empty part of the window) in miniature with a frame for the visible part;
clicking or dragging on it centers the view, the wheel zooms.

▶ Videos panel (on the right, when videos are assembled, foldable with ▸): the videos per branch,
the latest at the top; hover = play and source takes highlighted, click = player, « ⌖ takes »
centers the view on the last take of the video.

« + » or « generate » on a clip, ↻ for another version, the « following » box for the next clip
from a take, even a waiting one. Several generations can be started: progress bar on the running
one, ⏳ on the waiting ones, « cancel » button on each. A click chooses a take: the choice is saved
right away in the project (`selection.json`).

**Nothing is ever deleted.** A take is **invalidated** (yellow stripes, reason shown):

- when what it was made with no longer matches the project: picture or voice of a reference it
  uses, picture size, reference size, or its clip in the plan (prompt, length…). Putting the old
  value back makes it valid again;
- when a newer take has been made since with another value: then it is final, only a checkpoint
  can go back;
- when the take it continues is invalidated.

Changing a reference or the size asks for confirmation and gives the takes that will be
invalidated; it is refused while generations are waiting. On an invalidated take, **⟲ redo** makes
a new take of this clip only, with the same seed; for a continuation, from the chosen (or waiting)
take of the previous clip. To redo at once everything that depends on it: the branch ▶▶ button.

**Seeds**: each take shows its full seed, selectable. Another value + Enter (or ↵) starts a new take
of this clip with this seed (same starting take for a continuation, same branch). The « generate »
buttons have an optional seed field (empty = the plan's seed for the first take, else random).

**Time left**: running thumbnails show « ≈ … left », waiting ones « start ≈ … ». The estimates come
from the pace of the steps of the running generation and from the length of earlier generations
(kept in `timings.json`, next to `config.json`, in proportion to the size and the number of
frames): they get better over time.

What Encore does for each generation:

1. it saves the plan if it was changed;
2. it sends ComfyUI the plan (`input\h3studio\<project>\<branch>\plan.json`), the reference files
   (same folder, named after their content; the song: `input\h3studio_<project>_…`) and, for a
   continuation, the continued take with those it is built on;
3. it builds the workflow with the plugin's nodes and puts it in ComfyUI's queue;
4. it follows the generation and, once finished, copies the take (latent, signature, preview) into
   the project's `takes\` and chooses it.

On ComfyUI's side, the working copy is `output\h3_clip_plan\h3studio_<project>__<branch>\` (one per
branch): the prefix avoids any mix with your plans used directly in ComfyUI. When no generation of
the project is waiting any more, Encore empties it (option on the home page).

**Live preview** (Project settings… > Live preview): the thumbnail of the running generation shows
the preview received at each step; double-click to enlarge it.

- **ComfyUI** (default): one picture per step, as set by ComfyUI's « Live preview method ».
- **KJNodes – Model Preview Override** (ComfyUI-KJNodes pack): Encore adds this node to the
  workflow. With a TAE decoder (`models/vae_approx`, for example `taeh3`), true colors;
  « animated frames » at -1 (default): a small video of the whole clip at each step, with the
  generated sound if « sound » is checked (audible on hover with « sound on hover »).

**Diagnostics** (off by default): with `"diagnostic_preview": true` in `config.json`, Encore writes
what ComfyUI sends during generations to `diagnostic_apercu.log` (next to `Encore.bat`) and keeps
the first 20 previews in `diagnostic_apercu\`.

If Encore is closed while ComfyUI generates, the takes are collected when it opens again, once the
project is open.

Encore only listens on `127.0.0.1`: it cannot be reached from the network. It also refuses what
another web page open in your browser could send it: a request from another site, or from a site
whose name points to your PC, gets « request refused ». To open Encore from another device of your
network, start it with `--host 0.0.0.0` (only on a network you trust: anyone on it can then use it).

If ComfyUI stops answering while jobs are running there (restart, crash), the jobs it lost go back
to Encore's queue and are sent again when it answers (twice at most); what Encore had sent it
(pictures, voices, takes) is sent again too. Changing ComfyUI's address does the same.

## Development

- `encore/`: the server (Python standard library only). `encore/locales/`: one file per language.
- `ui/`: the sources of the page (JavaScript, `editor_shell.html`). After a change, rebuild the page with
  `python ui/build.py`, which writes `web/index.html` (the translations and the light theme are put in it).
- `tests/`: unit and end-to-end tests, with a fake ComfyUI that runs the plugin's real nodes; see
  [tests/README.md](tests/README.md).
- `tests/screenshots/make_screenshots.py`: makes the screenshots of this page (`docs/screenshots/`) with the fake
  ComfyUI and the robot example of the plugin.
- [CHANGELOG.md](CHANGELOG.md): what changed in each version.

## License

GPL-3.0 (see [LICENSE](LICENSE)), like the [ComfyUI-H3-ClipPlan](https://github.com/timpatim/ComfyUI-H3-ClipPlan) plugin.
