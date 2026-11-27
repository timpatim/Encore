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
  <img alt="Windows, Linux" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey">
  <a href="README.fr.md"><img alt="Français" src="https://img.shields.io/badge/lire%20en-fran%C3%A7ais-informational"></a>
</p>

> **Disclaimer: this project is entirely vibe-coded.** All of its code, documentation and tests were
> written by an AI assistant (Claude, by Anthropic), following the author's requests. The author
> specified the features and tested the result in use, but neither wrote nor reviewed any of the
> code. Read it, test it on your own setup and use it at your own risk; issues and corrections are
> welcome.

![Takes screen: branches, takes and the assembled video](docs/screenshots/takes.png)

## What Encore does

[MiniMax H3](https://huggingface.co/Comfy-Org/MiniMax-H3) makes clips of about ten seconds, with
picture and sound, from reference images. A music video or a short is a series of such clips that
follow one another. Encore describes that series in a **plan** (a JSON file: the subjects and files, one
clip after another, which clip continues which, the song; format in [docs/PLAN_SPEC.md](docs/PLAN_SPEC.md))
and is the application around it. ComfyUI does all the inference: Encore composes the prompts, prepares
the files and sends ComfyUI workflows made of its own nodes and those of two node packs (see
[Requirements](#requirements)). What it offers:

- **Plan editor**: clips on a timeline over the song; subjects (a character, a place, an object…) with
  their pictures and voice, named `@name` in plain fields; Encore writes the prompt in MiniMax's own form
  (numbers, definitions, retention, task) and shows it, editable; checks of the plan and of each clip.
- **Takes as a tree**: every generation is a take; a continuation is built on the exact take it
  follows. Try several takes, keep the best chain (a *twig*), go back to an earlier one. Each twig has
  its own plan: the clips already generated are frozen, the next ones can be rewritten.
- **Branches**: the same plan with other pictures, another size, other LoRA or upscale settings,
  side by side, without mixing their takes.
- **Generation queue**: runs one job at a time in ComfyUI, survives a restart of ComfyUI or of
  Encore, can be reordered, paused and resumed; **▶▶ complete** fills a whole branch.
- **Latent upscale** (optional): generate small, then upscale in a second pass.
- **Assembly**: one click puts the chosen takes end to end on the song into a video.
- **Plan windows** that say exactly how a take was made, an installation
  screen that installs the node packs and downloads the models, English and French, dark and
  light themes.

ComfyUI is only the engine: Encore talks to it at its address and never changes its workflows.

## Screenshots

**Plan editor: the master plan of a branch with takes, its clips frozen (🔒, made by the master line), the fields of clip 2, the subjects and files on the right**

![Plan editor](docs/screenshots/plan_editor.png)

**The same clip, « H3 prompt » tab: what MiniMax H3 gets, composed from the fields, with its numbers**

![H3 prompt](docs/screenshots/plan_h3.png)

**Launch panel: a new take of clip 2, over the takes; which twig's plan to start from, the clip, the seed**

![Launch panel](docs/screenshots/launch.png)

**Plan window ≡ of a take: the plan it was made with and everything used to generate it**

![Plan window of a take](docs/screenshots/plan_window.png)

**Generation queue: reorder, suspend, pause, resume**

![Generation queue](docs/screenshots/queue.png)

*(Screenshots made with the robot example of the `examples/` folder; the takes there are stand-in
animations, not real H3 renders.)*

## Requirements

- **Windows** or **Linux** (Mac not supported for now), **Python 3.10** or newer.
- A working **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)** with MiniMax H3 support, on
  this PC or reachable on the network, and **git** (for the node packs).
- The node packs below; Encore's installation screen can install them for you:
  [ComfyUI-H3-Motion-Context-MultiRef](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef)
  (takes kept to be continued, seams, song, videos) and
  [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) (videos);
  optional: ComfyUI-KJNodes (animated preview), the LBH latent upscaler nodes (upscale). Since 0.50 Encore
  no longer uses ComfyUI-H3-ClipPlan.
- **ffmpeg**, found by Encore (the one of VideoHelperSuite in ComfyUI's Python, or on the PATH): it cuts the
  voices and the pieces of video it sends, and assembles the videos.
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
5. **master plan…** (branch header), then **Import a plan…**: a plan written by hand, by an LLM (with the
   [system prompt](docs/LLM_SYSTEM_PROMPT.md) of `docs/`) or one of the `examples/`. Or write it there.
6. **Resources…**: import the pictures (and the song or voices); the song is chosen in **Project
   settings**. On the plan screen, give each subject of the plan its pictures (✎ on the subject, or drop
   a picture of the « Files of the project » onto it).
7. On the takes screen: the top row of the branch is its **master line**, one box per clip of the master
   plan; click the first one to generate it, or **▶▶ complete** to queue the whole line. **↻ new take…**
   and **+ next clip…** make variants of it. Click a take to choose it.
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
(what was already written, such as a branch name, stays as it is).

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
Projects do not move.

## First start: the « Welcome to Encore » screen

Encore goes no further until ComfyUI has everything it needs. The screen can be opened again
later with the **Installation…** button of the top bar (without blocking).

1. **ComfyUI**: its address, and its **installation folder** (the one that holds `custom_nodes`
   and `models`; for the portable version, the `ComfyUI_windows_portable` folder is enough).
   Encore finds **ComfyUI's Python**: `python_embeded` (portable version), `.venv` or `venv`
   (manual install, Desktop app). Otherwise, give the path of its `python.exe` (conda for
   example); « Check » runs it and makes sure torch is there. **git** is also needed (Git for
   Windows, git-scm.com). The screen also shows the **ffmpeg** Encore found (to cut the voices and
   pieces of video it sends, and to assemble): the one VideoHelperSuite brings in ComfyUI's Python, or
   the one on the PATH.
2. **Custom nodes**: the packs Encore uses, with their state (loaded, installed but ComfyUI not
   restarted yet, missing). The required ones (ComfyUI-H3-Motion-Context-MultiRef,
   ComfyUI-VideoHelperSuite) are checked from the start; the
   optional ones (ComfyUI-KJNodes for the animated preview, LBH nodes for the upscale) are checked
   as you like; a pack already in ComfyUI is checked and cannot be unchecked. Each name links to
   the pack's repository: **you can also install the packs yourself** (ComfyUI-Manager, git
   clone…), Encore detects them when ComfyUI restarts. **Install** does a `git clone` into
   `custom_nodes`, then installs the dependencies (`requirements.txt`) with ComfyUI's Python (`-s`
   for the portable version), without ComfyUI-Manager. The log shows below. A pack already present
   is recognized by its folder name or by the address of its git repository. A
   ComfyUI-H3-ClipPlan folder still in `custom_nodes` is pointed out: Encore no longer uses it since
   0.50 (keep it if you use it directly in ComfyUI).
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
  project.json      settings: what the video is (mode, video, song, context), models, branches
  plans.json        the master plan of each branch and the plan of what follows each take
  refs\images\      imported pictures
  refs\voices\      imported voices
  refs\songs\       imported songs
  refs\videos\      imported videos (start or edited video)
  takes\clip_NNN\   takes: latent (.pt), signature (.json), preview (.mp4)
  selection.json    the selected twig (chosen take of clips 1 to k, each continuing the one before)
  jobs.json         waiting generations (only there while there are some)
  exports\          assembled videos (.mp4) and their sheet (.json)
  trash\            what was deleted, until restored or erased (Trash…)
  store\            (reserved)
```

- **☰ Projects**: list, creation (name = folder name; free mode or music video). **🗑** on a project
  card deletes it **for good** (no trash): the confirmation counts its takes, assembled videos and size
  on the disk; its copies in ComfyUI's `input` and `output` folders go too. Refused while one of its
  generations or assemblies is waiting or running.
- **Import a plan…** (on the master plan screen of a branch): the file replaces the master plan of a
  branch that has no take yet; greyed once the branch has takes (make a new branch « from a plan file »).
  The seeds of the file are ignored. While the project has no take, the plan's mode, video and context
  become the project's.
- **Resources…**: imports pictures, voices, songs and videos (copied into `refs\`), with its buttons or
  by dropping files from the computer (an audio file goes to the section it is dropped on, otherwise Encore
  asks voices or songs); files can also be dropped on « Files of the project » in the library. A big file shows a
  progress window (cancel leaves nothing behind); it is written as it arrives. When ComfyUI's folder is known
  (welcome screen), files are later copied straight into its `input` folder, with no size limit;
  otherwise they go through ComfyUI's upload route, which refuses files over 100 MB unless ComfyUI is
  started with `--max-upload-size` (the queue shows « sending … to ComfyUI »). A video the browser
  cannot play (AVI, ProRes, HEVC…) gets a light H.264 copy for the players only, made by ffmpeg (the
  one of ComfyUI's Python, or on the PATH) with its progress; ComfyUI always gets the original. Each file
  shows its state: **used** (by a plan, the song or the video of the project, or a generation waiting),
  **takes only** (only takes already made used it) or **unused**. 🗑 deletes a file: refused while
  a plan, the song, the video or a waiting generation uses it (the message says where), after a warning
  listing the takes that still need it, at once otherwise. **Delete the unused files** removes all the
  unused ones at once, after confirmation. Their copy in ComfyUI goes too when ComfyUI's folder is known. An identical file is
  not copied twice. Accepted pictures: PNG, JPEG, WebP,
  BMP; the content is checked, and JPEG files named `.jfif`, `.jfi`, `.jpe`, `.pjpeg` or `.pjp`
  are saved as `.jpg` (same bytes).
- **Project settings…**: first **the project**: mode (music video or free), video (none, continue a
  video, edit a video) and its file, song (music video), context. They are the same for every branch and
  are fixed by the first take of the project (greyed, with the reason). Then preview quality, models and
  sampling, live preview. Buttons « Save as default settings » and « Apply the default settings ».

## Takes screen and plan screen

The **takes screen** is the main screen: branches, takes, queue, assembled videos. The plan is edited
on the **plan screen**, opened from it, which replaces it until **← Takes** (the plan is saved on the
way back if it was changed). The plan screen has a row of its own under the project's: **← Takes**, what
it shows (● when changes are not saved), **⚙ Plan settings**, then **↶ Undo**, **↷ Redo** and **Save the
plan**, which act on the plan shown. The project's buttons (Resources, Trash, Assembled videos, Project
settings) stay in the row above:

- **master plan…** (branch header): the starting pattern of the branch; its master line follows it.
  **Once the branch has a take** (or a generation waiting), **it is frozen**: its clips are read only
  (🔒, with the take of the master line that made them) and so are its subjects (🔒 in the library: their
  window shows them without « Save »), with the files they use. Clips can still be added at the end
  (they stay free until the master line generates them) and new subjects for them. To change the rest,
  duplicate the branch (without its clips: the copy's master plan is free).
- **Plan of the selection…** (selection bar, above the graph): the plan of the selected twig. The
  clips already generated in it show 🔒 and are read only (their prompt is the one the take was made
  with); clips can be added, changed or removed after them. The changes stay in this twig: the
  master plan and the other twigs do not change. **New branch with this plan…** makes it the master plan
  of a new branch with the settings of this one (nothing taken over): to try prompts that work elsewhere.
  A master plan is never replaced once its branch has takes.

**Plans of a branch.** A branch has a master plan and a **master line**: the takes made from the master
plan itself, one per clip, in a row at the top of its band (« master plan » tag), followed by empty boxes
for the clips not generated yet. A box of the line is generated once, in order (the first empty one is
clicked, or ▶▶): a change is made with **↻ new take…**, which makes a fork. After a take of the line comes
the master plan itself. Each other take has the plan of what comes after it (its *suite*): a new take of
clip k records the clips k+1 to the end it was launched with. The plan of a
twig is the frozen part of each of its takes, then the suite of its last take. Nothing is copied: a
fork references the takes it continues. Once a branch has a take, the plan settings that would make
its takes inconsistent (mode, start or edited video, context) are frozen; assembly options (start
video in the final video, sound and common instruction of an edit) are not.

Three columns: the clip list, the clip editor, and on the right the library (subjects of the plan,
files of the project, stock sentences) and the checks. The plan settings (mode, context, crossfade,
song, video) are in **⚙ Plan settings**.

**Subjects and files.** A plan has **subjects**: a character, a place, an object, an outfit, a style, an
action or a pose. Each one has a name (`@robot`), a kind, a description in English, as many pictures as
needed (each with what it gives: face, outfit, scene…; one picture can serve several subjects) and, in
free mode, a voice. **+ subject** or ✎ opens its window; a picture of « Files of the project », or a file
from the computer, can be dropped onto it; clicking a picture's thumbnail replaces it (its role kept), from
the project's images or imported directly. The files are those of the project (**Resources…**); the plan
names them by a label made automatically from the file name.

**Pictures to supply.** A plan imported with labels but no files (written elsewhere, for instance) shows
each missing picture as a dashed box with its label and note, and lists them in the library section
« Images to supply ». Choosing or importing (or dropping) an image fills the label: its name, note and role
are kept, so the clips that use it stay right.

**The fields of a clip** (« Fields » tab): plain text, the subjects named `@name`.

- **Anchors**: the picture the clip starts from (first frame; not on a clip that continues the previous
  one), keyframes at a given second, the picture it ends on (last frame). Choose a file in the list or
  drop one from the library.
- **Summary**: what the clip shows. **Shots**: the style, then `[Shot 1] …`, `[Shot 2] At 00:04.000 …`.
  **Sound** and **Music**: the ambience, the music (in a music video, the section of the song).
- **@ and drag and drop**: typing `@` opens a filtered list (subjects, lines or lyrics, stock
  sentences, « create @name »): arrows, Enter or Tab, Esc. A subject can be dragged into any text.
- **/ for the camera**: typing `/` in a text opens MiniMax's camera vocabulary: moves (push in, pan,
  tilt, arc, tracking…) followed by their amplitude and speed, cuts to a new shot, framings (close-up,
  wide shot, over the shoulder…). The sentence is written in English where the caret is.
- **Lines** (free mode): `@name says: <d>[French] …</d>`. The speaker of each line is found
  automatically: the subject named in its sentence, or the one of the clip's dialogue whose text matches.
  Speakers are numbered S1, S2… in the order they speak; write `@name (S)` only to choose another speaker.
- **Subjects of the clip**: the subjects its texts name, each with how closely the clip keeps its
  pictures (identical, partial, the attribute only, loose inspiration), how closely it keeps its voice,
  and a note for this clip only (« wears a cap »). A counter shows the pictures, voices and files used
  against H3's limits (9 pictures, 3 voices, 12 files).

**The « H3 prompt » tab** shows what MiniMax H3 will get, composed by Encore from the fields: subjects
numbered `<Subject N>` in the order they appear, pictures `<Picture N>`, voices `<Audio N>`, the
definitions, the retention of each subject, the task prefix (`[video continuation + reference
generation]`…) and the required opening sentence of a continuation or a new scene. The chips above it
give each number. The text can be **changed by hand**: it is then sent as it is (✎ on the tab) and the
fields no longer change it; « Back to the composed prompt » undoes that. In a text written by hand,
`@name` still works and gets its number.

- **« ↺ from the previous clip »** on the style, the sound and the music.
- **+ clip** takes over the subjects and the texts of the selected clip; ▾ offers an empty clip.
- **Passage of the song** (music video): « ▶ whole passage » (overlap included) and « ▶ new part »,
  played from the branch's song; bars of the passage in the song and of the overlap. The clip
  lyrics are below.
- A clip already generated (🔒, plan of a selection) keeps the subjects and files it was made with,
  even if the plan changes them afterwards.

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

- **Save** (Ctrl+S, plan screen): saves the plan shown (master plan or plan of the selection).
- **↶ ↷** (Ctrl+Z / Ctrl+Y): undo and redo the changes of the plan, on the plan screen and in the launch
  panel only (on the takes screen, they do nothing).

## Branches

A project says what the video is (mode, video, song, context: **Project settings**). **Branches** try
variations of it: picture size, segment of the video, LoRA, upscale, and its master plan (subjects with
their pictures and voices, prompts). They are set in the **settings…** window of the branch (one button in its
header). The size: presets by format (16:9, 9:16, 4:3, 3:4, 3:2, 2:3) and
megapixels (0.2 to 2; 0.5 MP by default, that is 960 × 544 in 16:9; same sizes as ComfyUI,
1 MP = 1024 × 1024 pixels), or a free size in multiples of 32. A 0.2 MP branch lets you test a
prompt quickly before a 1 MP branch (the same seed does not give the same video at another size).
The same screen sets the **reference size** (`max` by default, or `match`), passed to the H3
reference encoder: it is no longer a field of the plan (`ref_image_size` is removed from the plan
on import or save). Several branches let you try other pictures, voices or sizes side by side: give
the subjects of each branch's master plan other pictures. **Once a branch has a take, its size and the
segment of its video are frozen**: greyed in the windows, with a tooltip saying why. To try other values,
duplicate the branch. LoRA, upscale and reference size can always change. The takes keep the subjects
and files they were made with.

- A new project has « Branch 1 », with an empty master plan. **+ new branch** opens a window:
  - **Empty**: settings and master plan of the last branch made;
  - **From a plan file…**: its master plan is the file.
- **duplicate** (branch header): a new branch with its settings and master plan, **without clips** (its
  master plan can change again until its first take), or **with clips of the selection**: the dialog shows
  the selection as small thumbnails, scene by scene (✂ between them). The clips taken over form **portions**,
  each from the start of a scene: clicking a clip takes it over with its scene from its start, clicking a clip
  taken over leaves it free with the rest of its scene (a clip that continues another one is never taken over
  without it). For 1→2→3 | 4→5→6 | 7→8→9: 1→2→3 and 7→8→9, or 1→2, 4→5 and 7→8, or 1, 4→5 and 7.
  They are taken over by
  reference (no file is copied), shown dimmed in the new band (« ⇡ Branch 1 »), and its master line makes the
  clips left free: an empty box for each, the clips taken over after it hang on it. The clips left free start
  from the plan of the selection and stay editable in the master plan (until the master line freezes them);
  their length and link are locked, in the master plan and in the launch panel, so the portions after them
  stay at their moment of the song; a clip taken over after a clip left free waits
  for it (its ↻ and + are greyed). Its master plan is the plan of that selection, with its subjects; the clips taken
  over keep the subjects and files they were made with; ↻ new take… and + next clip… work on them, the new
  take being a variant of the duplicated branch (the branch it comes from does not change). A branch whose
  takes are taken over by another one cannot be deleted before it.
  Making a branch starts no generation.
- Each branch is a horizontal band (a tree), with on the left its color, its name (a field: type the
  new name, Enter or a click elsewhere saves it, Esc gives the old one back), its size and its song.
- **delete** (branch header, not while the branch is generating): moves its takes, its plans and its
  assembled videos to the trash, after a warning that counts them. The takes another branch takes over
  stay (shown in that branch). A branch number is never used again.
- **🗑** (on hover of a take): deletes it with every take made after it, in any branch; the confirmation
  lists them by clip and says what a branch that took it over keeps. Refused while a generation queued or
  running needs one of them.
- **Trash…** (project bar): what was deleted waits there. **Restore** puts an item back whole (a take
  with what followed it, a branch with its takes, master plan and videos, the clips other branches took
  over); **Erase** or **Empty the trash** deletes the files for good.
- **The boxes of the master line**: the first empty one (▶) opens the launch panel for that clip of the
  master plan, shown read only (seed, LoRA and upscale can be set); the next ones wait for it.
- **+ next clip…** (on a take that has no continuation yet, even a take still queued, and in the
  dotted box to its right, always there, even after the end of the plan): opens the launch panel for
  the next clip after this take, pre-filled with the next clip of the selection's plan, else of the
  master plan, else a copy of the clip before (texts, length, subjects, lines), continuing it (↪).
- **↻ new take…** (orange arrow on a take, also on a generation still queued or running): opens the
  launch panel for a new take of the same clip, after the same take of the previous clip (on clip 1:
  from the master plan). It makes a fork: a new twig, with its own plan.
- **▶▶ complete (branch header)**: fills the empty boxes of the branch's master line, in order.
  **▶▶ complete the selection** (selection bar): generates the rest of the selected twig's plan, after
  its last take (the selection ending the master line is the master line). Their tooltip says what they
  will do (« generate the clips 5 to 16 », « master line complete »); a summary (clips, estimated time) asks for
  confirmation, with the box « assemble at the end » (checked by default). Random seeds, branch
  settings. Generations of the branch already queued or running do not block it: the twig goes through
  them and the rest is queued after them.
- **▶ assemble 1–k** also exists on hover of a take still queued: the assembly is planned and
  starts as soon as this generation (and those it depends on) are finished.
- **The selection** (click on a take) is a twig: the take clicked and the takes it continues, back
  to clip 1. Takes after it that still continue it stay selected. The selection bar above the graph
  names it and opens its plan. Choosing a take of another branch moves the selection there. A
  generation still queued or running can be chosen too: the selection goes through the take it will
  make.
- **New scenes (✂) follow the selection.** A take that starts a new scene does not depend on the
  pictures before it: it hangs on the take selected for the clip before when it starts there at the same
  moment of the song (same length before it; in free mode, always), and its continuation goes with it.
  Example: 3a ✂ made after 2a (5 s); choose 2b (5 s too): 3a moves under 2b, and 1 → 2b → 3a is a twig,
  with nothing to generate again.

### Launch panel

**↻ new take…** and **+ next clip…** open the same panel, over the takes screen:

- **Plan of the following clips**: when twigs going through this take have different plans for the clips
  after it, one choice per distinct plan: « This take · the plan it was made with » first, then each other
  plan with the twig's takes as thumbnails (the new take dashed) and a yellow tag of what changes
  (« clip 3 changed »). Hovering a choice highlights its twig in the graph; « Read the chosen plan in full ▸ »
  shows it. Hidden when every twig keeps the same plan.
- **Seed**: drawn at random (🎲 for another one), a new take too; « ↺ seed of the take redone » puts
  its seed back (same seed and same prompt: Encore warns that the take will be identical).
- **LoRA and upscale** of this take (pre-filled with those of the take redone, or of the branch for
  the next clip).
- **The clip**, in the plan editor: change its prompt before launching. Only this clip and the
  ones after it can change; the change is kept in the plan of the new take.
- **Generate** adds it to the queue.

Typing another seed in the seed field of a take + Enter launches a new take of this clip at once,
with this seed and the same settings.

### Folding a branch

The ▾ arrow at the top left of a branch header folds it: the branch becomes a thin band (color,
name, number of takes, generations waiting; no ▶▶). ▸ or a double click unfolds it.
The folded branches are remembered per project in this browser; the overview map follows. Centering
the view on a take of a folded branch (« ⌖ takes ») unfolds it.
At least one branch always stays unfolded (the arrow of the last one is greyed out). A folded branch
never holds the selection: folding the branch of the selection moves it to the first twig (the top
line of the tree) of the first unfolded branch. The folded bands all have the same width.

## Starting from an existing video

A plan can start from a segment of a video you already have: clip 1 continues it (same shot: its
last 1.6 s are taken over, picture and, in free mode, sound) or cuts after it.

1. In **Project settings**: video « Continue a video », and its file (the project's imported videos, or
   **Import…**). One video for the project: every branch uses it.
2. In **⚙ Plan settings > Video** of a branch's master plan, choose the segment in the player:
   « Segment from … to … », or « ⇤ here » / « here ⇥ » at the player's position; « ▶ play the segment » plays it. The segment is snapped onto the frame grid:
   its end is kept, its start moves forward by less than 0.7 s (the line below says what is used).
3. « clip 1 continues the video » or « cut after the video », and whether **the segment opens the
   final video** (otherwise it is only a springboard: the video starts with clip 1).
4. Music video, segment in the final video: **the song starts with the video** (default; the video
   loses its own sound and clip 1 comes later in the song) or **the video keeps its own sound and
   the song starts with clip 1**.

The segment shows on the plan screen's timeline before clip 1 (hatched when it is not in the final
video). When it opens the final video, the takes screen has a **Start video** column before clip 1:
the segment of each branch, linked to the takes of clip 1 that continue it (hover: plays it; click:
its settings, on the plan screen). It is not a take: it is neither generated nor chosen. The video is
read at 24 fps, resized to cover the branch's picture size and cropped in the middle. The file can only
be changed while the project has no take; the segment of a branch while it has none. Whether the segment is in the
final video changes nothing in free mode (in a music video it moves the song under the clips).

## Editing an existing video

A free-mode plan can edit a segment of a video you have: change its style, replace a character by a
reference picture, and so on. The timeline of the plan is the segment; each clip edits its own slice
of it, given to H3 as `<Video 1>` with its sound (the voices of the clip come after it, Encore numbers
them). In **Project settings**, choose video « Edit a video » and its file; then in **⚙ Plan settings >
Video** of a branch's master plan:

1. Choose the segment, as for a start video.
   The branches should have the proportions of the video, otherwise its picture is cropped: Encore
   says so and **gives them the video's proportions** on request (about the same number of pixels).
2. The sound of the final video: **the original sound of the segment** (default) or **the sound H3
   made** (to change a voice or a line).
3. **✂ Cut on the shots**: Encore finds the changes of shot of the segment (ffmpeg) and makes the
   clips: a new scene at each change of shot, a shot longer than a clip cut in equal parts that
   continue each other (« clips of at most 10.1 s » by default). The cuts are on the grid where clips
   can end; move them afterwards like any clip. It asks before replacing the clips of the plan.
4. Each clip gets texts that keep the framing, motion and timing of `<Video 1>`. Write the edit once
   in **✎ Common instruction**, the first entry of the clip list (also reached from the settings): name
   the subjects with `@` (« the man is replaced by @hero »); it opens the summary of every edited clip,
   whose own summary can complete it (« the man also wears a red scarf »). The entry says which clips
   use it and which subjects it names.

**Going on after the segment.** The clips that end before the end of the segment edit the video (🎞 in
the list and on the timeline, which shows the end of the segment); the next ones continue it like any
clip: add them with « + clip » after the last one (no `<Video 1>` in their prompt). « Cut on the shots »
replaces the edited clips only and keeps the ones after. With the original sound, the final video keeps
it over the edited part only.

A clip that edits a video lasts 2 to 15 s. On the takes screen, the empty card of a clip shows, behind
the « + », the part of the video it edits (hover: plays it). The file is frozen by the first take of the
project, the segment of a branch by its first take. A start video and an edited video cannot be combined in one plan.

## Generation queue (indicator on the right of the top bar)

Encore keeps its own queue, shared by all projects, and sends ComfyUI one job at a time. Each
generation or assembly is frozen at the time of the click (plan, settings, references, seed,
upscale) and sent when its turn comes. The queue survives an Encore restart.

- Groups: a job and those that continue it (« + next clip… » or ↻ started on a waiting job).
  Their order is fixed; the whole group moves (drag its ≡ handle: a line shows where it lands and the list scrolls at its edges; or ⤒ ↑ ↓ ⤓).
- **Batches**: everything a branch ▶▶ starts (generations and final assembly) makes one block,
  « ▶▶ Branch 1: clips 3 to 16 + assembly ». It is moved, suspended or cancelled as a whole; above
  5 jobs, the list folds. A generation started after a job of the batch joins it; another
  generation goes after the batch (it can be moved up).
- **Planned assembly**: it waits until every generation it needs is finished, and takes their
  takes at that moment. If a generation fails,
  only the jobs that depend on it stop (its continuations, and the assembly: « clip 6 it depends
  on has failed »); clips of another scene go on. Starting ▶▶ again only redoes the gaps, assembly
  included.
- **Pause after the running job**: it finishes, nothing else starts.
- **Pause now**: the running job is interrupted and goes back to the top of the queue; it will
  start again from the beginning, with the same seed.
- **Suspend** a group: the queue skips it until « resume ».
- **Cancel**: a job, and those that depend on it (after confirmation). If a generation fails, those
  that depended on it are removed from the queue.
- **Cancel all** (top of the manager): every job of the queue, of every project, the running one
  included, after confirmation.
- The indicator, always visible on the right of the « Encore » bar (fixed width: a text too long ends
  with « … », the whole text is in its tooltip), sums up the state at a glance:
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

**settings…** window of the branch, « modify… » next to the upscale (⇧ on the button when it is on): first pass at a reduced size (in
megapixels, same proportions as the branch), latent upscale, second pass at the branch size. Off by
default.

- Pass 1: the first N steps of the settings schedule (scheduler, number of steps, SigmaShift), or a
  manual list of noise levels.
- Upscaler: LBH-123-AI 3D or 2D nodes (`Comfyui_Minimax_h3_latent_Upscaler` pack), or ComfyUI's node
  (MiniMax H3 Latent Upscale With Model); model in `models/latent_upscale_models`.
- Pass 2: manual list (default `0.9035, 0.8000, 0.6316, 0.3158, 0`, in 4 steps) or rest of the
  schedule; sampler and LoRA of pass 2 can be set apart (by default those of the settings).
- The seam with the previous clip and the song are put back as they are before pass 2 (ComfyUI's
  Separate/Concat AV Latent, Latent Cut, Replace Video Latent Frames nodes).
- Changing these settings changes no take; takes made with it carry the ⇧ mark (details on
  hover). A single take can use other settings, or none (see below).
- Time left is estimated separately for generations with upscale.

## LoRA and upscale per branch and per take

The LoRA stack of the Project settings always applies. « Extra » LoRA can be added:

- **Branch**: in its **settings…** window (⇧ and L on the button when they are on). Added to every take
  of the branch; « modify… » opens the upscale settings of its takes.
- **Take**: in the launch panel (↻ new take…, + next clip…): the LoRA list and the upscale for this
  take only. The upscale line is folded and says « like branch « X » » or « changed for this take »;
  **modify…** unfolds the full form (on/off, model, start size, passes…), started from the branch's
  settings; **reset to the branch's settings** goes back to them. From ↻, the panel is pre-filled
  with that take's LoRA and upscale; for the next clip, with those of the branch.

A continuation does not inherit the LoRA of the previous clip. These LoRA
also apply to pass 2 of the upscale. Each thumbnail carries its badges (L, L×2: extra LoRA, ⇧:
upscale; details on hover), like the queue and the video info. Encore adds the LoRA loaders to the
workflow it sends.

The plan window **≡** (on a take, a generation in progress, a placeholder or a column header) ends
with a **Generation** block: models, LoRA, upscale settings (and where they come from), seed, size,
reference image size and song — those used for a take, or those that would be used if launched now.

## Assembly

On hover, each take shows a **▶ assemble 1–k** button: it adds to the queue the assembly of clips 1
to k along this twig (the take and those it continues). The selection does not change. Encore makes it
itself with ffmpeg, from the takes' previews (nothing is decoded again, ComfyUI is not needed): the
branch's song for a music video, the sound generated by the clips in free mode, the branch size. A take
without its preview cannot be assembled: make it again.

- The video is copied into `exports\`: `project_branch_YYYY-MM-DD_HHhMM.mp4`, with a sheet (branch,
  takes, clips covered).
- It appears in the « ▶ Videos » panel on the right of the takes screen, under its branch name (hover:
  play and source takes highlighted; double click: large, looping; « ⌖ takes »: center the view). When
  the panel is folded, its tab shows the assemblies waiting or running, and launching one says so.
- **Assembled videos…** (top bar) lists them all, with a player.
- Next to the video, `<name>.infos.md` (readable summary: table of the clips with start/end in the
  video, take, seed, size, model, LoRA, sampler, steps, upscale; then the details and prompt of
  each clip) and `<name>.infos.json` (all the details, plus a copy of the plan at the time of the
  assembly). « infos » button in the player and in « Assembled videos… »: a page in Encore's
  colors (summary, clip table with their length, one card per clip with its branch dot, prompts),
  with links to the .md and the .json. Videos assembled before v0.11 have none.
- Several assemblies can be queued, even during generations; Encore makes them one after the other.

### Plan of a clip, plan of a take

- **≡** before the name of a clip (column header): the clip as it is in the plan of the selection,
  read only (length, link, place in the video, subjects with their pictures, anchors, lyrics or lines,
  the H3 prompt).
- **≡** on a placeholder (on hover): the plan of the clip now, with the pictures of that branch — to
  read the prompt again before launching.
- **≡** on a generation still queued or running (on hover): the plan it was launched with.
- **≡** at the top left of a take (on hover): the frozen part of this take — the clip exactly as it
  was generated (length, link, subjects with their pictures, anchors, lyrics or lines, the H3 prompt,
  the common instruction of an edit) — then the Generation block.

## Generating

Each take thumbnail shows the length of its clip (e.g. « 8.7 s »). A video opened large (take,
generation, assembled video) plays in a loop. **◎ Generation running** (top bar of the takes screen)
brings the take being generated to the middle of the view, unfolding its branch; the queue itself is
in the indicator of the « Encore » bar.

Navigation: the wheel scrolls up and down, Shift + wheel zooms (25 to 200 %) around the cursor;
dragging (on the background or a thumbnail) scrolls left / right, up to the edges of the graph; the
scroll bar scrolls up and down, until the lowest take reaches the top of the view. « fit » fits the
width of the graph to the window. The branch
column (left) and the row of clip names (top) always stay visible when scrolling; they follow the
zoom.

Overview (corner of the area, bottom right by default, ⚙ to change corner, ✕ to minimize): the
whole graph in miniature, filling it, with a frame for the visible part (cut at its edges when the view
goes past the graph) and the selection in blue; clicking or dragging on it centers the view, the wheel
zooms.

▶ Videos panel (on the right, when videos are assembled, foldable with ▸): the videos per branch,
the latest at the top; hover = play and source takes highlighted, double click = player, « ⌖ takes »
centers the view on the last take of the video.

« generate » on clip 1, ↻ new take… for another version, + next clip… for the next clip from a
take, even a waiting one. Several generations can be started: progress bar on the running
one, ⏳ on the waiting ones, « cancel » button on each. A click chooses a take: the choice is saved
right away in the project (`selection.json`).

**A take never goes stale.** It keeps the plan it was made with: changing the master plan or the plan
of another twig changes nothing for it. The settings that would make it inconsistent are frozen
(see Branches). Takes are only deleted with their branch.

**Seeds**: each take shows its full seed, selectable. Another value + Enter (or ↵) starts a new take
of this clip with this seed (same starting take for a continuation, same branch).

**Time left**: running thumbnails show « ≈ … left », waiting ones « start ≈ … ». The estimates come
from the pace of the steps of the running generation and from the length of earlier generations
(kept in `timings.json`, next to `config.json`, in proportion to the size and the number of
frames): they get better over time.

What Encore does for each generation:

1. it composes the plan of the twig (frozen part of each previous take, then the clip and those after
   it) and records the plan of what follows the new take;
2. it composes the clip's H3 prompt (the one of the « Prompt H3 » tab) and prepares its files with
   ffmpeg: the voices cut to H3's limits (2 to 15 s each, 15 s in all), the song with silence before it
   when it starts later than the plan, the end of the start video or the slice of the edited video at the
   branch size (kept in `cache\comfy\` of the project);
3. it sends them to ComfyUI (`input\encore\<project>\` for the pictures, `input\encore_<project>_…`
   for the others, named after their content) and, for a continuation, the latent of the continued take
   (`output\encore\<project>\latents\`);
4. it builds the workflow, only with ComfyUI's own nodes (MiniMax H3 Reference to Video, Load Image,
   Load Audio, sampler, VAE decode), those of MultiRef (load and save the latent, contexts of the
   continuation, of the song and of a video) and VHS (load and write videos), and puts it in ComfyUI's
   queue: ComfyUI does all the inference;
5. it follows the generation and, once finished, copies the take (latent, preview) into the project's
   `takes\`, writes its record and chooses it.

On ComfyUI's side, what a generation makes is in `output\encore\<project>\` (takes, previews, latents
sent). When no generation of the project is waiting any more, Encore empties it (option on the home
page) — only when ComfyUI's folder is given in Installation…: ComfyUI cannot delete files through its
API, so with a ComfyUI on another machine they stay.

**Takes made before 0.50**: their latent was written by ComfyUI-H3-ClipPlan (`.pt`). When such a project
is opened, Encore rewrites them once in MultiRef's format (`.safetensors`, a window shows the progress; a
plain rewriting of files, nothing is computed). A take that cannot be converted stays visible and can be
assembled, but cannot be continued.

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

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (in French): which file does what, where to make a change, which
  tests to run for each file.
- `encore/`: the server (Python standard library only). `encore/locales/`: one file per language.
- `ui/`: the sources of the page (JavaScript, `editor_shell.html`). After a change, rebuild the page with
  `python ui/build.py`, which writes `web/index.html` (the translations and the light theme are put in it).
- `tests/`: unit and end-to-end tests, with a fake ComfyUI whose fake nodes check what they get; see
  [tests/README.md](tests/README.md).
- `tests/screenshots/make_screenshots.py`: makes the screenshots of this page (`docs/screenshots/`) with the fake
  ComfyUI and the robot example of `examples/`.
- `docs/PLAN_SPEC.md` and `docs/plan.schema.json`: the plan format; `docs/LLM_SYSTEM_PROMPT.md`: the system prompt
  to have a plan written by a language model.
- [CHANGELOG.md](CHANGELOG.md): what changed in each version.

## License

GPL-3.0 (see [LICENSE](LICENSE)).
