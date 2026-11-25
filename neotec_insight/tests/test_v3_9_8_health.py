"""v3.9.8 — health check H2-H8 and snapshot completeness, each from the
acceptance check in the release review."""
import json
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import _fakefrappe as ff  # noqa: E402
from test_v2_90_security import Site  # noqa: E402
from test_v3_6_bankrec import ROWS, page  # noqa: E402

APP = HERE.parents[0] / "neotec_insight"


# ── H2, H5, H6 — bank statements ─────────────────────────────────────────────

class Bank(unittest.TestCase):
    def setUp(self):
        self.site = ff.install()
        import frappe
        self.frappe = frappe
        frappe.log_error = lambda *a, **k: None
        self.site.table("Bank Account")["Riyad - IRSAA"] = {"name": "Riyad - IRSAA", "is_company_account": 1,
                                                             "account": "1110 - Riyad Bank - IR", "company": "IRSAA"}
        self.site.table("File")["f1"] = {"name": "f1", "file_url": "/private/files/stmt.pdf", "file_name": "stmt.pdf",
                                         "owner": "acc@a.co"}
        self.site.table("Insight AI Settings")["Insight AI Settings"] = {
            "name": "Insight AI Settings", "bank_charges_account": "5310 - Bank Charges - IR", "input_vat_account": ""}
        ff.stage_files(self)
        ff.Document.submit = lambda self: setattr(self, "docstatus", 1)
        self.addCleanup(lambda: delattr(ff.Document, "submit"))
        from neotec_insight.neotec_insight.api import bankrec
        self.br = bankrec
        self.parsed = []
        self.pages = [page(ROWS)]
        bankrec.core.pdf_words = lambda content: self.parsed.append(content) or self.pages
        frappe.db.sql = lambda q, p=None, as_dict=False: []
        from neotec_insight.neotec_insight.api import copilot
        copilot._ai_ready = lambda s=None: False

    def tearDown(self):
        ff.uninstall()

    # H2
    def test_private_pdf_needs_permission_to_the_file(self):
        self.site.user = "acc@a.co"
        s = self.br.create_statement("Riyad - IRSAA", "/private/files/stmt.pdf")
        self.assertEqual((s["status"], len(s["lines"])), ("Read", 5))
        self.site.perm = lambda dt, p, doc, u: (getattr(doc, "owner", None) == u) if dt == "File" else None
        self.site.user = "other@a.co"
        self.parsed.clear()
        with self.assertRaises(self.frappe.PermissionError):
            self.br.read_statement(s["name"])
        self.assertEqual(self.parsed, [])                    # refused before parsing

    def test_pdf_path_accepts_pdf_only(self):
        self.site.table("File")["f2"] = {"name": "f2", "file_url": "/private/files/stmt.txt", "file_name": "stmt.txt"}
        with self.assertRaises(self.frappe.ValidationError):
            self.br.create_statement("Riyad - IRSAA", "/private/files/stmt.txt")
        src = (APP / "api" / "bankrec.py").read_text()
        self.assertNotIn(".get_content()", src)

    # H5
    def test_reread_keeps_transactions_matches_and_reconciled_lines(self):
        s = self.br.create_statement("Riyad - IRSAA", "/private/files/stmt.pdf")
        self.br.create_transactions(s["name"])
        doc = self.frappe.get_doc(self.br.DT, s["name"])
        before = {ln.line_key: ln.bank_transaction for ln in doc.lines}
        self.assertTrue(all(before.values()))
        doc.lines[0].update({"match_json": json.dumps([["Payment Entry", "PE-1", 5.75]]), "match_status": "Reconciled"})
        doc.lines[1].update({"match_status": "Accepted", "confidence": 95, "note": "checked"})
        doc.save()
        again = self.br.read_statement(s["name"])
        doc = self.frappe.get_doc(self.br.DT, again["name"])
        self.assertEqual({ln.line_key: ln.bank_transaction for ln in doc.lines}, before)
        by = {ln.line_key: ln for ln in doc.lines}
        k0, k1 = list(before)[:2]
        self.assertEqual(by[k0].match_status, "Reconciled")
        self.assertEqual(json.loads(by[k0].match_json)[0][1], "PE-1")
        self.assertEqual((by[k1].match_status, by[k1].note), ("Accepted", "checked"))
        self.assertEqual(self.br.create_transactions(s["name"])["created"], 0)     # still none twice

    def test_reread_that_would_drop_a_processed_line_is_refused(self):
        s = self.br.create_statement("Riyad - IRSAA", "/private/files/stmt.pdf")
        self.br.create_transactions(s["name"])
        self.pages = [page(ROWS[1:])]                         # a different file: the newest line is gone
        with self.assertRaises(self.frappe.ValidationError):
            self.br.read_statement(s["name"])
        doc = self.frappe.get_doc(self.br.DT, s["name"])
        self.assertEqual(len(doc.lines), 5)
        self.assertTrue(all(ln.bank_transaction for ln in doc.lines))

    # H6
    def test_drafting_a_charge_again_returns_the_same_journal(self):
        s = self.br.create_statement("Riyad - IRSAA", "/private/files/stmt.pdf")
        fee = next(ln for ln in s["lines"] if ln["debit"] == 5.75)
        first = self.br.draft_charges(s["name"], [fee["name"]])["drafts"]
        second = self.br.draft_charges(s["name"], [fee["name"]])["drafts"]
        self.assertEqual(first, second)
        self.assertEqual(len(self.site.table("Journal Entry")), 1)
        locked = []
        self.frappe.db.sql = lambda q, p=None, as_dict=False: locked.append(q) or []
        self.br.draft_charges(s["name"], [fee["name"]])
        self.assertTrue(any("for update" in q for q in locked))
        # a cancelled draft is replaced by a new one
        self.site.table("Journal Entry")[first[0]]["docstatus"] = 2
        third = self.br.draft_charges(s["name"], [fee["name"]])["drafts"]
        self.assertNotEqual(third, first)


