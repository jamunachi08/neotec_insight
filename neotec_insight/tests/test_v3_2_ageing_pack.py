"""v3.2.0 — 'AR & AP Ageing' download pack, laid out like the client's
month-end workbook (Dashboard, AR Ageing, AP Ageing), with live formulas."""
import io
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import _fakefrappe as ff  # noqa: E402

OUT = Path("/tmp/ageing_pack_test.xlsx")


def fake_ageing(company=None, as_of=None, party_type="Customer", split_not_due=0, **k):
    if party_type == "Customer":
        rows = [{"party": "C1", "label": "Acme Trading", "invoiced": 1000.0, "paid": 300.0, "outstanding": 700.0,
                 "not_due": 0.0, "buckets": [400.0, 200.0, 0.0, 100.0, 0.0]},
                {"party": "C2", "label": "Beta Co", "invoiced": 500.0, "paid": 0.0, "outstanding": 500.0,
                 "not_due": 0.0, "buckets": [0.0, 0.0, 0.0, 0.0, 500.0]}]
    else:
        nd = 150.0 if split_not_due else 0.0
        rows = [{"party": "S1", "label": "Gulf Supplies", "invoiced": 800.0, "paid": 200.0, "outstanding": 600.0,
                 "not_due": nd, "buckets": [450.0 - nd + 150.0 - 150.0 if split_not_due else 450.0, 150.0, 0, 0, 0]}]
    # v3.2.1 — the REAL label builder: it returns {"key","en","ar"} objects, which
    # the first version of the pack wrote straight into Excel (server error).
    from neotec_insight.neotec_insight.api.ageing import _slab_labels
    return {"rows": rows, "labels": _slab_labels([30, 60, 90, 120], "days"), "currency": "SAR"}


class Pack(unittest.TestCase):
    def setUp(self):
        self.site = ff.install()
        import frappe
        self.frappe = frappe
        self.site.table("Company")["Alpha Co"] = {"name": "Alpha Co", "company_name": "شركة ألفا", "default_currency": "SAR"}
        frappe.local.response = types.SimpleNamespace()
        from neotec_insight.neotec_insight.api import ageing, packs
        self.packs = packs
        self.real_ageing = ageing.ar_ap_ageing
        ageing.ar_ap_ageing = fake_ageing
        packs._notes_by_party = lambda c, d, pt: {"C1": 50.0} if pt == "Customer" else {"S1": 20.0}
        packs._seed_ageing_pack()

    def tearDown(self):
        ff.uninstall()

    def build(self):
        self.packs.generate_pack("ar_ap_ageing", "Alpha Co", "2026-09-01", "2026-09-30")
        data = self.frappe.local.response.filecontent
        OUT.write_bytes(data)
        import openpyxl
        return openpyxl.load_workbook(io.BytesIO(data))

    def test_layout_matches_the_template(self):
        wb = self.build()
        self.assertEqual(wb.sheetnames, ["Dashboard", "AR Ageing", "AP Ageing"])
        ar, ap = wb["AR Ageing"], wb["AP Ageing"]
        self.assertEqual([c.value for c in ar[9]][:6], ["#", "Party Name", "Invoiced Amount", "Paid Amount",
                                                        "Credit Note", "Outstanding"])
        self.assertEqual(ar["L9"].value, "Total Due")
        self.assertEqual(ap["E9"].value, "Debit Note")
        self.assertEqual(ap["G9"].value, "Not Yet Due")
        self.assertEqual(ap["M9"].value, "Total Due")
        self.assertIn("30 September 2026", ar["B5"].value)
        self.assertEqual(ar.freeze_panes, "C10")

    def test_notes_split_out_of_payments(self):
        ar = self.build()["AR Ageing"]
        self.assertEqual((ar["D10"].value, ar["E10"].value), (250.0, 50.0))   # paid 300 = 250 payments + 50 notes
        self.assertEqual(ar["F10"].value, "=C10-D10-E10")
        self.assertEqual(ar["L10"].value, "=SUM(G10:K10)")
        self.assertEqual(ar["C12"].value, "=SUM(C10:C11)")                    # total row

    def test_dashboard_links(self):
        d = self.build()["Dashboard"]
        self.assertEqual(d["E6"].value, "='AR Ageing'!G12")
        self.assertEqual(d["I6"].value, "='AP Ageing'!G11")                   # AP: 1 supplier, total row 11, starts with Not Yet Due
        self.assertTrue(str(d["I7"].value).startswith("='AP Ageing'!H"))

    def test_pack_is_seeded_once(self):
        self.packs._seed_ageing_pack()
        self.assertEqual(len([k for k in self.site.table("Insight Export Pack")]), 1)


if __name__ == "__main__":
    unittest.main()


class FromAgeingScreen(Pack):
    """v3.2.1 — the Ageing screen's Download pack button."""

    def test_overrides_reach_every_ageing_sheet_and_bad_values_are_ignored(self):
        seen = []
        from neotec_insight.neotec_insight.api import ageing

        def spy(**k):
            seen.append(k)
            return fake_ageing(**k)
        ageing.ar_ap_ageing = spy
        self.packs.generate_pack("ar_ap_ageing", "Alpha Co", "2026-10-27", "2026-10-27",
                                 overrides='{"slabs": "30,60,90", "based_on": "posting", "mode": "months", "evil": 1}')
        self.assertEqual({(k["slabs"], k["based_on"], k["mode"]) for k in seen}, {("30,60,90", "posting", "months")})
        seen.clear()
        self.packs.generate_pack("ar_ap_ageing", "Alpha Co", "2026-10-27", "2026-10-27",
                                 overrides='{"based_on": "DROP", "mode": "weeks"}')
        self.assertEqual({(k["based_on"], k["mode"]) for k in seen}, {("due", "days")})

    def test_missing_pack_is_created_on_the_fly(self):
        self.site.table("Insight Export Pack").clear()
        self.packs.generate_pack("ar_ap_ageing", "Alpha Co", "2026-10-27", "2026-10-27")
        self.assertIn("ar_ap_ageing", self.site.table("Insight Export Pack"))
        self.assertTrue(self.frappe.local.response.filecontent)


class Labels(Pack):
    def test_bucket_headers_are_text_in_the_pack_language(self):
        ar = self.build()["AR Ageing"]
        self.assertEqual(ar["G9"].value, "0\u201330 Days")
        self.assertEqual(ar["K9"].value, "121+ Days")
