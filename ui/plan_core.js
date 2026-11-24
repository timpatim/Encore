// ---------------------------------------------------------------------------------------------
// H3 Clip Plan - plan logic (pure functions, port of core.py v6). No DOM access in this part.
// ---------------------------------------------------------------------------------------------
const H3 = (() => {
    const _t = typeof H3I18n !== "undefined" ? H3I18n.t : (id) => id;
    const FPS = 24;
    const MAX_CLIPS = 64, MAX_REFS = 9, MAX_VOICES = 3, MAX_REF_FILES = 12;
    const SOFT_MAX_FRAMES = 243, HARD_MAX_FRAMES = 1195, DEFAULT_CONTEXT = 39, DEFAULT_FEATHER = 8;
    const MAX_WORDS_PER_SECOND = 3.0;
    const MODES = ["music_video", "free"];
    const SECTIONS = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:",
        "overall_soundscape:", "non_diegetic_music:"];
    const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
    const PLAN_KEYS = new Set(["version", "project", "mode", "refs_dir", "refs", "width", "height", "context_frames",
        "crossfade_frames", "audio_feather_ticks", "seed", "ref_image_size", "song", "clips", "notes", "start_video", "edit_video"]);
    const START_VIDEO_KEYS = new Set(["ref", "start", "end", "in_assembly", "song"]);
    const START_SONG_CHOICES = ["with_video", "after_video"];
    const EDIT_VIDEO_KEYS = new Set(["ref", "start", "end", "sound", "instruction"]);
    const EDIT_MARK = "{edit}";     // replaced by edit_video.instruction
    const EDIT_SOUND_CHOICES = ["original", "h3"];
    const EDIT_MIN_FRAMES = 48, EDIT_MAX_FRAMES = 360;    // a reference video lasts 2 to 15 s
    const PLAN_VERSION = 6;
    const CLIP_KEYS = new Set(["name", "frames", "continue", "refs", "prompt", "seed", "lyrics", "dialogue", "notes"]);
    const DIALOGUE_KEYS = new Set(["speaker", "text", "language"]);

    const placeholderRe = () => /\{(picture|voice):([A-Za-z0-9][A-Za-z0-9_-]*)\}/g;
    const anyBraceRe = () => /\{(picture|voice|image|audio)\s*:[^}]*\}/gi;

    const isInt = (v) => typeof v === "number" && Number.isInteger(v);
    const isRun = (f) => isInt(f) && f >= 5 && (f - 5) % 17 === 0;
    const largestRun = (f) => (f < 5 ? 0 : 5 + Math.floor((f - 5) / 17) * 17);
    const nearestRuns = (f) => { const low = Math.max(5, largestRun(f)); return [low, low + 17]; };
    const snapContext = (req, prev, f) => largestRun(Math.min(req, prev, f - 1));
    const isAvBoundary = (f) => (f * 40) % FPS === 0;
    const avContextValues = () => { const out = []; for (let n = 5; n <= 243; n += 17) if (isAvBoundary(n)) out.push(n); return out; };
    const mode = (plan) => (plan && MODES.includes(plan.mode) ? plan.mode : "music_video");

    function placeholders(text) {
        const out = [];
        for (const m of String(text || "").matchAll(placeholderRe())) out.push({ kind: m[1], name: m[2] });
        return out;
    }

    function squash(text) {
        return String(text).toLowerCase().replace(/[^\p{L}\p{N}_]+/gu, " ").trim();
    }

    // Python's round(): halves go to the even neighbour
    function pyRound(x) {
        const f = Math.floor(x), d = x - f;
        if (d > 0.5) return f + 1;
        if (d < 0.5) return f;
        return f % 2 === 0 ? f : f + 1;
    }
    const isNumber = (v) => typeof v === "number" && Number.isFinite(v);
    // The start video segment as core.normalize gives it, or null (also when start_video is not usable).
    function startVideo(plan) {
        const sv = plan && plan.start_video;
        if (!sv || typeof sv !== "object" || !isNumber(sv.end)) return null;
        const start = sv.start ?? 0;
        if (!isNumber(start) || start < 0 || sv.end <= start) return null;
        const endFrame = pyRound(sv.end * FPS), startFrame = pyRound(start * FPS);
        const frames = largestRun(endFrame - startFrame);
        if (frames <= 0) return null;
        return { ref: sv.ref, frames, start_frame: endFrame - frames, end_frame: endFrame,
            in_assembly: sv.in_assembly !== false, song: sv.song || "with_video" };
    }
    // The edited video segment as core.normalize gives it, or null.
    function editVideo(plan) {
        const ev = plan && plan.edit_video;
        if (!ev || typeof ev !== "object" || !isNumber(ev.end)) return null;
        const start = ev.start ?? 0;
        if (!isNumber(start) || start < 0 || ev.end <= start) return null;
        const startFrame = pyRound(start * FPS), frames = pyRound(ev.end * FPS) - startFrame;
        return { ref: ev.ref, start_frame: startFrame, end_frame: startFrame + frames, frames, sound: ev.sound || "original",
            instruction: typeof ev.instruction === "string" ? ev.instruction : null };
    }
    // core.expand_edit: {edit} replaced by the common instruction, the references it names added at the end
    function expandEdit(prompt, refs, instruction) {
        refs = [...(refs || [])];
        if (instruction === null || instruction === undefined || typeof prompt !== "string" || !prompt.includes(EDIT_MARK)) return [prompt, refs];
        for (const p of placeholders(instruction)) if (!refs.includes(p.name)) refs.push(p.name);
        return [prompt.split(EDIT_MARK).join(instruction), refs];
    }
    const instructionOf = (plan) => (plan && plan.edit_video && typeof plan.edit_video.instruction === "string" ? plan.edit_video.instruction : null);
    // a clip as the plugin sees it: prompt and references with {edit} expanded
    function expandedClip(plan, clip) {
        const [prompt, refs] = expandEdit(clip.prompt, clip.refs, instructionOf(plan));
        return { ...clip, prompt, refs };
    }
    // core.edit_clip_count: the clips ending before the end of the segment edit it; the next ones continue the video
    function editClipCount(plan) {
        const ev = editVideo(plan);
        if (!ev) return 0;
        return timeline(plan).filter((r) => r.end <= ev.frames).length;
    }
    // (first frame in the file, frames) of the source that clip `index` edits, or null (core.edit_slice)
    function editSlice(plan, index) {
        const ev = editVideo(plan);
        if (!ev) return null;
        const row = timeline(plan)[index - 1];
        return row && row.end <= ev.frames ? [ev.start_frame + row.raw_start, row.frames] : null;
    }
    // Clips that cover an edited segment of `segFrames` frames: a new scene at each cut of the video (frames from the
    // start of the segment, put on the 17k + 5 grid where clips can end), a shot longer than a clip split in equal
    // parts that continue each other. Every clip lasts at most maxFrames (and 2 s at least). [{frames, continue}]
    function editCuts(segFrames, cuts, context, maxFrames) {
        const grid = (x) => 5 + 17 * Math.round((x - 5) / 17);
        const end = largestRun(segFrames);
        const MIN_FIRST = 56, MIN_SECTION = 34;
        if (end < MIN_FIRST) return [];
        const bounds = [0];
        for (const c of [...cuts].sort((a, b) => a - b)) {
            const b = grid(c);
            const last = bounds[bounds.length - 1];
            if (b < (last === 0 ? MIN_FIRST : last + MIN_SECTION) || b > end - MIN_SECTION) continue;
            bounds.push(b);
        }
        bounds.push(end);
        const out = [];
        for (let i = 0; i + 1 < bounds.length; i++) {
            const a = bounds[i], b = bounds[i + 1];
            for (let parts = 1; parts < 400; parts++) {
                const marks = [a];
                for (let j = 1; j < parts; j++) marks.push(grid(a + (b - a) * j / parts));
                marks.push(b);
                const clips = [];
                let ok = true;
                for (let j = 0; j + 1 < marks.length; j++) {
                    const frames = marks[j] === 0 ? marks[j + 1] : marks[j + 1] - marks[j] + context;
                    if (marks[j + 1] <= marks[j] || frames > maxFrames || frames < EDIT_MIN_FRAMES || frames <= context) { ok = false; break; }
                    clips.push({ frames, continue: j > 0 });
                }
                if (ok) { out.push(...clips); break; }
            }
        }
        return out;
    }
    function startRow(plan) {
        const sv = startVideo(plan);
        return sv ? { index: 0, frames: sv.frames, raw_start: 0, visible: 0, end: sv.frames, context: 0 } : null;
    }
    // first timeline frame of the assembled video, and timeline frame at which the song starts (core.final_start / song_offset)
    function finalStart(plan) {
        const sv = startVideo(plan);
        if (!sv || sv.in_assembly) return 0;
        return timeline(plan)[0].raw_start;
    }
    function songOffset(plan) {
        const sv = startVideo(plan);
        if (!sv || mode(plan) === "free") return 0;
        if (!sv.in_assembly) return finalStart(plan);
        return sv.song === "with_video" ? 0 : sv.frames;
    }

    function contextOf(plan) {
        const c = plan.context_frames ?? DEFAULT_CONTEXT;
        return isRun(c) ? c : DEFAULT_CONTEXT;
    }

    // Per-clip timing. Only meaningful when every frames value is legal.
    function timeline(plan) {
        const rows = [];
        let prev = startRow(plan);   // the start video segment acts as the clip before clip 1
        const ctx = contextOf(plan);
        (plan.clips || []).forEach((clip, i) => {
            const frames = clip.frames;
            let context = 0, rawStart = 0;
            if (prev) {
                context = snapContext(ctx, prev.frames, frames);
                rawStart = prev.end - context;
            }
            const row = {
                index: i + 1, name: clip.name || `clip_${String(i + 1).padStart(3, "0")}`, frames,
                continue: !!clip.continue, context, raw_start: rawStart, visible: rawStart + context, end: rawStart + frames,
            };
            rows.push(row);
            prev = row;
        });
        return rows;
    }

    function framesLegal(plan) {
        const ctx = contextOf(plan);
        return Array.isArray(plan.clips) && plan.clips.length > 0 &&
            plan.clips.every((c) => c && isRun(c.frames) && c.frames > ctx && c.frames <= HARD_MAX_FRAMES);
    }

    // Returns a list of {level: "error"|"warning", clip: index (1-based) or 0, text}.
    function validate(plan) {
        const out = [];
        const err = (text, clip = 0) => out.push({ level: "error", clip, text });
        const warn = (text, clip = 0) => out.push({ level: "warning", clip, text });
        if (!plan || typeof plan !== "object" || Array.isArray(plan)) { err(_t("check.the_plan_must_be_a_json")); return out; }

        for (const key of Object.keys(plan)) {
            if (!PLAN_KEYS.has(key) && !key.startsWith("_")) warn(_t("check.unknown_key_ignored", { key }));
        }
        const version = plan.version;
        if (![1, 2, 3, 4, 5, 6].includes(version)) err(_t("check.version_must_be_3"));
        if ("mode" in plan && !MODES.includes(plan.mode)) err(_t("check.mode_must_be_music_video_or", { v0: JSON.stringify(plan.mode) }));
        if ((version === 1 || version === 2) && plan.mode === "free") err(_t("check.the_free_mode_needs_version_3"));
        const free = mode(plan) === "free";
        if ("refs_dir" in plan) warn(_t("check.refs_dir_is_no_longer_used"));
        if (typeof plan.project !== "string" || !NAME_RE.test(plan.project)) err(_t("check.project_a_short_name_made_of"));
        for (const key of ["width", "height"]) {
            const v = plan[key];
            if (v !== undefined && v !== null && (!isInt(v) || v < 64 || v % 32 !== 0)) err(_t("check.must_be_a_multiple_of_32", { key, v1: JSON.stringify(v) }));
        }
        if ((plan.width == null) !== (plan.height == null)) err(_t("check.width_and_height_go_together_both"));
        let context = plan.context_frames ?? DEFAULT_CONTEXT;
        if (!isRun(context)) {
            err(_t("check.context_frames_must_be_5_22", { v0: JSON.stringify(context) }));
            context = DEFAULT_CONTEXT;
        } else if (free && !isAvBoundary(context)) {
            err(_t("check.in_free_mode_context_frames_must", { v0: avContextValues().join(", "), context }));
            context = DEFAULT_CONTEXT;
        }
        const crossfade = plan.crossfade_frames ?? 0;
        if (!isInt(crossfade) || crossfade < 0 || crossfade > context) err(_t("check.crossfade_frames_an_integer_from_0", { context }));
        if ("audio_feather_ticks" in plan) {
            if (!free) warn(_t("check.audio_feather_ticks_is_only_used"));
            const f = plan.audio_feather_ticks;
            if (!isInt(f) || f < 0 || f > 64) err(_t("check.audio_feather_ticks_an_integer_from"));
        }
        if ("seed" in plan && (!isInt(plan.seed) || plan.seed < 0)) err(_t("check.seed_must_be_a_positive_integer"));
        if (!["match", "max", undefined].includes(plan.ref_image_size)) err(_t("check.ref_image_size_must_be_match"));

        let refsMap = plan.refs ?? {};
        if (typeof refsMap !== "object" || Array.isArray(refsMap)) { err(_t("check.refs_must_be_an_object_name")); refsMap = {}; }
        const declared = Object.keys(refsMap);
        for (const [name, desc] of Object.entries(refsMap)) {
            if (!NAME_RE.test(name)) err(_t("check.reference_name_letters_digits_and_only_2", { name }));
            if (typeof desc !== "string") err(_t("check.reference_the_description_must_be_a", { name }));
        }

        const sv = plan.start_video;
        if (sv !== undefined && sv !== null) {
            if (typeof sv !== "object" || Array.isArray(sv)) err(_t("check.start_video_must_be_an_object"));
            else {
                for (const key of Object.keys(sv)) if (!START_VIDEO_KEYS.has(key) && !key.startsWith("_")) warn(_t("check.start_video_unknown_key", { key }));
                if (typeof sv.ref !== "string" || !NAME_RE.test(sv.ref)) err(_t("check.start_video_ref_must_be_a_name"));
                else if (!declared.includes(sv.ref)) err(_t("check.start_video_ref_not_declared", { ref: sv.ref }));
                const start = sv.start ?? 0;
                if (!isNumber(start) || start < 0) err(_t("check.start_video_start_must_be"));
                else if (!isNumber(sv.end) || sv.end <= start) err(_t("check.start_video_end_must_be"));
                else {
                    const frames = startVideo(plan).frames;
                    if (frames <= context) err(_t("check.start_video_too_short", { frames, context, v2: ((context + 17) / FPS).toFixed(2) }));
                }
                if ("in_assembly" in sv && typeof sv.in_assembly !== "boolean") err(_t("check.start_video_in_assembly_bool"));
                const sg = sv.song ?? "with_video";
                if (!START_SONG_CHOICES.includes(sg)) err(_t("check.start_video_song_choices", { v0: JSON.stringify(sg) }));
                else if (free && "song" in sv) warn(_t("check.start_video_song_only_music"));
            }
        }

        const ev = plan.edit_video;
        let editFrames = null;
        if (ev !== undefined && ev !== null) {
            if (sv !== undefined && sv !== null) err(_t("check.edit_video_and_start_video"));
            if (!free) err(_t("check.edit_video_needs_free"));
            if (typeof ev !== "object" || Array.isArray(ev)) err(_t("check.edit_video_must_be_an_object"));
            else {
                for (const key of Object.keys(ev)) if (!EDIT_VIDEO_KEYS.has(key) && !key.startsWith("_")) warn(_t("check.edit_video_unknown_key", { key }));
                if (typeof ev.ref !== "string" || !NAME_RE.test(ev.ref)) err(_t("check.edit_video_ref_must_be_a_name"));
                else if (!declared.includes(ev.ref)) err(_t("check.edit_video_ref_not_declared", { ref: ev.ref }));
                const start = ev.start ?? 0;
                if (!isNumber(start) || start < 0) err(_t("check.edit_video_start_must_be"));
                else if (!isNumber(ev.end) || ev.end <= start) err(_t("check.edit_video_end_must_be"));
                else {
                    if (ev.instruction !== undefined && ev.instruction !== null) {
                        if (typeof ev.instruction !== "string") err(_t("check.edit_instruction_must_be_text"));
                        else {
                            if (ev.instruction.includes(EDIT_MARK)) err(_t("check.edit_instruction_no_mark"));
                            for (const m of ev.instruction.matchAll(/\{(picture|voice|image|audio)\s*:[^}]*\}/gi)) if (!/^\{(picture|voice):[A-Za-z0-9][A-Za-z0-9_-]*\}$/.test(m[0])) err(_t("check.edit_instruction_bad_placeholder", { v0: m[0] }));
                            for (const p of placeholders(ev.instruction)) if (declared.length && !declared.includes(p.name)) err(_t("check.edit_instruction_unknown_ref", { ref: p.name }));
                        }
                    }
                    if (!EDIT_SOUND_CHOICES.includes(ev.sound ?? "original")) err(_t("check.edit_video_sound_choices", { v0: JSON.stringify(ev.sound) }));
                    const frames = editVideo(plan).frames;
                    if (frames < EDIT_MIN_FRAMES) err(_t("check.edit_video_too_short", { v0: (frames / FPS).toFixed(2) }));
                    else editFrames = frames;
                }
            }
        }

        let song = plan.song ?? {};
        if (typeof song !== "object" || Array.isArray(song)) { err(_t("check.song_must_be_an_object")); song = {}; }
        let songDuration = null;
        if (free) {
            if (Object.keys(song).length) err(_t("check.free_mode_has_no_song_remove"));
        } else if (typeof song.duration_seconds === "number") songDuration = song.duration_seconds;

        const clips = plan.clips;
        if (!Array.isArray(clips) || !clips.length) { err(_t("check.clips_must_be_a_non_empty")); return out; }
        if (clips.length > MAX_CLIPS) err(_t("check.at_most_clips_found", { MAX_CLIPS, length: clips.length }));

        const names = new Set();
        let framesOk = true;
        clips.forEach((clip, i) => {
            const n = i + 1;
            if (!clip || typeof clip !== "object" || Array.isArray(clip)) { err(_t("check.the_clip_must_be_an_object"), n); framesOk = false; return; }
            for (const key of Object.keys(clip)) if (!CLIP_KEYS.has(key) && !key.startsWith("_")) warn(_t("check.unknown_key_ignored", { key }), n);
            const name = clip.name ?? `clip_${String(n).padStart(3, "0")}`;
            if (typeof name !== "string" || !NAME_RE.test(name)) err(_t("check.name_letters_digits_and_only"), n);
            else if (names.has(name)) err(_t("check.name_already_used", { name }), n);
            names.add(name);

            const frames = clip.frames;
            if (!isRun(frames)) {
                framesOk = false;
                if (isInt(frames) && frames > 0) {
                    const [lo, hi] = nearestRuns(frames);
                    err(_t("check.frames_must_be_17k_5_found", { frames, lo, hi }), n);
                } else err(_t("check.frames_must_be_an_integer_of", { v0: JSON.stringify(frames) }), n);
            } else {
                if (frames <= context) { err(_t("check.frames_must_be_more_than_context", { frames, context }), n); framesOk = false; }
                if (frames > HARD_MAX_FRAMES) err(_t("check.frames_is_far_too_large", { frames }), n);
                else if (frames > SOFT_MAX_FRAMES) warn(_t("check.frames_s_more_than_frames_slow", { frames, v1: (frames / FPS).toFixed(1), SOFT_MAX_FRAMES }), n);
            }

            const cont = clip.continue ?? false;
            if (typeof cont !== "boolean") err(_t("check.continue_must_be_true_or_false"), n);
            else if (cont && n === 1 && (sv === undefined || sv === null)) err(_t("check.clip_1_cannot_be_a_continuation"));

            let refs = clip.refs ?? [];
            if (!Array.isArray(refs) || !refs.every((r) => typeof r === "string")) { err(_t("check.refs_must_be_a_list_of"), n); refs = []; }
            const instruction = ev !== undefined && ev !== null ? instructionOf(plan) : null;
            if (typeof clip.prompt === "string" && clip.prompt.includes(EDIT_MARK) && instruction === null) err(_t("check.edit_mark_without_instruction"), n);
            let expandedPrompt;
            [expandedPrompt, refs] = expandEdit(clip.prompt, refs, instruction);
            if (new Set(refs).size !== refs.length) err(_t("check.a_reference_is_listed_twice"), n);
            const limit = free ? MAX_REF_FILES : MAX_REFS;
            if (refs.length > limit) err(_t("check.at_most_references_per_clip_found", { limit, length: refs.length }), n);
            for (const ref of refs) {
                if (!NAME_RE.test(ref)) err(_t("check.reference_name_letters_digits_and_only", { ref }), n);
                else if (declared.length && !declared.includes(ref)) err(_t("check.the_reference_is_not_declared_in", { ref }), n);
            }
            if (!refs.length) warn(_t("check.no_reference_the_clip_will_be"), n);

            let prompt = expandedPrompt;
            if (typeof prompt !== "string" || !prompt.trim()) { err(_t("check.the_prompt_is_empty"), n); prompt = ""; }
            else {
                let position = -1;
                for (const section of SECTIONS) {
                    const found = prompt.indexOf(section);
                    if (found < 0) warn(_t("check.the_prompt_has_no_section", { section }), n);
                    else if (found < position) warn(_t("check.the_section_is_out_of_place", { section }), n);
                    position = Math.max(position, found);
                }
                const ph = placeholders(prompt);
                const pictures = new Set(ph.filter((p) => p.kind === "picture").map((p) => p.name));
                const voices = new Set(ph.filter((p) => p.kind === "voice").map((p) => p.name));
                for (const m of prompt.matchAll(anyBraceRe())) {
                    if (!/^\{(picture|voice):[A-Za-z0-9][A-Za-z0-9_-]*\}$/.test(m[0])) err(_t("check.is_not_a_valid_placeholder_write", { v0: m[0] }), n);
                }
                for (const ref of [...new Set([...pictures, ...voices])].sort()) {
                    if (!refs.includes(ref)) err(_t("check.the_prompt_uses_but_the_clip", { ref }), n);
                }
                const numbered = [...new Set([...prompt.matchAll(/<Picture (\d+)>/g)].map((m) => +m[1]))].sort((a, b) => a - b);
                for (const k of numbered) if (k < 1 || k > refs.length) err(_t("check.the_prompt_uses_picture_but_the", { k, length: refs.length }), n);
                if (numbered.length && pictures.size) err(_t("check.do_not_mix_picture_n_and"), n);
                if (pictures.size > MAX_REFS) err(_t("check.at_most_pictures_per_clip", { MAX_REFS }), n);
                if (voices.size > MAX_VOICES) err(_t("check.at_most_voices_per_clip_found", { MAX_VOICES, size: voices.size, v2: [...voices].sort().join(", ") }), n);
                if (pictures.size + voices.size > MAX_REF_FILES) err(_t("check.at_most_reference_files_pictures_voices", { MAX_REF_FILES }), n);
                for (const line of prompt.split("\n")) {
                    if (line.includes("{voice:") && (line.includes("{picture:") || line.includes("<Picture"))) {
                        err(_t("check.each_must_be_alone_on_its"), n);
                        break;
                    }
                }
                const vids = [...new Set([...prompt.matchAll(/<Video (\d+)>/g)].map((m) => +m[1]))];
                if (vids.length && (ev === undefined || ev === null)) err(_t("check.video_tag_without_edit"), n);
                else if (vids.some((k) => k !== 1)) err(_t("check.video_tag_is_video_1"), n);
                if (prompt.includes("<Audio ")) {
                    if (free) err(_t("check.do_not_write_audio_n_write"), n);
                    else warn(_t("check.the_prompt_mentions_audio_n_the"), n);
                }
                if (voices.size && !free) warn(_t("check.voices_are_ignored_in_music_video"), n);
            }

            if (clip.lyrics && free) warn(_t("check.lyrics_is_for_music_video_mode"), n);
            let dialogue = clip.dialogue ?? [];
            if (dialogue.length && !free) warn(_t("check.lines_are_only_checked_in_free"), n);
            if (!Array.isArray(dialogue)) { err(_t("check.dialogue_must_be_a_list_of"), n); dialogue = []; }
            let words = 0;
            dialogue.forEach((line, k) => {
                const where = _t("check.line", { v0: k + 1 });
                if (!line || typeof line !== "object") { err(_t("check.must_be_an_object_with_speaker", { where }), n); return; }
                for (const key of Object.keys(line)) if (!DIALOGUE_KEYS.has(key) && !key.startsWith("_")) warn(_t("check.unknown_key_ignored_2", { where, key }), n);
                if (typeof line.speaker !== "string" || !refs.includes(line.speaker)) err(_t("check.the_speaker_must_be_one_of", { where, v1: JSON.stringify(line.speaker) }), n);
                if (typeof line.text !== "string" || !line.text.trim()) { err(_t("check.empty_text", { where }), n); return; }
                words += line.text.trim().split(/\s+/).length;
                if (prompt && !squash(prompt).includes(squash(line.text))) warn(_t("check.this_text_is_not_in_the", { where }), n);
                if ("language" in line && typeof line.language !== "string") err(_t("check.language_must_be_a_text_for", { where }), n);
            });
            if (words && isRun(frames) && frames > context) {
                const speaking = (frames - (n > 1 ? context : 0)) / FPS;
                const rate = words / speaking;
                if (rate > MAX_WORDS_PER_SECOND) warn(_t("check.words_in_s_of_new_picture", { words, v1: speaking.toFixed(1), v2: rate.toFixed(1) }), n);
            }
            if ("seed" in clip && clip.seed !== null && (!isInt(clip.seed) || clip.seed < 0)) err(_t("check.seed_must_be_a_positive_integer"), n);
        });

        if (framesOk && editFrames && !out.some((m) => m.level === "error")) {
            const rows = timeline(plan);
            const edited = editClipCount(plan);
            if (!edited) err(_t("check.edit_no_clip_inside", { v0: (editFrames / FPS).toFixed(3) }));
            rows.forEach((row, k) => {
                if (row.index <= edited) {
                    if (row.frames < EDIT_MIN_FRAMES || row.frames > EDIT_MAX_FRAMES) err(_t("check.edit_clip_length", { frames: row.frames }), row.index);
                } else if (/<Video (\d+)>/.test(expandedClip(plan, plan.clips[k]).prompt || "")) err(_t("check.edit_video_tag_after_segment"), row.index);
            });
            if (edited && edited < rows.length) {
                const row = rows[edited];
                if (editFrames - row.visible >= 17) warn(_t("check.edit_clip_past_segment", { n: row.index, v0: ((row.end - editFrames) / FPS).toFixed(2), v1: (row.visible / FPS).toFixed(2) }));
            } else if (edited && editFrames - rows[rows.length - 1].end >= FPS) {
                warn(_t("check.edit_rest_not_edited", { v0: (rows[rows.length - 1].end / FPS).toFixed(2), v1: (editFrames / FPS).toFixed(2) }));
            }
        }
        if (framesOk && !out.some((m) => m.level === "error")) {
            const rows = timeline(plan);
            const offset = songOffset(plan);
            if (songDuration !== null) {
                for (const row of rows) {
                    if ((row.end - offset) / FPS > songDuration + 1 / FPS) err(_t("check.ends_at_s_after_the_end", { v0: ((row.end - offset) / FPS).toFixed(3), v1: songDuration.toFixed(3) }), row.index);
                }
                const last = (rows[rows.length - 1].end - offset) / FPS;
                if (last < songDuration - 1) warn(_t("check.the_plan_ends_at_s_but", { v0: last.toFixed(2), v1: songDuration.toFixed(2) }));
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ prompt sections
    function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

    function parseSections(prompt) {
        const text = String(prompt || "");
        const starts = SECTIONS.map((s) => {
            const m = new RegExp(`(^|\\n)${escapeRe(s)}`).exec(text);
            return m ? m.index + m[1].length : -1;
        });
        if (starts.some((v) => v < 0)) return null;
        for (let k = 1; k < starts.length; k++) if (starts[k] <= starts[k - 1]) return null;
        const head = text.slice(0, starts[0]).trim();
        if (head) return null;
        return SECTIONS.map((s, k) => text.slice(starts[k] + s.length, k + 1 < starts.length ? starts[k + 1] : text.length)
            .replace(/^[ \t]*\n/, "").replace(/^[ \t]+/, "").replace(/\s+$/, ""));
    }

    function composeSections(parts) {
        return SECTIONS.map((s, k) => `${s}\n${(parts[k] || "").replace(/\s+$/, "")}`).join("\n\n");
    }

    function skeleton(clip, index, isFree) {
        const refs = clip.refs || [];
        const subjects = refs.map((r, k) => `<Subject ${k + 1}> is ... whose appearance comes from {picture:${r}}.`).join("\n");
        let shot = "[Shot 1] ";
        if (clip.continue) shot += CONTINUE_SENTENCE + (isFree ? FREE_CONTINUE_SUFFIX : "") + " ";
        else if (index > 1) shot += (isFree ? HIDDEN_LEADIN_FREE : HIDDEN_LEADIN_MUSIC) + " ";
        return composeSections([
            subjects,
            "[reference generation] ",
            refs.map((r, k) => `<Subject ${k + 1}> (appears throughout [Shot 1]): fully_preserved - `).join("\n"),
            "The target video is ...\n" + shot,
            isFree ? "" : "",
            isFree ? "None." : "",
        ]);
    }

    const CONTINUE_SENTENCE = "The incoming performer motion, camera trajectory, body momentum, facial state, lighting, environment and object state continue uninterrupted from the protected video context.";
    const FREE_CONTINUE_SUFFIX = " The protected sound continues too; nothing in that context is repeated.";
    const HIDDEN_LEADIN_FREE = "Hidden lead-in for the first 1.6 seconds: the scene is already fully established, nobody speaks.";
    const HIDDEN_LEADIN_MUSIC = "The first second and a half of this clip is a lead-in that overlaps the end of the previous song phrase; the scene is already fully established from the first frame.";

    function renameRef(plan, oldName, newName) {
        const re = new RegExp(`\\{(picture|voice):${escapeRe(oldName)}\\}`, "g");
        if (plan.start_video && plan.start_video.ref === oldName) plan.start_video.ref = newName;
        if (plan.edit_video && plan.edit_video.ref === oldName) plan.edit_video.ref = newName;
        if (plan.edit_video && typeof plan.edit_video.instruction === "string") plan.edit_video.instruction = plan.edit_video.instruction.replace(re, (_m, kind) => `{${kind}:${newName}}`);
        for (const clip of plan.clips || []) {
            if (Array.isArray(clip.refs)) clip.refs = clip.refs.map((r) => (r === oldName ? newName : r));
            if (typeof clip.prompt === "string") clip.prompt = clip.prompt.replace(re, (_m, kind) => `{${kind}:${newName}}`);
            if (Array.isArray(clip.dialogue)) for (const d of clip.dialogue) if (d && d.speaker === oldName) d.speaker = newName;
        }
    }

    function referenceKinds(plan, name) {
        const kinds = new Set();
        if ((plan.start_video && plan.start_video.ref === name) || (plan.edit_video && plan.edit_video.ref === name)) kinds.add("video");
        for (const raw of plan.clips || []) {
            const clip = expandedClip(plan, raw);
            if (!(clip.refs || []).includes(name)) continue;
            const prompt = String(clip.prompt || "");
            const found = placeholders(prompt).filter((p) => p.name === name).map((p) => p.kind);
            if (found.includes("picture") || (prompt.includes("<Picture") && !placeholders(prompt).length)) kinds.add("image");
            if (found.includes("voice") && mode(plan) === "free") kinds.add("voice");
        }
        return [...kinds];
    }

    // ------------------------------------------------------------------ takes (port of core.py)
    // Python's json.dumps(obj, sort_keys=True) with its default ensure_ascii=True and separators (", ", ": ").
    function pyString(text) {
        let out = '"';
        for (let i = 0; i < text.length; i++) {
            const c = text.charCodeAt(i);
            const ch = text[i];
            if (ch === '"') out += '\\"';
            else if (ch === "\\") out += "\\\\";
            else if (ch === "\n") out += "\\n";
            else if (ch === "\r") out += "\\r";
            else if (ch === "\t") out += "\\t";
            else if (ch === "\b") out += "\\b";
            else if (ch === "\f") out += "\\f";
            else if (c < 0x20 || c > 0x7e) out += "\\u" + c.toString(16).padStart(4, "0");
            else out += ch;
        }
        return out + '"';
    }
    function pyDumps(value) {
        if (value === null || value === undefined) return "null";
        if (value === true) return "true";
        if (value === false) return "false";
        if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(value);
        if (typeof value === "string") return pyString(value);
        if (Array.isArray(value)) return "[" + value.map(pyDumps).join(", ") + "]";
        const keys = Object.keys(value).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
        return "{" + keys.map((k) => pyString(k) + ": " + pyDumps(value[k])).join(", ") + "}";
    }
    // SHA-256 written out: crypto.subtle only exists on https or localhost, not when Encore is opened by its
    // address on the local network
    const SHA_K = new Uint32Array([0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
        0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb,
        0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f,
        0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
    function sha256Plain(bytes) {
        const length = bytes.length, padded = new Uint8Array(((length + 9 + 63) >> 6) << 6);
        padded.set(bytes);
        padded[length] = 0x80;
        const bits = length * 8, view = new DataView(padded.buffer);
        view.setUint32(padded.length - 8, Math.floor(bits / 0x100000000));
        view.setUint32(padded.length - 4, bits >>> 0);
        const H = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
        const W = new Uint32Array(64);
        const rot = (x, n) => (x >>> n) | (x << (32 - n));
        for (let off = 0; off < padded.length; off += 64) {
            for (let i = 0; i < 16; i++) W[i] = view.getUint32(off + i * 4);
            for (let i = 16; i < 64; i++) {
                const s0 = rot(W[i - 15], 7) ^ rot(W[i - 15], 18) ^ (W[i - 15] >>> 3), s1 = rot(W[i - 2], 17) ^ rot(W[i - 2], 19) ^ (W[i - 2] >>> 10);
                W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
            }
            let [a, b, c, d, e, f, g, h] = H;
            for (let i = 0; i < 64; i++) {
                const t1 = (h + (rot(e, 6) ^ rot(e, 11) ^ rot(e, 25)) + ((e & f) ^ (~e & g)) + SHA_K[i] + W[i]) >>> 0;
                const t2 = ((rot(a, 2) ^ rot(a, 13) ^ rot(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
                h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
            }
            H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
        }
        return [...H].map((x) => x.toString(16).padStart(8, "0")).join("");
    }
    async function sha256Hex(text) {
        const bytes = new TextEncoder().encode(text);
        if (typeof crypto !== "undefined" && crypto.subtle) {
            const digest = await crypto.subtle.digest("SHA-256", bytes);
            return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
        }
        return sha256Plain(bytes);
    }
    // Same value as core.take_fingerprint(normalize(plan), index). Needs legal frames everywhere.
    async function takeFingerprints(plan) {
        const rows = timeline(plan);
        const out = {};
        for (const row of rows) {
            const clip = expandedClip(plan, plan.clips[row.index - 1]);
            const payload = {
                frames: clip.frames, continue: !!clip.continue, refs: [...(clip.refs || [])], prompt: clip.prompt,
                raw_start: row.raw_start, context: row.context, mode: mode(plan),
            };
            const sv = startVideo(plan);   // same as core._start_video_payload
            const ev = editVideo(plan);
            if (ev) { if (editSlice(plan, row.index)) payload.edit_video = [ev.ref, ev.start_frame]; }
            else if (sv) {
                if (row.index === 1 && plan.clips[0].continue) payload.start_video = [sv.ref, sv.start_frame, sv.end_frame];
                if (mode(plan) === "music_video") payload.song_offset = songOffset(plan);
            }
            out[row.index] = (await sha256Hex(pyDumps(payload))).slice(0, 16);
        }
        return out;
    }

    // Port of core.resolve_takes. takes: {index: [record]} (record.id set), fingerprints: {index: fp}.
    function resolveTakes(plan, takes, selection, fingerprints) {
        selection = selection || {};
        const everything = Object.values(takes).flat();
        const currentRefs = new Map();
        let currentSize = null;
        for (const r of [...everything].sort((a, b) => (a.saved_at || 0) - (b.saved_at || 0))) {
            for (const [name, kinds] of Object.entries(r.refs || {})) {
                for (const kind of ["image", "voice", "video"]) currentRefs.set(`${name}\u0000${kind}`, (kinds || {})[kind] ?? null);
            }
            currentSize = [r.width, r.height];
        }
        const result = {};
        (plan.clips || []).forEach((clip, k) => {
            const index = k + 1;
            const previous = result[index - 1];
            const living = new Set(previous ? Object.entries(previous.takes).filter(([, s]) => s[0] !== "stale").map(([id]) => id) : []);
            const states = {}, kinds = {};
            const existingParents = new Set((takes[index - 1] || []).map((r) => r.id));
            const list = [...(takes[index] || [])].sort((a, b) => (a.saved_at || 0) - (b.saved_at || 0));
            for (const r of list) {
                let reason = null, kind = null;
                if (r.frames !== clip.frames || r.fingerprint !== fingerprints[index]) { reason = _t("check.its_entry_in_the_plan_has"); kind = "plan"; }
                else if (!currentSize || r.width !== currentSize[0] || r.height !== currentSize[1]) {
                    reason = _t("check.made_at_x_the_latest_at", { width: r.width, height: r.height, v2: currentSize ? currentSize.join("x") : "?" });
                    kind = "size";
                } else {
                    outer: for (const name of Object.keys(r.refs || {}).sort()) {
                        for (const kind of ["image", "voice", "video"]) {
                            const mine = (r.refs[name] || {})[kind] ?? null;
                            if (mine !== (currentRefs.get(`${name}\u0000${kind}`) ?? null)) {
                                reason = _t("check.of_has_changed_since", { v0: kind === "image" ? _t("check.the_picture") : _t("check.the_voice"), name });
                                break outer;
                            }
                        }
                    }
                }
                if (reason) { states[r.id] = ["stale", reason]; kinds[r.id] = kind || "refs"; }
                else if (clip.continue && index > 1) {
                    if (!living.has(r.parent)) {
                        const exists = existingParents.has(r.parent);
                        states[r.id] = ["stale", exists ? _t("check.the_take_of_clip_it_continues", { v0: index - 1 }) : _t("check.the_take_of_clip_it_continues_2", { v0: index - 1 })];
                        kinds[r.id] = exists ? "parent_stale" : "parent_missing";
                    }
                    else if (r.parent !== previous.chosen) states[r.id] = ["other", _t("check.continues_take_of_clip", { parent: r.parent, v1: index - 1 })];
                    else states[r.id] = ["ok", ""];
                } else states[r.id] = ["ok", ""];
            }
            const usable = Object.entries(states).filter(([, s]) => s[0] === "ok").map(([id]) => id);
            const wanted = selection[index];
            const chosen = usable.includes(wanted) ? wanted : (usable.length ? usable[usable.length - 1] : null);
            result[index] = { chosen, takes: states, kinds };
        });
        return result;
    }
    // the branch of a take (record.studio.branch)
    function takeBranch(r, def) { return (r.studio && r.studio.branch) || def || null; }
    function usablePrefix(plan, resolved) {
        let count = 0;
        for (let i = 1; i <= (plan.clips || []).length; i++) { if (!resolved[i] || !resolved[i].chosen) break; count = i; }
        return count;
    }

    return {
        FPS, MAX_CLIPS, SOFT_MAX_FRAMES, DEFAULT_CONTEXT, DEFAULT_FEATHER, SECTIONS, NAME_RE, MODES,
        CONTINUE_SENTENCE, FREE_CONTINUE_SUFFIX, HIDDEN_LEADIN_FREE, HIDDEN_LEADIN_MUSIC,
        isRun, largestRun, isAvBoundary, avContextValues, mode, placeholders, timeline, framesLegal, validate,
        PLAN_VERSION, startVideo, startRow, finalStart, songOffset, pyRound, editVideo, editSlice, editCuts, EDIT_MAX_FRAMES, EDIT_MARK, expandEdit, expandedClip, editClipCount,
        parseSections, composeSections, skeleton, renameRef, referenceKinds, contextOf, squash,
        pyDumps, takeFingerprints, resolveTakes, takeBranch, usablePrefix, sha256Plain,
    };
})();
if (typeof module !== "undefined") module.exports = H3;
