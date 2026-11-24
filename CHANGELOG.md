# Changelog

Versions of Encore (called H3 Studio up to 0.16). Each version is delivered as `Encore_vX.Y.zip`.
Encore needs the ComfyUI plugin [ComfyUI-H3-ClipPlan](https://github.com/timpatim/ComfyUI-H3-ClipPlan)
3.11 or newer.

## 0.40

- **Video editing rolled back: it works as in 0.38 again** (plugin 3.11). The 0.39 sharpness fix broke the
  consistency between clips (for instance the red dress lost in clip 2): the reference video is the original
  video over its whole length again, and Encore no longer sends the takes' previews to ComfyUI. Takes made in
  0.39 for edit clips that continue another one are outdated. For the final render of an edit, avoid the latent
  upscale.
- **New: the final video is assembled by Encore with ffmpeg**, from the takes' previews, without ComfyUI's queue
  and without decoding the latents again. It can run while a generation is going on. Same result as the plugin's
  assembly: overlaps removed (or crossfaded), start video, song, each take's sound in free mode, original sound
  over the edited part. The queue shows « assembling (ffmpeg)… N % ». When a take has no preview or ffmpeg is
  not found, the plugin assembles as before; `"assembly_engine": "plugin"` in config.json forces it. The video's
  information file says which one made it. The previews are re-encoded at the configured crf.
- Kept from 0.39: in the Takes tab, the last branch scrolls up to the top of the view.

## 0.39

- **Fixed: edited videos lost sharpness clip after clip** (with a latent upscale above all). An edit clip that
  continues the previous one now gets, as the start of its reference video, the frames of the take it continues
  instead of the original video, so that H3 is no longer torn between the two (plugin 3.10). Encore sends the
  take's preview to ComfyUI with its latent when needed. The takes of edit clips that continue another one,
  made before, are stale: generate them again.
- Takes tab: scrolled down to the bottom, the last branch now comes up to the top of the view (it used to stay
  at the bottom of the screen).

## 0.38

- **New, edited video: the common instruction.** The edit common to the clips is written once, in
  « ✎ Common instruction », the first entry of the clip list (in its own editor, with the references on
  the right: drag one or type `@`), and put in the prompts as `{edit}` (« Cut on the shots » does it; no
  more TODO). A picture it names is added to every clip that uses it. The entry says which clips use it,
  which have their own text, and shows how H3 gets it; the settings show it on one line. Needs the
  plugin 3.9.
- **New, edited video: going on after the segment.** The clips that end after the end of the segment
  continue the video instead of being an error: the timeline shows the end of the segment, the edited
  clips have 🎞, the settings say which clips edit and which continue. A clip added after the segment gets
  a fresh prompt (no `<Video 1>`, which is an error there). « Cut on the shots » keeps these clips. With
  the original sound, the final video keeps it over the edited part only.
- The « Preview sent to H3 » tab shows `{edit}` replaced.
- Plans are saved in version 6 (sent in version 6 when they edit a video, in version 4 otherwise).

## 0.37

- **New: editing an existing video** (free mode; needs the plugin 3.8). In ⚙ Plan settings, the « Video »
  section offers « No video / Continue a video / Edit a video ». When editing, the timeline of the plan is the
  chosen segment and each clip edits its own slice of it, given to H3 as `<Video 1>` with its sound; the
  clip's voices are numbered after it. The final video keeps the original sound of the segment (default) or
  the sound H3 made.
- **✂ Cut on the shots**: the changes of shot of the segment are found (ffmpeg) and the clips made from them:
  a new scene at each change of shot, long shots cut in equal parts that continue each other, clips of at
  most 10.1 s by default. Each clip gets a prompt that keeps the framing, motion and timing of `<Video 1>`;
  only the edit is left to write (TODO).
- The branches are told when they do not have the video's proportions, and given them on request.
- Takes tab: the empty card of a clip shows the part of the video it edits (hover: plays it).
- Plans are saved in version 5; plans without an edited video are sent to ComfyUI in version 4, so that the
  plugin 3.7 still reads them.

## 0.36

- **Fixed**: the start video card of the Takes tab was slow to appear (it loaded the whole video file), was
  reloaded each time the tab was drawn again (a new take reset them all), and could go on playing without the
  mouse on it. It now plays a small copy of the segment only (270 pixels high, sound kept), made once by ffmpeg
  in the background (the card says « preparing… » meanwhile) and made again when the video or the segment
  changes; it works for videos the browser cannot play too. The same player is kept when the tab is drawn
  again, and it is stopped like the takes' thumbnails when it plays without the mouse on it. Without ffmpeg,
  the card plays the file itself from the start of the segment. The cards of assembled videos in the graph
  also keep their player. Deleting the video deletes its copies.

## 0.35

- **Fixed**: in the Takes tab, with more assembled videos than the side pane could hold, their thumbnails were
  squeezed into thin strips and the pane did not scroll. They now keep their size and the list scrolls (scroll
  bar and wheel).

## 0.34

- **Fixed**: a big file (a video, typically) was refused by ComfyUI (« 413 … Maximum request body size
  104857600 exceeded »): its upload route takes 100 MB at most by default. When ComfyUI's folder is known,
  Encore now copies the files straight into ComfyUI's `input` folder (and the takes into `output`), with no size
  limit, the progress still shown in the queue. Otherwise the upload route stays, and a refusal now says what to
  do: give ComfyUI's folder, or start ComfyUI with `--max-upload-size 4096`.
- **New**: a video the browser cannot play (AVI, ProRes, HEVC…; the player stayed grey) gets a light playable
  copy (H.264, 540 pixels high at most, sound kept), made by ffmpeg with its progress under the player (cancel
  possible). The players of the plan settings and of the resources use it; ComfyUI always gets the original.
  ffmpeg is the one of imageio-ffmpeg in ComfyUI's Python (the plugin's), else the one on the PATH. Deleting
  the video deletes its copy.

