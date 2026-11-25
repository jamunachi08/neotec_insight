# Copyright (c) 2026, Neotec Integrated Solution
import frappe
from frappe.model.document import Document

# v3.9.8 (H3) — fields that decide what is sent and to whom
_DELIVERY = ("report", "recipients", "whatsapp_numbers", "enabled")


class InsightReportSchedule(Document):
    def validate(self):
        """Delivery rules on every save, including Desk: whoever creates or changes
        what is sent, or to whom, must be able to run the report and pass the
        recipient policy, and the schedule then runs with their permissions."""
        if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
            return
        if not self.is_new() and not any(self._changed(f) for f in _DELIVERY):
            return
        from neotec_insight.neotec_insight.utils.scheduled_reports import (
            check_recipients,
            preflight_as_current_user,
        )
        if not self.report or not frappe.db.exists("Studio Report", self.report):
            frappe.throw(frappe._("Pick a saved Studio report to schedule."))
        check_recipients(self.recipients or "", self.whatsapp_numbers or "")
        if self.enabled:
            preflight_as_current_user(self.report)
        self.run_as = frappe.session.user

    def _changed(self, field):
        fn = getattr(self, "has_value_changed", None)
        if fn:
            return fn(field)
        before = self.get_doc_before_save() if hasattr(self, "get_doc_before_save") else None
        return before is None or before.get(field) != self.get(field)