# ── H3 — scheduled report delivery ───────────────────────────────────────────

class Schedules(Site):
    def setUp(self):
        super().setUp()
        for u in ("acc@a.co", "cfo@a.co"):
            self.site.table("User")[u] = {"name": u, "email": u, "enabled": 1}
        self.site.table("Studio Report")["R1"] = {"name": "R1", "title": "R", "config_json": '{"doctype": "GL Entry"}'}
        self.ran, self.sent = [], []
        studio = types.ModuleType("neotec_insight.neotec_insight.api.studio")
        studio.run_query = lambda cfg: self.ran.append(self.site.user) or {"rows": [], "columns": []}
        sys.modules["neotec_insight.neotec_insight.api.studio"] = studio
        self.frappe.sendmail = lambda **k: self.sent.append(k["recipients"])
        from neotec_insight.neotec_insight.utils import scheduled_reports as sch
        sch._render_attachment = lambda *a: ("r.xlsx", b"x")
        sch.get_url = lambda path="": "https://test.site" + path
        import html
        self.frappe.utils.escape_html = html.escape
        self.sch = sch
        from neotec_insight.neotec_insight.doctype.insight_report_schedule.insight_report_schedule import (
            InsightReportSchedule,
        )
        self.Cls = InsightReportSchedule

    def schedule(self, before=None, **data):
        doc = self.Cls("Insight Report Schedule", {"report": "R1", "enabled": 1, **data})
        prev = dict(before) if before else None
        doc.is_new = lambda: prev is None
        doc.has_value_changed = lambda f: prev is None or prev.get(f) != doc.get(f)
        doc.db_set = lambda *a, **k: None
        return doc

    def test_desk_save_checks_recipients_and_sets_the_responsible_user(self):
        self.as_user("acc@a.co", {"Accounts Manager"})
        with self.assertRaises(self.frappe.ValidationError):
            self.schedule(recipients="someone@gmail.com").validate()
        with self.assertRaises(self.frappe.ValidationError):
            self.schedule(whatsapp_numbers="+966500000000").validate()
        doc = self.schedule(recipients="cfo@a.co", run_as="Administrator")
        doc.validate()
        self.assertEqual(doc.run_as, "acc@a.co")                 # not what the form said
        self.assertEqual(self.ran, ["acc@a.co"])                 # the report was run once as them

    def test_changing_recipients_makes_the_editor_responsible(self):
        self.as_user("cfo@a.co", {"Accounts Manager"})
        old = {"report": "R1", "enabled": 1, "recipients": "acc@a.co", "run_as": "acc@a.co"}
        doc = self.schedule(before=old, recipients="cfo@a.co", run_as="acc@a.co")
        doc.validate()
        self.assertEqual(doc.run_as, "cfo@a.co")
        unchanged = self.schedule(before=old, recipients="acc@a.co", run_as="acc@a.co", subject="new subject")
        self.ran.clear()
        unchanged.validate()
        self.assertEqual((unchanged.run_as, self.ran), ("acc@a.co", []))

    def test_send_time_recheck_disabled_recipient_and_domain_policy(self):
        doc = self.schedule(name="S1", recipients="cfo@a.co", run_as="acc@a.co")
        self.site.roles["acc@a.co"] = {"Accounts Manager"}
        self.sch.dispatch_schedule(doc)
        self.assertEqual(self.sent, [["cfo@a.co"]])
        self.site.table("User")["cfo@a.co"]["enabled"] = 0           # recipient disabled since saving
        self.sch.dispatch_schedule(doc)
        self.assertEqual(self.sent, [["cfo@a.co"]])
        self.assertTrue(any("dispatch failed" in e for e in self.site.errors))
        self.site.table("User")["cfo@a.co"]["enabled"] = 1
        self.frappe.conf["insight_schedule_allowed_domains"] = ["irsaa.sa"]     # domain policy changed
        self.sch.dispatch_schedule(doc)
        self.assertEqual(self.sent, [["cfo@a.co"]])


