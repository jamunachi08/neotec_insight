"""v3.9.6 — ERPNext's AR/AP report filters on the Payment Ledger ageing (screen and
pack), and ERPNext's General Ledger options on the Statement of Account."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import _fakefrappe as ff  # noqa: E402
from test_v3_7_2_payment_ledger import O, SUPPLIER  # noqa: E402

SRC = HERE.parents[1] / "reportManager" / "src"


class ArApFilters(unittest.TestCase):
    def setUp(self):
        self.site = ff.install()
        import frappe
        self.frappe = frappe
        self.site.table("Company")["DSC"] = {"name": "DSC", "default_currency": "SAR"}
        self.site.table("Supplier")[O] = {"name": O, "supplier_name": "Oracle Systems Limited"}
        self.seen = []

        def sql(q, p=None, as_dict=False):
            if "Payment Ledger Entry" in q:
                self.seen.append((q, p))
                return [dict(r) for r in SUPPLIER]
            return []
        frappe.db.sql = sql
        from neotec_insight.neotec_insight.api import packs
        self.packs = packs

    def tearDown(self):
        ff.uninstall()

    def test_conditions(self):
        sql, params = self.packs.ple_filters("Supplier", {
            "party_account": "Creditors - DSC", "cost_center": '["Main - DSC", "GMO - DSC"]', "finance_book": "IFRS",
            "party_group": "Services", "ignore_err": 1})
        self.assertIn("ple.account in %(f_accounts)s", sql)
        self.assertEqual(params["f_ccs"], ("Main - DSC", "GMO - DSC"))
        self.assertIn("default_finance_book", sql)
        self.assertIn("`tabSupplier` p where p.supplier_group", sql)
        self.assertIn("Exchange Gain Or Loss", sql)
        self.assertEqual(self.packs.ple_filters("Customer", {}), ("", {}))

    def test_filters_reach_the_query_and_party_currency(self):
        self.packs.ledger_rows("DSC", "2026-11-08", "Supplier", {"cost_center": "Main - DSC", "in_party_currency": 1})
        q, p = self.seen[-1]
        self.assertIn("ple.amount_in_account_currency as amount", q)
        self.assertEqual(p["f_ccs"], ("Main - DSC",))

    def test_screen_passes_them(self):
        from neotec_insight.neotec_insight.api import ageing
        self.frappe.has_permission = lambda *a, **k: True
        self.packs._has_ple = lambda: True
        ageing.ar_ap_ageing(company="DSC", as_of="2026-11-08", party_type="Supplier", finance_book="IFRS")
        self.assertEqual(self.seen[-1][1]["f_fb"], "IFRS")


class StatementOptions(unittest.TestCase):
    def test_statement_sends_erp_gl_options(self):
        s = (SRC / "features/statement/StatementApp.tsx").read_text()
        for k in ("disable_opening_balance_calculation", "show_cancelled_entries", "ignore_err", "ignore_cr_dr_notes",
                  "include_default_book_entries", "voucher_no", "against_voucher_no", "finance_book"):
            self.assertIn(k + ":", s)


if __name__ == "__main__":
    unittest.main()
