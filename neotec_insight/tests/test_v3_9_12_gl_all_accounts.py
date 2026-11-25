"""v3.9.12 — reported: "Request Line is too large (4560 > 4094)" on the General
Ledger, and only one page of 25 accounts per run. The ledger now goes by POST,
any long GET switches to POST, and every selected account is fetched (in
batches) into one ledger by default."""
import unittest
from pathlib import Path

FRONT = Path(__file__).resolve().parents[2] / "reportManager" / "src"


class GlAllAccounts(unittest.TestCase):
    def test_ledger_request_is_a_post(self):
        api = (FRONT / "utils" / "api.ts").read_text()
        i = api.index("call<any>('report.general_ledger'")
        self.assertIn("}, 'POST');", api[i:i + 400])

    def test_long_get_switches_to_post(self):
        api = (FRONT / "utils" / "api.ts").read_text()
        self.assertIn("const MAX_GET_URL = 1800;", api)
        self.assertIn("if (httpMethod === 'GET' && args && getUrlLength(url, args) > MAX_GET_URL) httpMethod = 'POST';", api)

    def test_all_selected_accounts_by_default(self):
        gl = (FRONT / "features" / "gl" / "GeneralLedger.tsx").read_text()
        self.assertIn("return v === null ? 0 : (parseInt(v) || 0);", gl)       # default: all accounts
        self.assertIn("batches(pageNames)", gl)
        self.assertIn("mergeLedgers(parts)", gl)
        self.assertIn("<option value={0}>{t('All accounts')}", gl)


if __name__ == "__main__":
    unittest.main()