## 0.33

- **Fixed**: with the upscale on, clip 1 continuing the start video lost the video in the second pass: the
  video's last frames were not put back (nor protected), so the second pass redrew them from the blurry first pass
  and the character could turn into a similar but different one. They now go back into the second pass, as for
  the clips that continue another clip.

## 0.32

- **Fixed**: the 🗑 button of a resource was hidden when its file name was long (it was cut off with the name). It
  now stays visible: in the corner of the thumbnail, or at the end of the line.

## 0.31

- **Start video, all in the plan settings**: the video is chosen (or imported) in ⚙ Plan settings > Start video,
  one for the project, used by every branch. It is no longer a reference of the branches nor of the plan's
  reference list. Changing it asks first when takes of clip 1 use it.
- **Start video column** in the Takes tab, before clip 1, when the segment opens the final video: the segment in
  each branch, linked to the takes of clip 1 that continue it (hover: plays; click: its settings).
- **Big files**: an import shows a progress window (file, %, MB, cancel) and is written as it arrives, never held
  in memory; files are sent to ComfyUI piece by piece, the queue showing the progress.
- **Deleting resources** (🗑 in Resources): refused while a branch or the start video uses the file, after a
  warning when only checkpoints or takes need it. The copy in ComfyUI's input folder goes too. Total size shown.
- Checkpoints keep the start video too.
- **Fixed**: « null » written in the plan settings (free mode, start video).

## 0.30

- **Start from an existing video**: in ⚙ Plan settings, « Start video »: clip 1 continues a segment of a
  video file (same shot) or cuts after it. The video is imported in Resources (new « Videos » section) and
  chosen per branch in « references… ». The segment is chosen in a player (« ⇤ here » / « here ⇥ », « ▶ play
  the segment ») and snapped onto the frame grid. Option: the segment opens the final video, or is only a
  springboard. Music video: the song starts with the video (default) or after it (the video keeps its own
  sound). The segment shows on the Plan tab's timeline and in the branch header.
- Changing the branch's video file or the segment invalidates the takes of clip 1 and those that continue them.
- **Needs ComfyUI-H3-ClipPlan 3.7**: plans are now version 4 (the installation screen asks for the update).

## 0.29

- **Folded branches**: they all have the same width, the ▶▶ buttons lined up on the right; no more
  « · selection » label.
- **A folded branch never holds the selection**: folding the branch of the selection moves it to an
  unfolded branch (the one of the latest valid take of clip 1), and a take finished in a folded branch
  is not chosen on its own.
- **At least one branch stays unfolded**: the fold arrow of the last one is greyed out.
- **For the GitHub repository**: a README with the logo, screenshots and a quick start, the GPL-3.0 license,
  and `tests/screenshots/` that makes the screenshots.

## 0.28

- **Upscale of a take, simpler**: the « tuned take » dialog (▾) no longer has the « as the branch / with /
  without » choice. It shows the branch's upscale settings on a folded line (« like branch « X » »);
  **modify…** unfolds the full form to change them, or turn upscale off, for this take only; **reset to
  the branch's settings** goes back to them.
- **Removed: upscale per clip** (⚙ of the column): only the clip LoRA remain. The « with / without » choice
  and own settings given to a clip in 0.27 are ignored.
- **Plan window ≡: Generation block**: models, LoRA, upscale settings and where they come from, seed, size,
  reference image size and song — those used for a take or a running generation, or those that would be
  used if launched now (placeholder, column header).
- **Fixed**: « nullnullnull » written in the « tuned take » dialog (and in a few other windows).

## 0.27

- **≡ (plan) also on the « generate » and « following » boxes** (the plan of the clip now, to read the
  prompt again before launching) **and on a generation queued or running** (the plan it was launched with,
  compared with the plan now).
- **Upscale settings of a clip and of a take**: the clip settings (⚙ of the column) can have their own
  upscale settings (model, start size, passes…), used for this clip in every branch; the « tuned take »
  dialog (▾) can give settings for one take only, kept by the take (« ⟲ redo » and ▾ start again from
  them). The plan window of a take says which settings it was made with.