# ── H4 — control findings ────────────────────────────────────────────────────

class Findings(Site):
    def setUp(self):
        super().setUp()
        from neotec_insight.neotec_insight.api import controls
        self.c = controls
        for n, co in (("F-A", "Alpha Co"), ("F-B", "Beta Co")):
            self.site.table(controls.FIND)[n] = {"name": n, "company": co, "status": "Open"}

    def test_restricted_manager_cannot_change_another_companys_finding(self):
        self.as_user("acc@a.co", {"Accounts Manager"}, ["Alpha Co"])
        with self.assertRaises(self.frappe.PermissionError):
            self.c.set_status(json.dumps(["F-B"]), self.c.core.DISMISSED)
        with self.assertRaises(self.frappe.PermissionError):
            self.c.set_status(json.dumps(["F-A", "F-B"]), self.c.core.DISMISSED)
        t = self.site.table(self.c.FIND)
        self.assertEqual((t["F-A"]["status"], t["F-B"]["status"]), ("Open", "Open"))     # nothing changed
        self.assertEqual(self.c.set_status(json.dumps(["F-A"]), self.c.core.DISMISSED)["updated"], 1)
        self.assertEqual(t["F-A"]["status"], self.c.core.DISMISSED)

    def test_document_permission_and_unknown_names(self):
        self.as_user("cfo@a.co", {"Accounts Manager"}, ["Alpha Co", "Beta Co"])
        self.site.perm = lambda dt, p, doc, u: False if (dt == self.c.FIND and p == "write" and doc == "F-B") else None
        with self.assertRaises(self.frappe.PermissionError):
            self.c.set_status(json.dumps(["F-A", "F-B"]), self.c.core.ACK)
        with self.assertRaises(self.frappe.ValidationError):
            self.c.set_status(json.dumps(["F-A", "nope"]), self.c.core.ACK)
        self.assertEqual(self.site.table(self.c.FIND)["F-A"]["status"], "Open")


# ── H7, H8 — group results ───────────────────────────────────────────────────

RATES = {("SAR", "USD", "2025-07"): 0.25, ("SAR", "USD", "2026-01"): 0.30, ("AED", "USD", "2026-03"): 0.27}


