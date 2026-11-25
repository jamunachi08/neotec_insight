"""v3.9.9 — statement lines hold their drafted charge journal in its own field.
Lines drafted earlier carry it only in their match: copy it across."""
import json

import frappe


def execute():
    frappe.reload_doc("neotec_insight", "doctype", "insight_bank_statement_line", force=True)
    rows = frappe.db.sql("""select name, match_json from `tabInsight Bank Statement Line`
                            where ifnull(draft_journal, '') = '' and match_source like 'Draft entry%%'""",
                         as_dict=True)
    for r in rows:
        try:
            dt, dn = json.loads(r.match_json or "[]")[0][:2]
        except Exception:
            continue
        if dt == "Journal Entry" and frappe.db.exists("Journal Entry", dn):
            frappe.db.set_value("Insight Bank Statement Line", r.name, "draft_journal", dn, update_modified=False)
