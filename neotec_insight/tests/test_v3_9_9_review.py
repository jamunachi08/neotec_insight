"""v3.9.9 — the v3.9.8 release review, and the wider audit that followed.
Each test is written from the acceptance check it answers."""
import ast
import importlib
import io
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
MOD = "neotec_insight.neotec_insight"


# ── 1. company scope on every endpoint, whatever the route ───────────────────

class EveryEndpointIsScoped(unittest.TestCase):
    def test_no_plain_whitelist_left_and_each_endpoint_wrapped(self):
        site = ff.install()
        self.addCleanup(ff.uninstall)
        _ = site
        missing, plain, total = [], [], 0
        for f in sorted((APP / "api").glob("*.py")):
            src = f.read_text()
            if "@frappe.whitelist" in src:
                plain.append(f.name)
            names = [n.name for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)
                     and any("insight_api" in ast.unparse(d) for d in n.decorator_list)]
            if not names:
                continue
            mod = importlib.import_module(f"{MOD}.api.{f.stem}")
            for n in names:
                total += 1
                if not getattr(getattr(mod, n), "insight_scoped", False):
                    missing.append(f"{f.stem}.{n}")
        self.assertEqual((plain, missing), ([], []))
        self.assertGreater(total, 300)

    def test_every_route_form_is_recognised(self):
        ff.install()
        self.addCleanup(ff.uninstall)
        import frappe
        from neotec_insight.neotec_insight.utils import access
        for path in ("/api/method/neotec_insight.neotec_insight.api.ageing.get_ageing",
                     "/api/v1/method/neotec_insight.neotec_insight.api.ageing.get_ageing",
                     "/api/v2/method/neotec_insight.neotec_insight.api.ageing.get_ageing"):
            frappe.request = types.SimpleNamespace(path=path)
            self.assertEqual(access._target_method(), f"{MOD}.api.ageing.get_ageing")


class ScopeInsideTheService(Site):
    def test_direct_call_without_any_request_is_refused(self):
        self.as_user("acc@a.co", {"Accounts User"}, ["Alpha Co"])
        self.frappe.request = None                       # no route at all
        from neotec_insight.neotec_insight.api import liquidity
        with self.assertRaises(self.frappe.PermissionError):
            liquidity.get_liquidity(company="Beta Co", fiscal_year=2026)

    def test_company_inside_filters_and_payloads(self):
        self.as_user("acc@a.co", {"Accounts User"}, ["Alpha Co"])
        from neotec_insight.neotec_insight.utils import access
        for args in ({"filters": {"company": "Beta Co"}}, {"filters": '[["GL Entry","company","=","Beta Co"]]'},
                     {"payload": '{"company": "Beta Co"}'}, {"config": {"filters": {"company": "Beta Co"}}},
                     {"companies": ["Alpha Co", "Beta Co"]}):
            with self.assertRaises(self.frappe.PermissionError, msg=str(args)):
                access.check_call_scope({}, dict(args), fill=False)
        access.check_call_scope({}, {"filters": {"company": "Alpha Co"}}, fill=False)
        for ok in ({"filters": {"company": ["!=", "Beta Co"]}}, {"filters": [["company", "not in", ["Beta Co"]]]},
                   {"filters": {"company": ["in", ["Alpha Co"]]}}):
            access.check_call_scope({}, dict(ok), fill=False)              # exclusions select nothing
        with self.assertRaises(self.frappe.PermissionError):
            access.check_call_scope({}, {"filters": {"company": ["in", ["Alpha Co", "Beta Co"]]}}, fill=False)

    def test_named_records_must_belong_to_an_allowed_company(self):
        self.site.table("Bank Account")["Beta Bank"] = {"name": "Beta Bank", "company": "Beta Co"}
        self.site.table("Account")["Cash - B"] = {"name": "Cash - B", "company": "Beta Co"}
        self.site.table("Insight Allocation Rule")["R-B"] = {"name": "R-B", "company": "Beta Co"}
        self.as_user("acc@a.co", {"Accounts User"}, ["Alpha Co"])
        from neotec_insight.neotec_insight.utils import access
        for args in ({"bank_account": "Beta Bank"}, {"accounts": '["Cash - B"]'}, {"rule": "R-B"}):
            with self.assertRaises(self.frappe.PermissionError, msg=str(args)):
                access.check_call_scope({}, args, fill=False)

    def test_company_filled_on_the_outer_call_only(self):
        self.as_user("acc@a.co", {"Accounts User"}, ["Alpha Co"])
        from neotec_insight.neotec_insight.utils.access import scoped
        seen = []

        def inner(company=None):
            seen.append(("inner", company))
        inner_s = scoped(inner)

        def outer(company=None):
            seen.append(("outer", company))
            inner_s(company=None)                    # deliberate: no company
        scoped(outer)()
        self.assertEqual(seen, [("outer", "Alpha Co"), ("inner", None)])

    def test_default_company_is_one_the_user_may_see(self):
        self.as_user("acc@a.co", {"Accounts User"}, ["Beta Co"])
        self.frappe.defaults = types.SimpleNamespace(get_user_default=lambda k: "Alpha Co",
                                                     get_global_default=lambda k: None)
        from neotec_insight.neotec_insight.utils.access import default_company
        self.assertEqual(default_company(), "Beta Co")


