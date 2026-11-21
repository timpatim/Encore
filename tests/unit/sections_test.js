global.H3 = require("../../ui/plan_core.js");
const X = require("../../ui/plan_sections.js");
const assert = require("assert");
const prompt = H3.composeSections([
  "<Subject 1> is the robot whose body comes from {picture:robot}.\n<Subject 2> is the beach from {picture:beach}.",
  "[reference generation] <Subject 1> dances on <Subject 2>.",
  "<Subject 1> (appears throughout [Shot 1]): fully_preserved - same robot\n<Subject 2> (appears throughout [Shot 1]): fully_preserved - same place",
  "Warm cinematic.\n[Shot 1] " + H3.CONTINUE_SENTENCE + " <Subject 1> sways.",
  "Waves.", ""]);
const clip = { prompt, continue: true, refs: ["robot", "beach"] };
const parts = H3.parseSections(prompt);
const names = X.subjectNames(clip, parts);
assert.deepStrictEqual(names, ["robot", "beach"]);
// round trips
for (let k = 0; k < 6; k++) assert.strictEqual(X.toPrompt(X.toDisplay(parts[k], names), names), parts[k]);
const d = parts.map((p) => X.toDisplay(p, names));
const s = X.parseSubjects(d[0], names);
assert.strictEqual(X.toPrompt(X.composeSubjects(s.rows, s.extra), names), parts[0]);
const r = X.parseRetention(d[2]);
assert.strictEqual(r.length, 2);
assert.strictEqual(X.toPrompt(X.composeRetention(r), names), parts[2]);
const det = X.parseDetailed(d[3]);
assert.strictEqual(det.found, H3.CONTINUE_SENTENCE);
assert.strictEqual(X.toPrompt(X.composeDetailed(det.style, det.shots, X.expectedSentence(clip, 2, false)), names), parts[3]);
const sum = X.splitSummary(d[1]);
assert.strictEqual(X.toPrompt(X.composeSummary(sum.text), names), parts[1]);
// renumber
const swapped = X.remapSubjects(prompt, (k) => (k === 1 ? 2 : k === 2 ? 1 : k));
assert.ok(swapped.includes("<Subject 2> is the robot"));
// inherited
const inh = X.inheritedPrompt(clip, { continue: true }, 3, false);
const ip = H3.parseSections(inh);
assert.strictEqual(ip[0], parts[0]); assert.strictEqual(ip[2], parts[2]);
assert.strictEqual(ip[1], "[reference generation]");
assert.ok(ip[3].startsWith("Warm cinematic.\n[Shot 1] " + H3.CONTINUE_SENTENCE));
assert.strictEqual(ip[4], "Waves."); assert.strictEqual(ip[5], "");
// names fallback, unknown mention
assert.deepStrictEqual(X.subjectNames({ prompt: "<Subject 3> x" }, null), ["s1", "s2", "s3"]);
assert.deepStrictEqual(X.unknownMentions("@robot and @robo", names), ["robo"]);
// free form retention -> null
assert.strictEqual(X.parseRetention("something else"), null);
console.log("sections ok");
