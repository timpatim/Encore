// ---------------------------------------------------------------------------------------------
// H3 Clip Plan - plan logic (pure functions, port of core.py v3). No DOM access in this part.
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
        "crossfade_frames", "audio_feather_ticks", "seed", "ref_image_size", "song", "clips", "notes"]);
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

    function contextOf(plan) {
        const c = plan.context_frames ?? DEFAULT_CONTEXT;
        return isRun(c) ? c : DEFAULT_CONTEXT;
    }

    // Per-clip timing. Only meaningful when every frames value is legal.
    function timeline(plan) {
        const rows = [];
        let prev = null;
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
        if (![1, 2, 3].includes(version)) err(_t("check.version_must_be_3"));
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
            else if (cont && n === 1) err(_t("check.clip_1_cannot_be_a_continuation"));

            let refs = clip.refs ?? [];
            if (!Array.isArray(refs) || !refs.every((r) => typeof r === "string")) { err(_t("check.refs_must_be_a_list_of"), n); refs = []; }
            if (new Set(refs).size !== refs.length) err(_t("check.a_reference_is_listed_twice"), n);
            const limit = free ? MAX_REF_FILES : MAX_REFS;
            if (refs.length > limit) err(_t("check.at_most_references_per_clip_found", { limit, length: refs.length }), n);
            for (const ref of refs) {
                if (!NAME_RE.test(ref)) err(_t("check.reference_name_letters_digits_and_only", { ref }), n);
                else if (declared.length && !declared.includes(ref)) err(_t("check.the_reference_is_not_declared_in", { ref }), n);
            }
            if (!refs.length) warn(_t("check.no_reference_the_clip_will_be"), n);

            let prompt = clip.prompt;
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

        if (framesOk && !out.some((m) => m.level === "error")) {
            const rows = timeline(plan);
            if (songDuration !== null) {
                for (const row of rows) {
                    if (row.end / FPS > songDuration + 1 / FPS) err(_t("check.ends_at_s_after_the_end", { v0: (row.end / FPS).toFixed(3), v1: songDuration.toFixed(3) }), row.index);
                }
                const last = rows[rows.length - 1].end / FPS;
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
        for (const clip of plan.clips || []) {
            if (Array.isArray(clip.refs)) clip.refs = clip.refs.map((r) => (r === oldName ? newName : r));
            if (typeof clip.prompt === "string") clip.prompt = clip.prompt.replace(re, (_m, kind) => `{${kind}:${newName}}`);
            if (Array.isArray(clip.dialogue)) for (const d of clip.dialogue) if (d && d.speaker === oldName) d.speaker = newName;
        }
    }

    function referenceKinds(plan, name) {
        const kinds = new Set();
        for (const clip of plan.clips || []) {
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
            const clip = plan.clips[row.index - 1];
            const payload = {
                frames: clip.frames, continue: !!clip.continue, refs: [...(clip.refs || [])], prompt: clip.prompt,
                raw_start: row.raw_start, context: row.context, mode: mode(plan),
            };
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
                for (const kind of ["image", "voice"]) currentRefs.set(`${name}\u0000${kind}`, (kinds || {})[kind] ?? null);
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
                        for (const kind of ["image", "voice"]) {
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
    // H3 Studio rules (same as takes.py studio_resolve; keep both identical). Every take belongs to a branch
    // (record.studio.branch), which holds its reference files and song. A take is "invalid" when something it was
    // made with differs from the project now (undone by putting the old value back), or from a more recent take that
    // shares it (final), or when the take it continues is invalid or missing. Takes of another branch than the
    // selected one are "other".
    // selection: {index: id, branch: id}; current: {branches: {id: {refs: {name: {image, voice}}, song, size: [w, h]}},
    // default_branch}; fingerprints: {index: take fingerprint}. The result also has .branch (the selected branch).
    function takeBranch(r, def) { return (r.studio && r.studio.branch) || def || null; }
    function studioResolveTakes(plan, takes, selection, fingerprints, current) {
        const free = mode(plan) === "free";
        const def = current.default_branch || null;
        const sel = { ...(selection || {}) };
        const wantedBranch = sel.branch || null;
        delete sel.branch;
        const J = (v) => JSON.stringify(v === undefined ? null : v);
        const now = {};
        (plan.clips || []).forEach((clip, k) => { now[`plan:${k + 1}`] = J([fingerprints[k + 1], clip.frames]); });
        for (const [bid, bset] of Object.entries(current.branches || {})) {
            for (const [name, kinds] of Object.entries((bset && bset.refs) || {})) {
                now[`${bid}|image:${name}`] = J((kinds || {}).image ?? null);
                now[`${bid}|voice:${name}`] = J((kinds || {}).voice ?? null);
            }
            now[`${bid}|song`] = J((bset || {}).song ?? null);
            now[`${bid}|size`] = J((bset || {}).size || [null, null]);
            now[`${bid}|refsize`] = J((bset || {}).ref_image_size ?? null);
        }
        const keysOf = (r, index, branch) => {
            const st = r.studio || {};
            const keys = { [`${branch}|size`]: J([r.width ?? null, r.height ?? null]),
                [`${branch}|refsize`]: J(st.ref_image_size || current.legacy_ref_image_size || "match"),
                [`plan:${index}`]: J([r.fingerprint ?? null, r.frames ?? null]) };
            const refs = st.refs || {};
            for (const name of Object.keys(refs).sort()) {
                keys[`${branch}|image:${name}`] = J((refs[name] || {}).image ?? null);
                if (free) keys[`${branch}|voice:${name}`] = J((refs[name] || {}).voice ?? null);
            }
            if (!free && "song" in st) keys[`${branch}|song`] = J(st.song ?? null);
            return keys;
        };
        const reason = (key, final) => {
            const k = key.includes("|") ? key.slice(key.indexOf("|") + 1) : key;
            const [kind, ...rest] = k.split(":");
            const name = rest.join(":");
            const what = { size: _t("check.the_picture_size"), refsize: _t("check.the_reference_size"), plan: _t("check.the_clip_s_plan"), image: _t("check.the_picture_of", { name }), voice: _t("check.the_voice_of", { name }), song: _t("check.the_song") }[kind];
            return final ? _t("check.redone_since_with_another_value", { what }) : _t("check.has_changed", { what });
        };
        const records = [], branchOf = {};
        for (const [index, list] of Object.entries(takes)) {
            for (const r of list) {
                const b = takeBranch(r, def);
                branchOf[r.id] = b;
                records.push([+index, r, keysOf(r, +index, b)]);
            }
        }
        records.sort((a, b) => (a[1].saved_at || 0) - (b[1].saved_at || 0));
        const why = {};
        for (const [, r, keys] of records) {
            for (const [key, value] of Object.entries(keys)) {
                if (value !== (now[key] ?? "null")) { if (!(r.id in why)) why[r.id] = reason(key, false); break; }
            }
        }
        const later = {};
        for (const [, r, keys] of [...records].reverse()) {
            for (const [key, value] of Object.entries(keys)) {
                const seen = later[key] = later[key] || [];
                if (seen.some((v) => v !== value)) why[r.id] = reason(key, true);
                if (!seen.includes(value)) seen.push(value);
            }
        }
        const branches = new Set(Object.values(branchOf));
        let active = branches.has(wantedBranch) ? wantedBranch : null;
        if (active === null) {
            for (const index of Object.keys(sel).map(Number).sort((a, b) => a - b)) {
                if (sel[index] in branchOf) { active = branchOf[sel[index]]; break; }
            }
        }
        if (active === null) {
            const first = records.filter(([i, r]) => i === 1 && !(r.id in why));
            active = first.length ? branchOf[first[first.length - 1][1].id] : (branches.size ? [...branches].sort()[0] : null);
        }
        const result = {};
        (plan.clips || []).forEach((clip, k) => {
            const index = k + 1;
            const previous = result[index - 1];
            const states = {};
            const list = [...(takes[index] || [])].sort((a, b) => (a.saved_at || 0) - (b.saved_at || 0));
            for (const r of list) {
                if (r.id in why) { states[r.id] = ["invalid", why[r.id]]; continue; }
                if (clip.continue && index > 1) {
                    const ps = previous ? previous.takes[r.parent] : undefined;
                    if (!ps) { states[r.id] = ["invalid", _t("check.the_take_it_continues_does_not")]; continue; }
                    if (ps[0] === "invalid") { states[r.id] = ["invalid", _t("check.built_on_an_invalidated_take")]; continue; }
                }
                if (branchOf[r.id] !== active) states[r.id] = ["other", _t("check.other_branch")];
                else if (clip.continue && index > 1 && r.parent !== previous.chosen) states[r.id] = ["other", _t("check.built_on_another_take_of_the")];
                else states[r.id] = ["ok", ""];
            }
            let chosen = sel[index];
            if (!states[chosen] || states[chosen][0] !== "ok") {
                const ok = Object.entries(states).filter(([, st]) => st[0] === "ok").map(([id]) => id);
                chosen = ok.length ? ok[ok.length - 1] : null;
            }
            result[index] = { chosen, takes: states, kinds: {} };
        });
        Object.defineProperty(result, "branch", { value: active, enumerable: false });
        return result;
    }
    function usablePrefix(plan, resolved) {
        let count = 0;
        for (let i = 1; i <= (plan.clips || []).length; i++) { if (!resolved[i] || !resolved[i].chosen) break; count = i; }
        return count;
    }

    return {
        FPS, MAX_CLIPS, SOFT_MAX_FRAMES, DEFAULT_CONTEXT, DEFAULT_FEATHER, SECTIONS, NAME_RE, MODES,
        CONTINUE_SENTENCE, FREE_CONTINUE_SUFFIX, HIDDEN_LEADIN_FREE, HIDDEN_LEADIN_MUSIC,
        isRun, largestRun, isAvBoundary, avContextValues, mode, placeholders, timeline, framesLegal, validate,
        parseSections, composeSections, skeleton, renameRef, referenceKinds, contextOf, squash,
        pyDumps, takeFingerprints, resolveTakes, studioResolveTakes, takeBranch, usablePrefix, sha256Plain,
    };
})();
if (typeof module !== "undefined") module.exports = H3;