# ── 2. group view: KPI errors and one common period ──────────────────────────

class Group(Site):
    KPIS = ("total_revenue", "gross_profit", "ebitda", "net_income")

    def setUp(self):
        super().setUp()
        t = self.site.table("Company")
        t["Alpha Co"].update(default_currency="SAR", year_start_date="2025-01-01")
        t["Beta Co"].update(default_currency="SAR", year_start_date="2025-07-01")       # July start
        from neotec_insight.neotec_insight.api import group_view as gv
        gv._check_group_view_access = gv._require_read = lambda: None
        self.definition = {"rows": [
            {"key": "total_revenue", "kind": "source"}, {"key": "cogs", "kind": "source"},
            {"key": "gross_profit", "kind": "formula", "formula": "total_revenue - cogs"},
            {"key": "ebitda", "kind": "formula", "formula": "gross_profit"},
            {"key": "net_income", "kind": "formula", "formula": "ebitda"}]}
        gv._resolve_report_doc = lambda r: types.SimpleNamespace(name="R",
                                                                 definition_json=json.dumps(self.definition))
        gv.load_flag_to_accounts = lambda n: {}
        gv._sanitise_dimension_filters = lambda d: None
        self.calls, self.errors, self.drop = [], {}, set()

        def execute_report(company=None, fy_start_month_override=None, **k):
            self.calls.append((company, fy_start_month_override))
            rows = [{"key": k2, "monthly": {m: (0.0 if company == "Zero Co" else 10.0) for m in range(12)}}
                    for k2 in ("total_revenue", "cogs") + self.KPIS if k2 not in self.drop.get(company, ())]
            return {"rows": rows, "formula_errors": self.errors.get(company, {})}
        gv.execute_report = execute_report
        self.frappe.db.sql = lambda *a, **k: []
        self.gv = gv
        self.as_user("Administrator", {"System Manager"})
        self.drop = {}

    def run_group(self, companies, **kw):
        return self.gv.get_group_dashboard(report="R", fiscal_year=2026, companies=json.dumps(companies),
                                           presentation_currency="SAR", **kw)

    def test_one_calendar_for_every_company(self):
        out = self.run_group(["Alpha Co", "Beta Co"])
        self.assertEqual(len(out["periods"]), 12)
        self.assertEqual((out["periods"][0], out["periods"][-1]), ("2026-01", "2026-12"))
        self.assertEqual({c for c, _ in self.calls}, {"Alpha Co", "Beta Co"})
        self.assertEqual({o for _, o in self.calls}, {1})                # Beta restated to Jan–Dec
        self.assertEqual(out["period"]["restated_companies"], ["Beta Co"])
        self.assertEqual(out["group"]["total_revenue"]["total"], 240.0)
        self.assertTrue(all(len(v["monthly"]) == 12 for v in out["group"].values()))
        out = self.run_group(["Alpha Co", "Beta Co"], reference_company="Beta Co")
        self.assertEqual((out["periods"][0], out["periods"][-1]), ("2025-07", "2026-06"))
        with self.assertRaises(self.frappe.ValidationError):
            self.run_group(["Alpha Co"], reference_company="Beta Co")

    def test_formula_error_withholds_the_kpis_that_use_it(self):
        self.errors = {"Beta Co": {"cogs": {"label": "Cost of sales", "formula": "x/0", "months": {"3": "div"}}}}
        self.definition["rows"][1] = {"key": "cogs", "kind": "formula", "formula": "x/0"}
        out = self.run_group(["Alpha Co", "Beta Co"])
        beta = out["by_company"][1]
        self.assertEqual(beta["status"], "partial")
        self.assertEqual(beta["kpis"]["gross_profit"]["status"], "error")
        self.assertEqual(beta["kpis"]["net_income"]["status"], "error")         # through ebitda
        self.assertIsNone(beta["kpis"]["net_income"]["native_total"])
        self.assertEqual(beta["kpis"]["total_revenue"]["status"], "ok")
        self.assertEqual(out["group"]["net_income"]["status"], "withheld")
        self.assertIsNone(out["group"]["net_income"]["total"])
        self.assertEqual(out["group"]["total_revenue"]["status"], "ok")
        self.assertIn("Cost of sales", out["withheld_reason"])
        self.assertIn("Beta Co", out["withheld_reason"])
        self.assertFalse(out["complete"])

    def test_missing_kpi_is_not_zero_and_a_real_zero_is(self):
        self.site.table("Company")["Zero Co"] = {"name": "Zero Co", "default_currency": "SAR",
                                                 "year_start_date": "2025-01-01"}
        self.drop = {"Alpha Co": {"ebitda"}}
        out = self.run_group(["Alpha Co", "Zero Co"])
        alpha, zero = out["by_company"]
        self.assertEqual(alpha["kpis"]["ebitda"]["status"], "missing")
        self.assertEqual(out["group"]["ebitda"]["status"], "withheld")
        self.assertEqual(zero["kpis"]["net_income"]["native_total"], 0.0)
        self.assertEqual(zero["kpis"]["net_income"]["status"], "ok")
        self.assertEqual(out["group"]["net_income"]["total"], 120.0)


