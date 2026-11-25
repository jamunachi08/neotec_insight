"""v3.9.11 — the General Ledger lists accounts in chart-of-accounts tree order
(screen, print, PDF and Excel all come from the same server order), whatever
order the accounts were picked in. Reported: an export listing 5/… accounts,
then 4/… accounts in between them."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import _fakefrappe as ff  # noqa: E402

APP = HERE.parents[0] / "neotec_insight"

EXPORTED = [   # the order in the reported export
    "5/1/01/01/004 - Customer Success & Operations - DSC", "5/1/01/01/005 - Direct Third Party Costs - DSC",
    "5/1/01/01/006 - Cameras - DSC", "4/1/01/01/001 - Software/Subscription Revenue - DSC",
    "4/1/01/01/003 - Camera & Training revenues - DSC", "5/1/01/01/003 - Internal Engineering - DSC",
    "5/1/01/01/007 - Devices and Tools - DSC", "4/1/01/02/001 - Support دعم - DSC",
    "5/1/01/01/001 - Hosting Expenses مصاريف استضافة - DSC",
    "4/1/01/02/002 - Others Revenue - Government Grant إيرادات أخرى - منح حكومية - DSC",
]
PARENTS = {
    "4/0/00/00/000 - Income - DSC": None, "5/0/00/00/000 - Expenses - DSC": None,
    "4/1/01/00/000 - Revenue - DSC": "4/0/00/00/000 - Income - DSC",
    "5/1/01/00/000 - Direct Costs - DSC": "5/0/00/00/000 - Expenses - DSC",
    **{n: ("4/1/01/00/000 - Revenue - DSC" if n.startswith("4") else "5/1/01/00/000 - Direct Costs - DSC")
       for n in EXPORTED},
}


class TreeOrder(unittest.TestCase):
    def setUp(self):
        self.site = ff.install()
        self.addCleanup(ff.uninstall)

    def test_reported_export_comes_out_in_tree_order(self):
        from neotec_insight.neotec_insight.utils.account_order import sort_by_tree
        out = sort_by_tree(EXPORTED, PARENTS)
        self.assertEqual([n[:13] for n in out], [
            "4/1/01/01/001", "4/1/01/01/003", "4/1/01/02/001", "4/1/01/02/002",
            "5/1/01/01/001", "5/1/01/01/003", "5/1/01/01/004", "5/1/01/01/005", "5/1/01/01/006", "5/1/01/01/007"])

    def test_parents_decide_before_names(self):
        from neotec_insight.neotec_insight.utils.account_order import sort_by_tree
        parents = {"B group": None, "A group": None, "Zeta": "A group", "Alpha": "B group"}
        self.assertEqual(sort_by_tree(["Alpha", "Zeta"], parents), ["Zeta", "Alpha"])     # A group first
        parents["loop"] = "loop"
        self.assertEqual(sort_by_tree(["loop", "Zeta"], parents)[0], "Zeta")              # no endless loop

    def test_reads_the_chart_and_the_ledger_uses_it(self):
        for n, p in PARENTS.items():
            self.site.table("Account")[n] = {"name": n, "parent_account": p, "company": "DSC"}
        from neotec_insight.neotec_insight.utils.account_order import in_tree_order
        out = in_tree_order(list(EXPORTED))
        self.assertEqual(out[0][:13], "4/1/01/01/001")
        self.assertEqual(out[-1][:13], "5/1/01/01/007")
        src = (APP / "api" / "report.py").read_text()
        self.assertIn("leaf_accounts = in_tree_order(leaf_accounts)", src)


if __name__ == "__main__":
    unittest.main()
