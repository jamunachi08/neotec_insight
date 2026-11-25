"""v3.9.8 — health check H1: company scope after API-key / token authentication."""
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import _fakefrappe as ff  # noqa: E402
from test_v2_90_security import Site  # noqa: E402

M = "neotec_insight.neotec_insight.api.ageing.get_ageing"


class TokenScope(Site):
    def test_registered_after_authentication(self):
        hooks = (HERE.parents[0] / "neotec_insight" / ".." / "hooks.py").resolve()
        src = (HERE.parents[1] / "neotec_insight" / "hooks.py").read_text()
        self.assertIn('auth_hooks = ["neotec_insight.neotec_insight.utils.access.enforce_request_scope"]', src)
        _ = hooks

    def test_token_call_is_scoped_once_identity_is_known(self):
        from neotec_insight.neotec_insight.utils.access import enforce_request_scope
        # before_request: the token is not checked yet — Guest, nothing to scope
        self.site.user = "Guest"
        self.frappe.request = types.SimpleNamespace(path=f"/api/method/{M}")
        self.frappe.local = types.SimpleNamespace(site=self.site.site_name, form_dict={"company": "Beta Co"})
        enforce_request_scope()
        # auth hook: Frappe has set the token's user — now it is scoped
        self.site.user = "api@a.co"
        self.site.roles["api@a.co"] = {"Accounts User"}
        self.site.allowed_companies["api@a.co"] = ["Alpha Co"]
        with self.assertRaises(self.frappe.PermissionError):
            enforce_request_scope()

    def test_runs_once_per_user_per_request(self):
        self.as_user("acc@a.co", {"Accounts User"}, ["Alpha Co"])
        self.request(M, company="Alpha Co")
        self.frappe.local.form_dict["company"] = "Beta Co"      # a second run for the same user is skipped
        from neotec_insight.neotec_insight.utils.access import enforce_request_scope
        enforce_request_scope()


class GroupView(Site):
    def setUp(self):
        super().setUp()
        from neotec_insight.neotec_insight.api import group_view as gv
        gv._check_group_view_access = lambda: None
        gv._require_read = lambda: None
        self.gv = gv

    def test_company_outside_scope_and_duplicates_refused(self):
        self.as_user("grp@a.co", {"Accounts User"}, ["Alpha Co"])
        with self.assertRaises(self.frappe.PermissionError):
            self.gv.get_group_dashboard(report="x", fiscal_year=2026, companies='["Alpha Co", "Beta Co"]')
        with self.assertRaises(self.frappe.ValidationError):
            self.gv.get_group_dashboard(report="x", fiscal_year=2026, companies='["Alpha Co", "Alpha Co"]')


if __name__ == "__main__":
    unittest.main()
