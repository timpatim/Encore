// The plan screen's helpers (plan v7): the subjects a clip names, the files it uses (in the server's order), the
// label of a project file, renaming a subject, the settings of a subject in a clip, the checks of the page.
global.H3 = require("../../ui/plan_core.js");
const X = require("../../ui/plan_sections.js");
const assert = require("assert");
const fresh = () => JSON.parse(JSON.stringify(require("../fixtures/rue_test_v1.plan.json")));

// subjects named by a clip: texts in order, then the speakers of its dialogue
let p = fresh();
assert.deepStrictEqual(H3.clipSubjects(p, p.clips[0], 1), ["fillette", "homme", "rue"]);
assert.deepStrictEqual(H3.mentions("@a, @b-c. mail@x @é_1 @d-"), ["a", "b-c", "é_1", "d"]);
// a prompt written by hand: its own subjects only
assert.deepStrictEqual(H3.clipSubjects(p, { ...p.clips[0], prompt_override: "x @rue", dialogue: [] }, 1), ["rue"]);

// files of a clip, as the server numbers them: pictures of the subjects, then the anchors
p.files.start = { kind: "image", file: "refs/images/start.png" };
p.clips[0].anchors = { first: "start", keyframes: [{ at: 2, file: "rue" }] };
assert.deepStrictEqual(H3.clipFiles(p, p.clips[0], 1).pictures, ["fillette", "rue", "start"]);

// a clip's own definitions win
p.clips[1].defs = { subjects: { fillette: { kind: "person", pictures: [{ file: "start" }] } } };
assert.deepStrictEqual(H3.clipFiles(p, p.clips[1], 2).pictures.slice(0, 1), ["start"]);

// labels of project files: made once, unique, ASCII
p = fresh();
assert.strictEqual(X.fileLabel(p, "refs/images/rue.png", "image"), "rue");
assert.strictEqual(X.fileLabel(p, "refs/images/Été 2.png", "image"), "Ete_2");
assert.strictEqual(X.fileLabel(p, "refs/images/Été 2.png", "image"), "Ete_2");
assert.strictEqual(X.fileLabel(p, "refs/voices/rue.wav", "voice"), "rue_voice");
X.pruneFiles(p);
assert.deepStrictEqual(Object.keys(p.files).sort(), ["fillette", "rue"]);

// renaming a subject: everywhere from clip `from` on, speakers and settings included
p = fresh();
p.clips[2].subjects = [{ name: "fillette", keep: "partial" }];
X.renameSubject(p, "fillette", "léa", 1);
assert.ok(p.clips[0].description.includes("@fillette") && p.clips[1].description.includes("@léa"));
assert.strictEqual(p.clips[1].dialogue.find((d) => d.text.startsWith("Mais")).speaker, "léa");
assert.strictEqual(p.clips[2].subjects[0].name, "léa");
assert.ok("léa" in p.subjects && !("fillette" in p.subjects));

// settings of a subject in a clip: only what differs from the defaults is kept
const c = { };
X.setUse(c, "rue", "keep", "loose", "identical");
assert.deepStrictEqual(c.subjects, [{ name: "rue", keep: "loose" }]);
X.setUse(c, "rue", "keep", "identical", "identical");
assert.strictEqual(c.subjects, undefined);

// the checks of the page
p = fresh();
assert.deepStrictEqual(H3.validate(p), []);
p.clips[1].summary += " @chien";
p.clips[1].anchors = { first: "rue" };
p.clips[2].subjects = [{ name: "rue", keep: "bad" }];
const texts = H3.validate(p).map((m) => `${m.clip} ${m.text}`);
assert.deepStrictEqual(texts, ["2 check.unknown_subject", "2 check.anchor_first_on_continue", "3 check.subject_keep"]);

console.log("plan screen helpers OK");
