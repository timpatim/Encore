// Reads {plan, fingerprints, cases: [{takes, selection, current}]} on stdin, prints the JS resolution of every case.
const H3 = require("../../ui/plan_core.js");
let input = "";
process.stdin.on("data", (d) => { input += d; });
process.stdin.on("end", () => {
    const d = JSON.parse(input);
    const out = d.cases.map((c) => {
        const r = H3.studioResolveTakes(d.plan, c.takes, c.selection, d.fingerprints, c.current);
        const clips = {};
        for (const [i, v] of Object.entries(r)) {
            if (i === "branch") continue;
            clips[i] = { chosen: v.chosen || null, states: Object.fromEntries(Object.entries(v.takes).map(([k, s]) => [k, s[0]])) };
        }
        return { branch: r.branch || null, clips };
    });
    process.stdout.write(JSON.stringify(out));
});