# ── 3. bank: the drafted charge journal keeps its link ───────────────────────

class Bank(unittest.TestCase):
    def setUp(self):
        self.site = ff.install()
        import frappe
        self.frappe = frappe
        frappe.log_error = lambda *a, **k: None
        self.site.table("Bank Account")["Riyad - IRSAA"] = {"name": "Riyad - IRSAA", "is_company_account": 1,
                                                             "account": "1110 - Riyad Bank - IR", "company": "IRSAA"}
        self.site.table("File")["f1"] = {"name": "f1", "file_url": "/private/files/stmt.pdf", "file_name": "stmt.pdf"}
        self.site.table("Insight AI Settings")["Insight AI Settings"] = {
            "name": "Insight AI Settings", "bank_charges_account": "5310 - Bank Charges - IR", "input_vat_account": ""}
        ff.stage_files(self)
        ff.Document.submit = lambda self: setattr(self, "docstatus", 1)
        self.addCleanup(lambda: delattr(ff.Document, "submit"))
        from neotec_insight.neotec_insight.api import bankrec
        self.br = bankrec
        self.pages = [page(ROWS)]
        bankrec.core.pdf_words = lambda content: self.pages
        frappe.db.sql = lambda q, p=None, as_dict=False: []
        from neotec_insight.neotec_insight.api import copilot
        copilot._ai_ready = lambda s=None: False

    def tearDown(self):
        ff.uninstall()

    def drafted(self):
        s = self.br.create_statement("Riyad - IRSAA", "/private/files/stmt.pdf")
        fee = next(ln for ln in s["lines"] if ln["debit"] == 5.75)
        je = self.br.draft_charges(s["name"], [fee["name"]])["drafts"][0]
        return s, fee, je

    def test_draft_is_held_in_its_own_field_and_named_on_the_journal(self):
        s, fee, je = self.drafted()
        line = next(ln for ln in self.br.summary(s["name"])["lines"] if ln["name"] == fee["name"])
        self.assertEqual(line["draft_journal"], je)
        self.assertIn(s["name"], self.site.table("Journal Entry")[je]["user_remark"])

    def test_rematching_keeps_the_draft_and_a_retry_returns_it(self):
        s, fee, je = self.drafted()
        self.br._candidates = lambda doc: [{"name": "PE-9", "doctype": "Payment Entry", "amount": 5.75,
                                            "direction": "out", "date": None, "party": "", "reference": ""}]
        self.br.core.match = lambda view, cands: [{"key": v["key"], "vouchers": [["Payment Entry", "PE-9", 5.75]],
                                                   "confidence": 0.9, "rule": "amount"} for v in view]
        self.br.find_matches(s["name"], use_ai=0)
        line = next(ln for ln in self.br.summary(s["name"])["lines"] if ln["name"] == fee["name"])
        self.assertEqual(json.loads(line["match_json"])[0][1], je)          # suggestion not replaced
        self.assertEqual(self.br.draft_charges(s["name"], [fee["name"]])["drafts"], [je])
        self.assertEqual(len(self.site.table("Journal Entry")), 1)

    def test_reread_that_would_drop_a_drafted_line_is_refused(self):
        s, fee, je = self.drafted()
        self.pages = [page([r for r in ROWS if "5.75" not in json.dumps(r)])]
        with self.assertRaises(self.frappe.ValidationError):
            self.br.read_statement(s["name"])
        self.assertIn(je, [ln.draft_journal for ln in self.frappe.get_doc(self.br.DT, s["name"]).lines])

    def test_cancelled_draft_frees_the_line(self):
        s, fee, je = self.drafted()
        self.site.table("Journal Entry")[je]["docstatus"] = 2
        self.assertNotEqual(self.br.draft_charges(s["name"], [fee["name"]])["drafts"], [je])

    def test_migration_patch_copies_the_draft_from_the_match(self):
        from neotec_insight.patches.v3_9 import bank_draft_link
        self.site.table("Journal Entry")["JE-1"] = {"name": "JE-1", "docstatus": 0}
        self.frappe.reload_doc = lambda *a, **k: None
        self.frappe.db.sql = lambda q, p=None, as_dict=False: [
            self.frappe._dict(name="L1", match_json='[["Journal Entry", "JE-1", 5.75]]')]
        written = []
        self.frappe.db.set_value = lambda dt, n, f, v, **k: written.append((n, f, v))
        bank_draft_link.execute()
        self.assertEqual(written, [("L1", "draft_journal", "JE-1")])