- **▶▶ « complete »**: a fixed label (it no longer overflows the branch header); what it will do is in its
  tooltip.
- **Version check**: when the page and the server running are not the same version (Encore updated while
  it was running), a banner asks to restart Encore.
- Last French texts translated (checkpoint made before an import, sigma errors of the upscale, seed field).

## 0.26

- **Sources in the repository**: the interface's sources are now in `ui/` (`python ui/build.py` builds
  `web/index.html`), the tests in `tests/` (`python tests/run_tests.py`, see `tests/README.md`), with a fake
  ComfyUI that runs the real plugin code.
- **New test**: the validity of the takes, computed both by the server and by the page, is checked to give
  the same result (and the same fingerprints) on a set of cases.
- **Removed**: the code of the app that the plugin served until its version 3.6 (it no longer exists), and of
  the even older « open the project folder » mode of the Takes tab. Nothing changes in use.
- **Fix**: editing the « detailed_description » of a continuation clip whose opening sentence was written
  without the sound sentence (free mode, plans made before or by an LLM) rewrote that sentence, which
  invalidated the clip's takes. An ordinary edit now keeps the opening sentence as it is; only « use the
  right sentence » replaces it.

## 0.25

- **Security**: Encore refuses requests from other web pages (another site, or a site whose name points
  to your PC); `--host 0.0.0.0` to open it from another device of your network.
- **ComfyUI restarted or unreachable**: the jobs it lost go back to Encore's queue and are sent again
  (twice at most); pictures, voices and takes are sent again too, also after a change of ComfyUI's address.
  With the English interface, a ComfyUI unreachable at dispatch made the job fail: it now waits.
- **Takes tab**: on an invalidated take, « ⚠ ▶ assemble » moved to the bottom left of the picture (it hid
  « ⟲ redo »); ▶▶ says « generating… » in English too; the Takes tab works when Encore is opened by its
  network address (no secure context).
- **Assembling invalidated takes** works after a reference was renamed.
- Remaining French texts translated (decimals of the info sheets, Hugging Face messages, install scripts).
  In `.infos.json`, `branche` becomes `branch` (old sheets still read) and `video.clips` is a number.

## 0.24

- **Plan of a clip** (≡ in the column header) and **plan of a take** (≡ on a take): the plan the take was made
  with, compared with the plan now (fields, prompt word by word, reference pictures, song passage).
  Takes record their plan from now on; older ones are looked for in the plans Encore keeps.
- **Fold a branch** (▾ / ▸): a thin band with name, take count and ▶▶; remembered per project.
- **Assemble invalidated takes**: « ⚠ ▶ assemble 1–k » assembles the takes really made, after a
  confirmation; refused if picture sizes differ; the info sheet lists them.

## 0.23

- **ComfyUI shared with other work**: Encore shows the jobs ahead of its own in ComfyUI and gives its time
  estimates as minimums; « pause now » and « cancel » interrupt only Encore's job.

## 0.22

- **Light theme** (☀/☾ in the top bar, or Default settings › Theme).

## 0.21

- **Languages**: English by default, French; one file per language in `encore/locales` (add yours). The
  language is chosen in Default settings.

## 0.20

- **Plan tab redesign**: subjects (@names with autocomplete, drag and drop), retention rows, summary,
  one block per shot with its automatic opening sentence, « ↺ from the previous clip »; a new clip takes over
  subjects, retention, style, soundscape and references; reference thumbnails, voices and the song passage of
  the clip playable; plan settings in « ⚙ Plan settings ».
- **Takes tab**: the ▾ dialog of a take starts from that take's LoRA and upscale; every list of 8 choices or
  more has a filter field.

## 0.19

- ▶▶ can assemble the branch at the end; « ▶ assemble 1–k » on a queued take plans the assembly.
- **Lots**: what one ▶▶ launches moves, pauses and cancels as one block; a failure stops only what depends on it.

## 0.18

- « + clip k next » box after each take, ↻ (another take from the same previous take), ▶▶ (fill every hole of
  a branch), « tuned take » dialog (LoRA, upscale, seed), ⟲ redo with the same seed.

## 0.17

- **Renamed Encore**, with its icon. Welcome screen on first start: ComfyUI's folder and Python, required node
  packs installed by `git clone` (optional ones on request), default models downloaded (disk space checked),
  ComfyUI connection indicator. Linux install scripts (0.17.x).

## 0.6 to 0.16 (H3 Studio)

- Local server and browser interface driving ComfyUI through its API; projects in their own folder (plan and
  resources copied in); checkpoints of the whole project state; takes kept forever and invalidated (never
  deleted) when what made them changes.
- Branches of takes, each with its own references, picture size and song; LoRA stacks (project, branch, clip,
  take); latent upscale; live preview during generation (ComfyUI's or KJNodes'); queue with estimates,
  pause and reordering; assembled videos with their info sheet.
