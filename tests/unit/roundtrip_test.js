global.H3 = require("../../ui/plan_core.js");
const X = require("../../ui/plan_sections.js");
const fs = require("fs");
const files = process.argv.slice(2);
let n = 0, diffs = 0;
for (const f of files) {
  let plan; try { plan = JSON.parse(fs.readFileSync(f, "utf8")); } catch (e) { continue; }
  if (!plan.clips) continue;
  const free = H3.mode(plan) === "free";
  plan.clips.forEach((c, i) => {
    const parts = H3.parseSections(c.prompt);
    if (!parts) { console.log("no sections", f, i + 1); return; }
    const names = X.subjectNames(c, parts);
    const d = parts.map((p) => X.toDisplay(p, names));
    const out = [];
    const s = X.parseSubjects(d[0], names); out[0] = X.composeSubjects(s.rows, s.extra);
    out[1] = X.composeSummary(X.splitSummary(d[1]).text);
    const r = X.parseRetention(d[2]); out[2] = r ? X.composeRetention(r) : d[2];
    const det = X.parseDetailed(d[3]); out[3] = X.composeDetailed(det.style, det.shots, X.openingFor(det));
    out[4] = d[4]; out[5] = d[5];
    out.forEach((t, k) => { n++; const back = X.toPrompt(t, names); if (back !== parts[k]) { diffs++; console.log(`DIFF ${f.split("/").pop()} clip ${i + 1} sec ${k} ret=${!!r} found=${!!det.found}\n  was: ${JSON.stringify(parts[k].slice(0, 200))}\n  now: ${JSON.stringify(back.slice(0, 200))}`); } });
  });
}
console.log(`${n} sections, ${diffs} differ after an edit-without-change`);
process.exit(diffs ? 1 : 0);