# ── 4. budget import: no unusable cell becomes an amount ─────────────────────

class BudgetImport(Site):
    def setUp(self):
        super().setUp()
        self.site.table("Insight Report Definition")["PL"] = {
            "name": "PL", "slug": "pl", "report_name": "P&L", "company": "Alpha Co",
            "definition_json": json.dumps({"rows": [{"key": "rev", "kind": "source"}, {"key": "cost", "kind": "source"}]})}
        self.site.table("Accounting Dimension")["Branch X"] = {"name": "Branch X", "fieldname": "branch_x",
                                                               "document_type": "Branch X", "label": "Branch X"}
        self.site.table("Accounting Dimension")["Region"] = {"name": "Region", "fieldname": "region",
                                                             "document_type": "Region", "label": "Region"}
        from neotec_insight.neotec_insight.api import budget_import as bi
        self.bi = bi
        self.frappe.utils.escape_html = lambda s: s
        self.as_user("Administrator", {"System Manager"})

    def cells(self):
        return {(c["book"], c["row_key"], int(c["month"])): c["amount"]
                for c in self.site.table("Insight Budget Cell").values()}

    def imp(self, rows, **kw):
        return self.bi.budget_import(report="PL", fiscal_year=2026, rows=json.dumps(rows), **kw)

    def test_invalid_cell_refuses_everything_before_writing(self):
        rows = [{"value": "Main", "row_key": "rev", "months": {"0": 50}},
                {"value": "Main", "row_key": "cost", "sheet_row": 7, "months": {"0": "#DIV/0!"}}]
        with self.assertRaises(self.frappe.ValidationError) as cm:
            self.imp(rows)
        self.assertIn("Sheet row 7, M1", str(cm.exception))
        self.assertEqual(self.site.table("Insight Budget Cell"), {})
        self.assertEqual(self.site.table("Insight Budget Book"), {})

    def test_partial_import_over_existing_budget(self):
        self.imp([{"value": "Main", "row_key": "rev", "months": {"0": 100, "1": 100, "2": 100}}])
        book = next(iter(self.site.table("Insight Budget Book")))
        # blank (absent / null / "") keeps 100; explicit 0 writes 0; a number replaces
        self.imp([{"value": "Main", "row_key": "rev", "months": {"0": None, "1": 0, "2": "1,250.5"}}])
        c = self.cells()
        self.assertEqual((c[(book, "rev", 0)], c[(book, "rev", 1)], c[(book, "rev", 2)]), (100, 0.0, 1250.5))

    def test_locked_book_refuses_the_import(self):
        self.imp([{"value": "Main", "row_key": "rev", "months": {"0": 100}}])
        book = next(iter(self.site.table("Insight Budget Book").values()))
        book["status"] = "approved"
        self.as_user("planner@a.co", {"Insight Budget Planner"}, ["Alpha Co"])
        with self.assertRaises(self.frappe.PermissionError):
            self.imp([{"value": "Main", "row_key": "rev", "months": {"0": 5}}])
        self.assertEqual(list(self.cells().values()), [100])

    def test_two_custom_dimensions_with_the_same_value_are_two_books(self):
        for fn in ("branch_x", "region", "branch_x"):
            self.imp([{"value": "North", "row_key": "rev", "months": {"0": 1}}],
                     dimension_type="custom", custom_dimension_fieldname=fn)
        books = list(self.site.table("Insight Budget Book").values())
        self.assertEqual(sorted(b["custom_dimension_fieldname"] for b in books), ["branch_x", "region"])
        self.assertEqual(len({b["slug"] for b in books}), 2)
        with self.assertRaises(self.frappe.ValidationError):
            self.imp([{"value": "North", "row_key": "rev", "months": {"0": 1}}], dimension_type="custom")
        with self.assertRaises(self.frappe.ValidationError):
            self.imp([{"value": "North", "row_key": "rev", "months": {"0": 1}}],
                     dimension_type="custom", custom_dimension_fieldname="no_such_field")

    def test_book_controller_accepts_custom_dimensions(self):
        from neotec_insight.neotec_insight.doctype.insight_budget_book.insight_budget_book import (
            InsightBudgetBook, auto_slug)
        b = InsightBudgetBook("Insight Budget Book", {"report": "PL", "fiscal_year": 2026, "dimension_type": "custom",
                                                      "dimension_value": "North", "custom_dimension_fieldname": "region"})
        b.before_validate()
        b.validate()
        self.assertIn("dim-region", b.slug)
        self.assertIn("Region", b.label)
        self.assertNotEqual(auto_slug("PL", 2026, "custom", "North", "region"),
                            auto_slug("PL", 2026, "custom", "North", "branch_x"))
        b.custom_dimension_fieldname = None
        with self.assertRaises(self.frappe.ValidationError):
            b.validate()