class Group(Site):
    def setUp(self):
        super().setUp()
        t = self.site.table("Company")
        t["Alpha Co"].update(default_currency="USD", year_start_date="2025-01-01")
        t["Beta Co"].update(default_currency="SAR", year_start_date="2025-07-01")          # July start
        t["Gamma Co"] = {"name": "Gamma Co", "company_name": "Gamma Co", "default_currency": "USD",
                         "year_start_date": "2025-01-01"}
        t["Delta Co"] = {"name": "Delta Co", "company_name": "Delta Co", "default_currency": "AED",
                         "year_start_date": "2025-01-01"}
        t["Parity Co"] = {"name": "Parity Co", "company_name": "Parity Co", "default_currency": "BHD",
                          "year_start_date": "2025-01-01"}
        from neotec_insight.neotec_insight.api import group_view as gv
        gv._check_group_view_access = gv._require_read = lambda: None
        gv._resolve_report_doc = lambda r: types.SimpleNamespace(name="R", definition_json="{}")
        gv.load_flag_to_accounts = lambda n: {}
        gv._sanitise_dimension_filters = lambda d: None
        self.fail_for = set()

        def execute_report(company=None, **k):
            if company in self.fail_for:
                raise RuntimeError("boom")
            amt = {"Gamma Co": 0.0}.get(company, 100.0)
            return {"rows": [{"key": k, "monthly": {m: amt for m in range(12)}}
                             for k in ("total_revenue", "gross_profit", "ebitda", "net_income")]}
        gv.execute_report = execute_report

        def sql(q, p=None, as_dict=False):
            frm, to = p[0], p[1]
            if (frm, to) == ("BHD", "USD"):
                return [(1.0,)] if "date >= %s" in q else []        # a genuine parity rate
            if "date >= %s" in q:
                r = RATES.get((frm, to, p[2][:7]))
                return [(r,)] if r else []
            if "ORDER BY date DESC" in q:
                prior = sorted((k[2], v) for k, v in RATES.items() if k[:2] == (frm, to) and k[2] < p[2][:7])
                return [(prior[-1][1],)] if prior else []
            return []
        self.frappe.db.sql = sql
        self.gv = gv
        self.as_user("Administrator", {"System Manager"})

    def test_july_year_uses_each_calendar_months_rate(self):
        out = self.gv.get_group_dashboard(report="R", fiscal_year=2026, companies='["Beta Co"]',
                                          presentation_currency="USD")
        beta = out["by_company"][0]
        self.assertEqual(out["periods"][0], "2025-07")
        self.assertEqual(out["periods"][6], "2026-01")                  # crosses December
        self.assertEqual(beta["rates_used"][0], 0.25)                   # July at July's rate
        self.assertEqual(beta["rates_used"][5], 0.25)                   # Dec: latest earlier rate
        self.assertEqual(beta["rates_used"][6], 0.30)                   # January at January's rate
        self.assertTrue(out["complete"])
        self.assertAlmostEqual(out["group"]["total_revenue"]["total"], 6 * 25 + 6 * 30)
        self.assertEqual(out["periods"][0], "2025-07")

    def test_parity_rate_is_not_a_gap_and_missing_rate_withholds_total(self):
        out = self.gv.get_group_dashboard(report="R", fiscal_year=2026, companies='["Parity Co"]',
                                          presentation_currency="USD")
        self.assertEqual(out["fx_gaps"], [])
        self.assertTrue(out["complete"])
        out = self.gv.get_group_dashboard(report="R", fiscal_year=2026, companies='["Alpha Co", "Delta Co"]',
                                          presentation_currency="USD")
        gap = out["fx_gaps"][0]
        self.assertEqual((gap["company"], gap["months"]), ("Delta Co", ["2026-01", "2026-02"]))
        self.assertFalse(out["complete"])
        self.assertIsNone(out["group"]["total_revenue"]["total"])
        delta = out["by_company"][1]
        self.assertIsNone(delta["kpis"]["total_revenue"]["presentation_total"])
        self.assertNotIn(1.0, delta["rates_used"][:2])                  # never a silent 1.0
        self.assertIn("Delta Co", out["withheld_reason"])

    def test_zero_company_and_failed_company_in_one_request(self):
        self.fail_for = {"Alpha Co"}
        out = self.gv.get_group_dashboard(report="R", fiscal_year=2026, companies='["Gamma Co", "Alpha Co"]',
                                          presentation_currency="USD")
        status = {r["company"]: r["status"] for r in out["by_company"]}
        self.assertEqual(status, {"Gamma Co": "ok", "Alpha Co": "failed"})
        gamma = out["by_company"][0]
        self.assertEqual(gamma["kpis"]["total_revenue"]["native_total"], 0.0)      # a real zero
        self.assertEqual(out["failed_companies"], ["Alpha Co"])
        self.assertFalse(out["complete"])
        self.assertIsNone(out["group"]["total_revenue"]["total"])
        self.fail_for = set()
        out = self.gv.get_group_dashboard(report="R", fiscal_year=2026, companies='["Gamma Co", "Alpha Co"]',
                                          presentation_currency="USD")
        self.assertTrue(out["complete"])
        self.assertEqual(out["group"]["total_revenue"]["total"], 1200.0)


# ── recovery snapshots ───────────────────────────────────────────────────────

class Snapshots(Site):
    def test_two_identical_partial_captures_are_both_refused(self):
        from neotec_insight.neotec_insight.utils import backup_engine, snapshots
        real = backup_engine.build_bundle

        def partial(sections=None, plan=None):
            b = real(sections, plan)
            b["errors"] = ["Insight Budget Cell: timeout"]
            return b
        snapshots.build_bundle = partial
        for _ in range(2):
            with self.assertRaises(snapshots.SnapshotRequired):
                snapshots.guard("pre_restore", required=True, sections=["Insight Dashboard"])
        r = snapshots.take("manual", dedupe=True)
        self.assertTrue(r["incomplete"])
        self.assertFalse(r["skipped"])
        # a complete capture afterwards is stored, not deduplicated into the partial one
        snapshots.build_bundle = real
        full = snapshots.take("manual", dedupe=True)
        self.assertFalse(full["skipped"])
        self.assertFalse(full.get("incomplete"))
        self.assertTrue(snapshots.take("manual", dedupe=True)["skipped"])     # complete ones are still reused


if __name__ == "__main__":
    unittest.main()
