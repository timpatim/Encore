// the SHA-256 written out gives the same digests as node's crypto
const H3 = require("../../ui/plan_core.js");
const crypto = require("crypto");
const samples = ["", "abc", "é𝄞 Ünïcode", "x".repeat(55), "x".repeat(56), "x".repeat(64), "y".repeat(1000), JSON.stringify(require("../fixtures/rue_test_v1.plan.json"))];
let bad = 0;
for (const s of samples) {
    const bytes = new TextEncoder().encode(s);
    const want = crypto.createHash("sha256").update(bytes).digest("hex");
    if (H3.sha256Plain(bytes) !== want) { bad++; console.log("MISMATCH", JSON.stringify(s.slice(0, 20)), s.length); }
}
console.log(bad ? `${bad} mismatch(es)` : `sha256Plain OK on ${samples.length} samples`);
process.exit(bad ? 1 : 0);