# ── 5. scheduled delivery re-checked when the queued job runs ────────────────

class ScheduleWorker(Site):
    def setUp(self):
        super().setUp()
        self.site.table("Studio Report")["R1"] = {"name": "R1", "title": "R"}
        from neotec_insight.neotec_insight.utils import scheduled_reports as sch
        self.sch = sch
        self.sent = []
        sch.dispatch_schedule = lambda doc: self.sent.append(doc.name)
        self.site.table("Insight Report Schedule")["S1"] = {"name": "S1", "report": "R1", "enabled": 1,
                                                          "frequency": "Daily"}

    def test_disabled_while_queued_sends_nothing(self):
        self.site.table("Insight Report Schedule")["S1"]["enabled"] = 0
        self.sch._dispatch_by_name("S1")
        self.assertEqual(self.sent, [])
        self.assertIn("SKIPPED", self.site.table("Insight Report Schedule")["S1"]["last_status"])

    def test_deleted_or_already_sent_today_sends_nothing(self):
        self.sch._dispatch_by_name("missing")
        self.site.table("Insight Report Schedule")["S1"].update(last_run=self.sch.nowdate() + " 06:00:00",
                                                                last_status="OK — email:1")
        self.sch._dispatch_by_name("S1")
        self.assertEqual(self.sent, [])
        self.site.table("Insight Report Schedule")["S1"]["last_status"] = "FAILED — see Error Log"
        self.sch._dispatch_by_name("S1")
        self.assertEqual(self.sent, ["S1"])                        # a failed run may be retried


