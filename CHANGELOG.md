# Changelog

Versions of Encore (called H3 Studio up to 0.16). Each version is delivered as `Encore_vX.Y.zip`.
Encore needs the ComfyUI plugin [ComfyUI-H3-ClipPlan](https://github.com/timpatim/ComfyUI-H3-ClipPlan)
3.6 or newer.

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
