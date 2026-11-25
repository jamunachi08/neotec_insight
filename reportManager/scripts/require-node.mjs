// v3.9.10 — the front-end build and its tests need Node 22.6+ (they run
// TypeScript test fixtures directly). Declared as devEngines, not engines:
// Frappe Cloud checks `engines` against the bench's Node when it installs the
// app, and the bench never builds this front end (the built files ship in
// neotec_insight/public/insight). Written to run on any Node, so an older one
// gets this message instead of a syntax error.
var v = process.versions.node.split('.').map(Number);
if (v[0] < 22 || (v[0] === 22 && v[1] < 6)) {
  console.error('Neotec Insight front end: Node 22.6 or later is needed to build and test (found ' +
    process.versions.node + '). The built files are already in neotec_insight/public/insight; ' +
    'a Frappe bench does not need to build them.');
  process.exit(1);
}
