"""v3.9.10 — Frappe Cloud checks the app's package.json `engines.node` against
the bench's Node (18.16 on the deploying bench) before it builds the image.
The bench never builds Insight's front end (the built files ship with the app),
so the build requirement must not be declared there."""
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FRONT = REPO / "reportManager"


class BenchNode(unittest.TestCase):
    def test_no_engines_constraint_a_bench_would_reject(self):
        for pkg in [p for p in REPO.rglob("package.json") if "node_modules" not in p.parts]:
            d = json.loads(pkg.read_text())
            self.assertNotIn("engines", d, pkg)
        lock = json.loads((FRONT / "package-lock.json").read_text())
        self.assertNotIn("engines", lock["packages"][""])

    def test_build_requirement_still_declared_and_enforced(self):
        d = json.loads((FRONT / "package.json").read_text())
        self.assertEqual(d["devEngines"]["runtime"]["version"], ">=22.6.0")
        for s in ("build", "check"):
            self.assertTrue(d["scripts"][s].startswith("node scripts/require-node.mjs && "), s)
        guard = (FRONT / "scripts" / "require-node.mjs").read_text()
        self.assertNotIn("=>", guard)                     # runs on old Node to print its message
        self.assertIn("22", (FRONT / ".nvmrc").read_text())

    def test_built_front_end_ships_with_the_app(self):
        assets = REPO / "neotec_insight" / "public" / "insight" / "assets"
        self.assertTrue(list(assets.glob("index-*.js")))


if __name__ == "__main__":
    unittest.main()
