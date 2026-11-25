"""v3.9.7 — General Ledger account tree in ERPNext's order (by name)."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import _fakefrappe as ff  # noqa: E402


class AccountTree(unittest.TestCase):
    def setUp(self):
        self.site = ff.install()
        import frappe
        self.frappe = frappe
        self.seen = {}
        frappe.get_all = lambda dt, **k: self.seen.update(k) or []
        from neotec_insight.neotec_insight.api import report
        report._require_read = lambda: None
        self.report = report

    def tearDown(self):
        ff.uninstall()

    def test_ordered_by_name_with_nested_set(self):
        self.report.account_tree("DSC")
        self.assertEqual(self.seen["order_by"], "name asc")
        self.assertTrue({"lft", "rgt", "parent_account", "is_group"} <= set(self.seen["fields"]))


if __name__ == "__main__":
    unittest.main()
