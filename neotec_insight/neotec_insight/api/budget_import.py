# Copyright (c) 2026, Neotec Integrated Solution
# Budget Import (v2.37.0) — bulk budgeting for dimension books. One template,
# all cost centers (or departments/projects/custom values): download it,
# fill amounts, upload back. The engine validates before writing anything and
# creates/updates one budget book per dimension value plus its cells.
from __future__ import annotations

import io
import json

import frappe
from frappe import _

from neotec_insight.neotec_insight.utils.access import insight_api

_DIM_DOCTYPE = {"cost_center": "Cost Center", "department": "Department", "project": "Project"}


def _source_rows(report):
    doc = frappe.get_doc("Insight Report Definition", report)
    definition = json.loads(doc.definition_json or "{}")
    return doc, [r for r in (definition.get("rows") or [])
                 if r.get("kind") == "source" and not r.get("hidden")]


@insight_api()
def budget_import_template(report=None, fiscal_year=None, dimension_type="cost_center", values=None,
                           custom_dimension_fieldname=None):
    """Styled xlsx template: Dimension Value | Row Key | Row Label | M1..M12.
    One block per dimension value, rows = the report's source rows."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    doc, rows = _source_rows(report)
    if not frappe.has_permission("Insight Budget Book", "create"):
        frappe.throw(_("Not permitted."))
    if isinstance(values, str):
        values = [v.strip() for v in values.split("|") if v.strip()]
    if not values:
        dt = _dimension_doctype(dimension_type, (custom_dimension_fieldname or "").strip() or None)
        if dt and dimension_type == "custom":
            values = frappe.get_list(dt, pluck="name", limit_page_length=200)
        elif dt:
            flt_ = {"company": doc.company} if dt != "Project" else {}
            if dt == "Cost Center":
                flt_["is_group"] = 0
            values = frappe.get_list(dt, filters=flt_, pluck="name", limit_page_length=200)
    if not values:
        frappe.throw(_("No dimension values found — pass them explicitly."))

    wb = Workbook(); ws = wb.active; ws.title = "Budget"
    ws.append([f"Report: {doc.report_name}", f"FY: {fiscal_year}",
               f"Dimension: {custom_dimension_fieldname if dimension_type == 'custom' else dimension_type}"])
    ws["A1"].font = Font(bold=True)
    head = ["Dimension Value", "Row Key", "Row Label"] + [f"M{i}" for i in range(1, 13)]
    ws.append(head)
    for c in ws[2]:
        c.fill = PatternFill("solid", fgColor="2A2440"); c.font = Font(bold=True, color="FFFFFF")
    for v in values:
        for r in rows:
            ws.append([v, r.get("key"), r.get("label")] + [None] * 12)     # v3.9.9 — blank = unchanged
    ws.column_dimensions["A"].width = 34; ws.column_dimensions["C"].width = 40
    buf = io.BytesIO(); wb.save(buf)
    frappe.local.response.filename = f"budget-template-{frappe.scrub(doc.report_name)}-fy{fiscal_year}.xlsx"
    frappe.local.response.filecontent = buf.getvalue()
    frappe.local.response.type = "binary"


@insight_api(methods=["POST"])
def budget_import(report=None, fiscal_year=None, dimension_type="cost_center",
                  custom_dimension_fieldname=None, rows=None):
    """rows = [{value, row_key, months:{'0'..'11': amount}}] parsed client-side.

    v3.9.9 — validated completely before anything is written:
    * an amount must be a number (zero included); a month that is absent or
      null is left as it is in the book (a blank cell does not erase a budget);
      anything else — text, an error value — refuses the whole import with the
      row and month named;
    * a custom dimension needs its field, and books are found by it;
    * a book the user may not edit (approved / locked, or someone else's draft)
      refuses the import.
    M1..M12 in the template = months 0..11 of the company's fiscal year."""
    if not frappe.has_permission("Insight Budget Book", "create"):
        frappe.throw(_("Not permitted."))
    if dimension_type not in ("cost_center", "department", "project", "custom"):
        frappe.throw(_("Unknown dimension type: {0}").format(dimension_type))
    cd_field = (custom_dimension_fieldname or "").strip() or None
    if dimension_type == "custom":
        if not cd_field or not frappe.db.exists("Accounting Dimension", {"fieldname": cd_field}):
            frappe.throw(_("Pick the accounting dimension for a custom-dimension import."))
    else:
        cd_field = None
    doc, src_rows = _source_rows(report)
    valid_keys = {r.get("key") for r in src_rows}
    fiscal_year = int(fiscal_year)
    if isinstance(rows, str):
        rows = json.loads(rows or "[]")
    if not isinstance(rows, list):
        frappe.throw(_("rows must be a list."))

    warnings, clean, invalid = [], [], []
    dt = _dimension_doctype(dimension_type, cd_field)
    seen_values = set()
    seen_pairs = set()
    for n, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            invalid.append(_("Row {0}: not a row.").format(n))
            continue
        value = str(r.get("value") or "").strip()
        key = str(r.get("row_key") or "").strip()
        where = r.get("sheet_row") or n
        if not value:
            continue
        if key not in valid_keys:
            warnings.append(_("Unknown row key skipped: {0}").format(key))
            continue
        if (value, key) in seen_pairs:
            invalid.append(_("Sheet row {0}: {1} / {2} appears more than once.").format(where, value, key))
            continue
        seen_pairs.add((value, key))
        if dt and value not in seen_values and not frappe.db.exists(dt, value):
            warnings.append(_("{0} not found in ERP: {1} (book still created)").format(_(dt), value))
        seen_values.add(value)
        months = {}
        raw_months = r.get("months") or {}
        if not isinstance(raw_months, dict):
            invalid.append(_("Sheet row {0}: months must be an object.").format(where))
            continue
        for m, amt in raw_months.items():
            try:
                mi = int(m)
            except (TypeError, ValueError):
                invalid.append(_("Sheet row {0}: unknown month {1}.").format(where, m))
                continue
            if not 0 <= mi <= 11:
                invalid.append(_("Sheet row {0}: unknown month {1}.").format(where, m))
                continue
            if amt is None or (isinstance(amt, str) and not amt.strip()):
                continue                                  # blank: leave the stored amount as it is
            num = _amount(amt)
            if num is None:
                invalid.append(_("Sheet row {0}, M{1}: {2} is not an amount.").format(where, mi + 1, str(amt)[:30]))
                continue
            months[mi] = num
        clean.append({"value": value, "key": key, "months": months})

    if invalid:
        frappe.throw(_("Nothing was imported. Fix these cells and upload again:") + "<br>"
                     + "<br>".join(frappe.utils.escape_html(x) for x in invalid[:40])
                     + ("<br>…" if len(invalid) > 40 else ""))
    if not clean:
        frappe.throw(_("Nothing importable — check row keys and values."))

    # Books: found by report, year, dimension (and the custom field); every one
    # that exists must be editable by this user before anything is written.
    book_cache, to_create, locked = {}, [], []
    from neotec_insight.neotec_insight.doctype.insight_budget_book.insight_budget_book import (
        InsightBudgetBook,
        auto_label,
        auto_slug,
    )
    for value in sorted({c["value"] for c in clean}):
        filters = {"report": doc.name, "fiscal_year": fiscal_year, "dimension_type": dimension_type,
                   "dimension_value": value}
        if cd_field:
            filters["custom_dimension_fieldname"] = cd_field
        existing = frappe.get_all("Insight Budget Book", filters=filters, pluck="name")
        if existing:
            book = frappe.get_doc("Insight Budget Book", existing[0])
            if not InsightBudgetBook.can_user_edit(book):
                locked.append(f"{book.label or book.name} ({book.status})")
            book_cache[value] = existing[0]
        else:
            to_create.append(value)
    if locked:
        frappe.throw(_("Nothing was imported. You cannot change these budget books: {0}").format(", ".join(locked)),
                     frappe.PermissionError)

    books_created, cells = 0, 0
    for value in to_create:
        b = frappe.new_doc("Insight Budget Book")
        b.report = doc.name
        b.fiscal_year = fiscal_year
        b.dimension_type = dimension_type
        b.dimension_value = value
        b.custom_dimension_fieldname = cd_field
        b.status = "draft"
        # v2.37.2 — slug (docname) and label are derived: FY + dimension (+ the
        # custom field) + value ARE the identity of a book.
        b.label = auto_label(fiscal_year, dimension_type, value, cd_field)
        base = auto_slug(doc.slug or doc.name, fiscal_year, dimension_type, value, cd_field)[:120]
        slug, i = base, 2
        while frappe.db.exists("Insight Budget Book", slug):
            slug = f"{base}-{i}"
            i += 1
        b.slug = slug
        b.insert(ignore_permissions=True)
        book_cache[value] = b.name
        books_created += 1

    for c in clean:
        book = book_cache[c["value"]]
        for m, amt in c["months"].items():
            name = frappe.get_all("Insight Budget Cell",
                                  filters={"book": book, "row_key": c["key"], "month": m},
                                  pluck="name")
            if name:
                frappe.db.set_value("Insight Budget Cell", name[0], "amount", amt)
            else:
                frappe.get_doc({"doctype": "Insight Budget Cell", "book": book, "report": doc.name,
                                "fiscal_year": fiscal_year, "row_key": c["key"], "month": m,
                                "amount": amt}).insert(ignore_permissions=True)
            cells += 1
    frappe.db.commit()
    return {"books_created": books_created, "books_touched": len(book_cache),
            "cells_written": cells, "warnings": warnings[:30]}


def _amount(v) -> float | None:
    """A number, or None when the value is not an amount (never 0 by default)."""
    import math
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        t = v.strip().replace(",", "")
        try:
            f = float(t)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _dimension_doctype(dimension_type, cd_field=None):
    if dimension_type == "custom":
        return frappe.db.get_value("Accounting Dimension", {"fieldname": cd_field}, "document_type") if cd_field else None
    return _DIM_DOCTYPE.get(dimension_type)
