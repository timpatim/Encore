// ---------------------------------------------------------------------------------------------
// H3 Clip Plan - plan logic (pure functions, port of core.py v7: timing and checks; the H3 prompt itself is composed by
// the server, POST /plan/compose). No DOM access in this part.
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
    const PLAN_KEYS = new Set(["version", "project", "mode", "files", "subjects", "width", "height", "context_frames",
        "crossfade_frames", "audio_feather_ticks", "seed", "ref_image_size", "song", "clips", "notes", "start_video", "edit_video"]);
    const START_VIDEO_KEYS = new Set(["ref", "start", "end", "in_assembly", "song"]);
    const START_SONG_CHOICES = ["with_video", "after_video"];
    const EDIT_VIDEO_KEYS = new Set(["ref", "start", "end", "sound", "instruction"]);
    const EDIT_SOUND_CHOICES = ["original", "h3"];
    const EDIT_MIN_FRAMES = 48, EDIT_MAX_FRAMES = 360;    // a reference video lasts 2 to 15 s
    const PLAN_VERSION = 7;
    const CLIP_KEYS = new Set(["name", "frames", "continue", "anchors", "subjects", "summary", "description", "soundscape", "music",
        "prompt_override", "defs", "seed", "lyrics", "dialogue", "notes"]);
    const FILE_KINDS = ["image", "voice", "video"];
    const SUBJECT_KINDS = ["person", "place", "object", "outfit", "style", "action", "pose"];
    const KEEPS = ["identical", "partial", "attribute", "loose"], VOICE_KEEPS = ["exact", "partial", "timbre", "loose"];
    const TEXT_KEYS = ["summary", "description", "soundscape", "music"];
    // @name in a text (core.MENTION_RE): letters of any alphabet, digits, '_' and '-', not ending with '-'
    const mentionRe = () => /(?<![\p{L}\p{N}_@])@([\p{L}\p{N}](?:[\p{L}\p{N}_-]*[\p{L}\p{N}_])?)/gu;
    const SUBJECT_NAME_RE = /^[\p{L}\p{N}](?:[\p{L}\p{N}_-]*[\p{L}\p{N}_])?$/u;
    const DIALOGUE_KEYS = new Set(["speaker", "text", "language"]);


    const isInt = (v) => typeof v === "number" && Number.isInteger(v);
    const isRun = (f) => isInt(f) && f >= 5 && (f - 5) % 17 === 0;
    const largestRun = (f) => (f < 5 ? 0 : 5 + Math.floor((f - 5) / 17) * 17);
    const nearestRuns = (f) => { const low = Math.max(5, largestRun(f)); return [low, low + 17]; };
    const snapContext = (req, prev, f) => largestRun(Math.min(req, prev, f - 1));
    const isAvBoundary = (f) => (f * 40) % FPS === 0;
    const avContextValues = () => { const out = []; for (let n = 5; n <= 243; n += 17) if (isAvBoundary(n)) out.push(n); return out; };
    const mode = (plan) => (plan && MODES.includes(plan.mode) ? plan.mode : "music_video");

    function mentions(text) {
        const out = [];
        for (const m of String(text || "").matchAll(mentionRe())) if (!out.includes(m[1])) out.push(m[1]);
        return out;
    }
    // the files and subjects a clip sees: the plan's, with its own 'defs' on top (core.clip_definitions)
    function definitions(plan, clip) {
        const defs = clip && clip.defs && typeof clip.defs === "object" ? clip.defs : {};
        return { files: { ...((plan && plan.files) || {}), ...(defs.files || {}) }, subjects: { ...((plan && plan.subjects) || {}), ...(defs.subjects || {}) } };
    }
    // the subjects a clip names (core.mentioned_subjects): edit instruction, summary, description, soundscape, music (or
    // only its prompt written by hand), then the speakers of its dialogue
    function clipSubjects(plan, clip, index) {
        const own = clip && clip.defs && typeof clip.defs === "object" && "edit_instruction" in clip.defs ? clip.defs.edit_instruction : undefined;
        const instruction = index && editSlice(plan, index) ? (own !== undefined ? own : instructionOf(plan)) : null;
        let texts = [instruction || "", ...TEXT_KEYS.map((k) => String((clip || {})[k] || ""))];
        if (typeof (clip || {}).prompt_override === "string" && clip.prompt_override.trim()) texts = [clip.prompt_override];
        const out = [];
        for (const t of texts) for (const n of mentions(t)) if (!out.includes(n)) out.push(n);
        for (const d of (clip || {}).dialogue || []) if (d && typeof d.speaker === "string" && d.speaker && !out.includes(d.speaker)) out.push(d.speaker);
        return out;
    }
    // the pictures (then anchors) and voices of a clip, in the order the server numbers them (core.compose_clip)
    function clipFiles(plan, clip, index) {
        const { subjects } = definitions(plan, clip);
        const names = clipSubjects(plan, clip, index).filter((n) => n in subjects);
        const pictures = [], voices = [];
        for (const n of names) for (const p of subjects[n].pictures || []) if (p && p.file && !pictures.includes(p.file)) pictures.push(p.file);
        const a = (clip && clip.anchors) || {};
        const keys = [...(a.keyframes || [])].filter((k) => k && k.file).sort((x, y) => (x.at || 0) - (y.at || 0));
        for (const f of [a.first, ...keys.map((k) => k.file), a.last]) if (f && !pictures.includes(f)) pictures.push(f);
        if (mode(plan) === "free") for (const n of names) { const v = subjects[n].voice; if (v && !voices.includes(v)) voices.push(v); }
        return { subjects: names, pictures, voices };
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
    const instructionOf = (plan) => (plan && plan.edit_video && typeof plan.edit_video.instruction === "string" ? plan.edit_video.instruction : null);
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

    function checkFiles(files, err, n) {
        if (!files || typeof files !== "object" || Array.isArray(files)) { err(_t("check.files_must_be_an_object"), n); return {}; }
        const out = {};
        for (const [name, item] of Object.entries(files)) {
            if (!NAME_RE.test(name)) { err(_t("check.file_label_letters_digits", { name }), n); continue; }
            if (!item || typeof item !== "object" || !FILE_KINDS.includes(item.kind)) { err(_t("check.file_kind", { name }), n); continue; }
            out[name] = item;
        }
        return out;
    }
    function checkSubjects(subjects, files, err, n) {
        if (!subjects || typeof subjects !== "object" || Array.isArray(subjects)) { err(_t("check.subjects_must_be_an_object"), n); return {}; }
        const out = {};
        for (const [name, item] of Object.entries(subjects)) {
            if (!SUBJECT_NAME_RE.test(name)) { err(_t("check.subject_name_chars", { name }), n); continue; }
            if (!item || typeof item !== "object") { err(_t("check.subject_must_be_an_object", { name }), n); continue; }
            if (!SUBJECT_KINDS.includes(item.kind ?? "person")) err(_t("check.subject_kind", { name }), n);
            for (const p of item.pictures || []) if (!p || (files[p.file] || {}).kind !== "image") err(_t("check.subject_picture_not_image", { name, file: String(p && p.file) }), n);
            if (item.voice != null && (files[item.voice] || {}).kind !== "voice") err(_t("check.subject_voice_not_voice", { name, file: String(item.voice) }), n);
            out[name] = item;
        }
        return out;
    }
    // the v7 fields of a clip; what needs the composed prompt (a prompt written by hand) is checked by the server
    function checkClip(plan, clip, n, planFiles, planSubjects, free, err, warn) {
        let files = planFiles, subjects = planSubjects;
        if (clip.defs !== undefined) {
            if (!clip.defs || typeof clip.defs !== "object") err(_t("check.defs_must_be_an_object"), n);
            else {
                files = { ...planFiles, ...checkFiles(clip.defs.files ?? {}, err, n) };
                subjects = { ...planSubjects, ...checkSubjects(clip.defs.subjects ?? {}, files, err, n) };
            }
        }
        for (const k of TEXT_KEYS) if (clip[k] !== undefined && typeof clip[k] !== "string") err(_t("check.text_field", { key: k }), n);
        const override = typeof clip.prompt_override === "string" && clip.prompt_override.trim();
        if (!override && !String(clip.summary || "").trim() && !String(clip.description || "").trim()) err(_t("check.clip_needs_a_text"), n);
        const named = clipSubjects(plan, clip, n);
        for (const name of named) if (!(name in subjects)) err(_t("check.unknown_subject", { name }), n);
        const seen = new Set();
        for (const u of Array.isArray(clip.subjects) ? clip.subjects : []) {
            if (!u || typeof u.name !== "string") { err(_t("check.subject_setting_needs_a_name"), n); continue; }
            if (seen.has(u.name)) err(_t("check.subject_set_twice", { name: u.name }), n);
            seen.add(u.name);
            if (!(u.name in subjects)) err(_t("check.unknown_subject", { name: u.name }), n);
            else if (!named.includes(u.name)) warn(_t("check.subject_not_mentioned", { name: u.name }), n);
            if (!KEEPS.includes(u.keep ?? "identical")) err(_t("check.subject_keep", { name: u.name }), n);
            if (!VOICE_KEEPS.includes(u.voice_keep ?? "timbre")) err(_t("check.subject_voice_keep", { name: u.name }), n);
        }
        const a = clip.anchors ?? {};
        const image = (f) => (files[f] || {}).kind === "image";
        if (typeof a !== "object" || Array.isArray(a)) err(_t("check.anchors_must_be_an_object"), n);
        else {
            for (const k of ["first", "last"]) if (a[k] != null && !image(a[k])) err(_t("check.anchor_not_image", { which: _t("check.anchor_" + k) }), n);
            const continues = !!clip.continue && (n > 1 || !!plan.start_video);
            if (a.first && continues) err(_t("check.anchor_first_on_continue"), n);
            const secs = isRun(clip.frames) ? clip.frames / FPS : null;
            for (const k of a.keyframes || []) {
                if (!k || !image(k.file)) err(_t("check.anchor_not_image", { which: _t("check.anchor_keyframe") }), n);
                else if (!isNumber(k.at) || k.at <= 0 || (secs !== null && k.at >= secs)) err(_t("check.keyframe_inside", { v0: secs === null ? "?" : secs.toFixed(3) }), n);
            }
        }
        const sub = { files, subjects };
        const got = clipFiles({ ...plan, files: sub.files, subjects: sub.subjects }, { ...clip, defs: undefined }, n);
        if (got.pictures.length > MAX_REFS) err(_t("check.too_many_pictures", { count: got.pictures.length, max: MAX_REFS }), n);
        if (got.voices.length > MAX_VOICES) err(_t("check.too_many_voices", { count: got.voices.length, max: MAX_VOICES }), n);
        if (got.pictures.length + got.voices.length + (editSlice(plan, n) ? 1 : 0) > MAX_REF_FILES) err(_t("check.too_many_files", { max: MAX_REF_FILES }), n);
        if (!free && named.some((x) => subjects[x] && subjects[x].voice)) warn(_t("check.voices_ignored_music_video"), n);
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
        if (version !== PLAN_VERSION) err(_t("check.version_must_be_7"));
        if ("mode" in plan && !MODES.includes(plan.mode)) err(_t("check.mode_must_be_music_video_or", { v0: JSON.stringify(plan.mode) }));
        const free = mode(plan) === "free";
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

        const filesMap = checkFiles(plan.files ?? {}, err, 0);
        const subjectsMap = checkSubjects(plan.subjects ?? {}, filesMap, err, 0);
        const isVideo = (ref) => typeof ref === "string" && (filesMap[ref] || {}).kind === "video";

        const sv = plan.start_video;
        if (sv !== undefined && sv !== null) {
            if (typeof sv !== "object" || Array.isArray(sv)) err(_t("check.start_video_must_be_an_object"));
            else {
                for (const key of Object.keys(sv)) if (!START_VIDEO_KEYS.has(key) && !key.startsWith("_")) warn(_t("check.start_video_unknown_key", { key }));
                if (!isVideo(sv.ref)) err(_t("check.start_video_ref_not_declared", { ref: String(sv.ref) }));
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
                if (!isVideo(ev.ref)) err(_t("check.edit_video_ref_not_declared", { ref: String(ev.ref) }));
                const start = ev.start ?? 0;
                if (!isNumber(start) || start < 0) err(_t("check.edit_video_start_must_be"));
                else if (!isNumber(ev.end) || ev.end <= start) err(_t("check.edit_video_end_must_be"));
                else {
                    if (ev.instruction !== undefined && ev.instruction !== null) {
                        if (typeof ev.instruction !== "string") err(_t("check.edit_instruction_must_be_text"));
                        else for (const n of mentions(ev.instruction)) if (!(n in subjectsMap)) err(_t("check.edit_instruction_unknown_subject", { name: n }));
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

            checkClip(plan, clip, n, filesMap, subjectsMap, free, err, warn);

            if (clip.lyrics && free) warn(_t("check.lyrics_is_for_music_video_mode"), n);
            let dialogue = clip.dialogue ?? [];
            if (dialogue.length && !free) warn(_t("check.lines_are_only_checked_in_free"), n);
            if (!Array.isArray(dialogue)) { err(_t("check.dialogue_must_be_a_list_of"), n); dialogue = []; }
            let words = 0;
            dialogue.forEach((line, k) => {
                const where = _t("check.line", { v0: k + 1 });
                if (!line || typeof line !== "object") { err(_t("check.must_be_an_object_with_speaker", { where }), n); return; }
                for (const key of Object.keys(line)) if (!DIALOGUE_KEYS.has(key) && !key.startsWith("_")) warn(_t("check.unknown_key_ignored_2", { where, key }), n);
                if (typeof line.speaker !== "string" || !(line.speaker in definitions(plan, clip).subjects)) err(_t("check.the_speaker_must_be_a_subject", { where, v1: JSON.stringify(line.speaker) }), n);
                if (typeof line.text !== "string" || !line.text.trim()) { err(_t("check.empty_text", { where }), n); return; }
                words += line.text.trim().split(/\s+/).length;
                const said = [...TEXT_KEYS.map((k) => clip[k] || ""), clip.prompt_override || ""].join(" ");
                if (!squash(said).includes(squash(line.text))) warn(_t("check.this_text_is_not_in_the", { where }), n);
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
                } else if (TEXT_KEYS.some((key) => /<Video \d+>/.test(plan.clips[k][key] || ""))) err(_t("check.edit_video_tag_after_segment"), row.index);
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

    const CONTINUE_SENTENCE = "The incoming performer motion, camera trajectory, body momentum, facial state, lighting, environment and object state continue uninterrupted from the protected video context.";
    const FREE_CONTINUE_SUFFIX = " The protected sound continues too; nothing in that context is repeated.";
    const HIDDEN_LEADIN_FREE = "Hidden lead-in for the first 1.6 seconds: the scene is already fully established, nobody speaks.";
    const HIDDEN_LEADIN_MUSIC = "The first second and a half of this clip is a lead-in that overlaps the end of the previous song phrase; the scene is already fully established from the first frame.";

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
        isRun, largestRun, isAvBoundary, avContextValues, mode, timeline, framesLegal, validate,
        PLAN_VERSION, startVideo, startRow, finalStart, songOffset, pyRound, editVideo, editSlice, editCuts, EDIT_MAX_FRAMES, editClipCount,
        contextOf, squash, mentions, mentionRe, definitions, clipSubjects, clipFiles, instructionOf,
        FILE_KINDS, SUBJECT_KINDS, KEEPS, VOICE_KEEPS, TEXT_KEYS, SUBJECT_NAME_RE, MAX_REFS, MAX_VOICES, MAX_REF_FILES,
        takeBranch, usablePrefix,
    };
})();
if (typeof module !== "undefined") module.exports = H3;