# ── 6. other imports: unreadable cells are reported, never dropped ───────────

class OtherImports(unittest.TestCase):
    def test_cash_flow_template_reports_errors_and_unsaved_formulas(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        ff.install()
        self.addCleanup(ff.uninstall)
        from neotec_insight.neotec_insight.utils.cash_flow_import import parse_statement_template_sheet
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Sl", "Collections", "Jan-26", "Feb-26", "Mar-26"])
        ws.append([1, "Customer receipts", 100, "#DIV/0!", "=1/0"])
        ws.append([2, "Other", "", 0, "abc"])
        buf = io.BytesIO()
        wb.save(buf)
        out = parse_statement_template_sheet(buf.getvalue(), fiscal_year=2026)
        bad = " | ".join(out["invalid"])
        self.assertEqual(len(out["invalid"]), 3, bad)
        self.assertIn("formula without a saved result", bad)
        self.assertIn("#DIV/0!", bad)
        first = out["lines"][0]["budgets"]
        self.assertEqual(list(first.values()), [100.0])
        self.assertEqual(list(out["lines"][1]["budgets"].values()), [0.0])

    def test_head_count_paste_names_unreadable_cells(self):
        ff.install()
        self.addCleanup(ff.uninstall)
        from neotec_insight.neotec_insight.api.allocation import head_count_problems
        text = "Cost centre\tJan\tFeb\nSales\t4\tfour\nAdmin\t2\t-\n"
        self.assertEqual(head_count_problems(text), ["line 2 (Sales), month 2: four"])


# ── 7. silent fallbacks found by the audit ───────────────────────────────────

class NoSilentZeros(unittest.TestCase):
    def test_sources_no_longer_swallow_figures(self):
        rep = (APP / "api" / "report.py").read_text()
        self.assertIn('budget_errors[key]["months"]', rep)                     # budget formulas reported
        self.assertIn("party openings failed", rep)                            # ledger fails, not 0 opening
        self.assertIn("per_account_prev = None", rep)                          # no comparison, not zeros
        ana = (APP / "api" / "analytics.py").read_text()
        self.assertIn('"failed": failed', ana)
        for f in ("cash_flow_forecast.py", "cashflow.py", "brand.py", "health.py", "ai.py"):
            self.assertNotRegex((APP / "api" / f).read_text(), r'get_all\(\s*"Company"', f)


if __name__ == "__main__":
    unittest.main()
