"""Multi-company group view: aggregation and currency translation
(Layer 1 — intercompany is not eliminated) (v1.9.38).

v2.92.0 — moved unchanged out of api/report.py, which re-exports every
name so the `api.report.<name>` endpoint addresses keep working."""

import json
import frappe
from frappe.utils import cint
from neotec_insight.neotec_insight.utils.access import insight_api
from neotec_insight.neotec_insight.utils.execution import execute_report, load_flag_to_accounts
from neotec_insight.neotec_insight.api.report_shared import _check_group_view_access, _require_read, _resolve_report_doc, _sanitise_dimension_filters


@insight_api()
def list_group_companies() -> list[dict]:
    """Return all enabled companies in the bench, with their default currency.
    Used by the group-view multi-select picker on the dashboard.
    """
    _require_read()
    _check_group_view_access()
    # v3.9.8 — only companies this user may see (user permissions apply)
    rows = frappe.get_list(
        "Company",
        fields=["name", "company_name", "default_currency", "is_group", "parent_company"],
        order_by="company_name asc",
        limit_page_length=0,
    )
    return [
        {
            "name": r["name"],
            "label": r.get("company_name") or r["name"],
            "currency": r.get("default_currency") or "",
            "is_group": int(r.get("is_group") or 0),
            "parent_company": r.get("parent_company") or "",
        }
        for r in rows
    ]


def _avg_rate_for_month(from_currency: str, to_currency: str, year: int, month: int) -> float | None:
    """Average Currency Exchange rate for calendar `year`/`month` (1-12).

    v3.9.8 (H8) — the month is a real calendar month (callers translate each
    company's fiscal-month position first), and a missing rate is None, never a
    silent 1.0: a genuine parity rate of 1.0 is a rate, not a gap.
    Fallbacks: the latest rate before the month, then the inverse pair.
    """
    if not from_currency or not to_currency or from_currency == to_currency:
        return 1.0
    month = int(month)
    first = f"{year}-{month:02d}-01"
    next_first = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
    rows = frappe.db.sql(
        """SELECT exchange_rate FROM `tabCurrency Exchange`
           WHERE from_currency = %s AND to_currency = %s
             AND date >= %s AND date < %s""",
        [from_currency, to_currency, first, next_first],
    )
    rates = [float(r[0]) for r in (rows or []) if r[0] and float(r[0]) > 0]
    if rates:
        return sum(rates) / len(rates)
    prev = frappe.db.sql(
        """SELECT exchange_rate FROM `tabCurrency Exchange`
           WHERE from_currency = %s AND to_currency = %s AND date < %s
           ORDER BY date DESC LIMIT 1""",
        [from_currency, to_currency, first],
    )
    if prev and prev[0][0] and float(prev[0][0]) > 0:
        return float(prev[0][0])
    inv = frappe.db.sql(
        """SELECT exchange_rate FROM `tabCurrency Exchange`
           WHERE from_currency = %s AND to_currency = %s AND date < %s
           ORDER BY date DESC LIMIT 1""",
        [to_currency, from_currency, next_first],
    )
    if inv and inv[0][0] and float(inv[0][0]) > 0:
        return 1.0 / float(inv[0][0])
    return None


KPI_LABELS = {"total_revenue": "Revenue", "gross_profit": "Gross profit", "ebitda": "EBITDA",
              "net_income": "Net income"}


def _kpi_dependencies(definition: dict) -> dict[str, set[str]]:
    """Row key -> every row key it is computed from (itself included), following
    formula references transitively."""
    import re
    rows = {r.get("key"): r for r in (definition.get("rows") or []) if isinstance(r, dict) and r.get("key")}
    refs = {}
    for key, r in rows.items():
        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(r.get("formula") or ""))) \
            if r.get("kind") == "formula" else set()
        refs[key] = {n for n in names if n in rows}
    out = {}
    for key in rows:
        seen, todo = {key}, [key]
        while todo:
            for n in refs.get(todo.pop(), ()):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        out[key] = seen
    return out



def _company_periods(company: str, fy: int, fy_start_month: int | None = None) -> list[str]:
    """Calendar 'YYYY-MM' for each of the 12 fiscal months (index 0 = first month
    of the year), on the company's calendar or the given start month."""
    from neotec_insight.neotec_insight.utils.fiscal_year import fiscal_year_bounds
    start, _end = fiscal_year_bounds(company, fy, fy_start_month_override=fy_start_month)
    out = []
    for m in range(12):
        k = start.month - 1 + m
        out.append(f"{start.year + k // 12}-{k % 12 + 1:02d}")
    return out


@insight_api()
def get_group_dashboard(
    report: str,
    fiscal_year: str | int,
    companies: str | list,
    presentation_currency: str | None = None,
    dimension_filters: dict | str | None = None,
    reference_company: str | None = None,
) -> dict:
    """Aggregate one P&L definition across multiple companies for one fiscal year.

    v3.9.9 — one period for the whole group: every company runs over the same
    calendar months, those of the reference company's fiscal year (the first
    company unless given), so a January-start and a July-start subsidiary are
    added over the same twelve months.

    Returns:
      - group: KPI totals in presentation_currency (revenue, gross_profit,
        ebitda, net_income; monthly series stitched for sparklines)
      - by_company: each company in its OWN currency, with the same KPI set
      - meta: which rate dates were used, gaps in FX data, banner text

    v1.9.52 — dimension_filters is applied to each per-company execute_report
    call, sanitised against the discovered dimension set.

    Layer 1: aggregation only. Does NOT eliminate intercompany.
    """
    _require_read()
    _check_group_view_access()
    fy = cint(fiscal_year)
    if isinstance(companies, str):
        try:
            companies = json.loads(companies)
        except Exception:
            companies = [c.strip() for c in companies.split(",") if c.strip()]
    if not companies or not isinstance(companies, list):
        frappe.throw("companies must be a non-empty list of company names.")
    if len(companies) > 50:
        frappe.throw("Too many companies — please limit to 50 per request.")
    # v3.9.8 (H1, H7) — each company once, and each one the user may read,
    # checked here as well as by the request hook (token calls, internal callers)
    if len({str(c) for c in companies}) != len(companies):
        frappe.throw("Each company can be selected only once.")
    from neotec_insight.neotec_insight.utils.access import check_company
    for c in companies:
        check_company(c)

    doc = _resolve_report_doc(report)
    definition = json.loads(doc.definition_json or "{}")
    flag_to_accounts = load_flag_to_accounts(doc.name)
    dim_filters_safe = _sanitise_dimension_filters(dimension_filters)

    # Resolve each company's native currency.
    company_meta = {}
    for c in companies:
        cur = frappe.db.get_value("Company", c, "default_currency") or ""
        company_meta[c] = {"currency": cur, "name": c}

    # Pick presentation currency: default to the first company's currency
    # if not specified (a sensible default — usually the holding company is
    # listed first or already passed in).
    pres_cur = presentation_currency or company_meta[companies[0]]["currency"] or ""

    KPI_KEYS = ["total_revenue", "gross_profit", "ebitda", "net_income"]
    months_all = list(range(12))

    # v3.9.9 — the group's period: the reference company's fiscal calendar, applied
    # to every company (execute_report's calendar override), so all columns are the
    # same calendar months for all companies.
    from neotec_insight.neotec_insight.utils.fiscal_year import get_company_fy_start_month
    ref = reference_company or companies[0]
    if ref not in companies:
        frappe.throw("The reference company must be one of the selected companies.")
    group_start_month = get_company_fy_start_month(ref)
    periods = _company_periods(ref, fy, group_start_month)

    # Which KPI depends on which rows: a formula error in any row a KPI uses
    # (directly or through other formulas) makes that KPI unavailable.
    deps = _kpi_dependencies(definition)

    # v3.9.8 (H7, H8) / v3.9.9 — a company that fails, a KPI whose calculation
    # failed or is not in the report, or a month without a rate is reported, and
    # the affected group figure is withheld, never shown as zero.
    by_company: list[dict] = []
    group_by_period: dict[str, dict[str, float]] = {k: {} for k in KPI_KEYS}
    fx_gaps: list[dict] = []
    failed: list[str] = []
    kpi_issues: dict[str, list[dict]] = {k: [] for k in KPI_KEYS}

    for c in companies:
        cur = company_meta[c]["currency"] or pres_cur
        own_start = get_company_fy_start_month(c)
        try:
            res = execute_report(
                report_def=definition,
                fiscal_year=fy,
                month_from=0,
                month_to=11,
                segment="total",
                company=c,
                flag_to_accounts=flag_to_accounts,
                dimension_filters=dim_filters_safe or None,
                fy_start_month_override=group_start_month,
            )
        except Exception as e:
            frappe.log_error(f"group_dashboard exec failed for {c}: {e}\n{frappe.get_traceback()}",
                             "Neotec Insight: group")
            failed.append(c)
            by_company.append({"company": c, "currency": cur, "status": "failed",
                               "error": "This company's figures could not be produced. See the Error Log.",
                               "own_calendar": own_start == group_start_month,
                               "kpis": None, "rates_used": None})
            continue

        rows_by_key = {r.get("key"): r for r in (res.get("rows") or [])}
        errors = res.get("formula_errors") or {}

        if cur == pres_cur:
            rates: list[float | None] = [1.0] * 12
        else:
            rates = [_avg_rate_for_month(cur, pres_cur, int(p[:4]), int(p[5:])) for p in periods]
            missing = [periods[m] for m in months_all if rates[m] is None]
            if missing:
                fx_gaps.append({"company": c, "from": cur, "to": pres_cur, "months": missing})

        kpis = {}
        for k in KPI_KEYS:
            bad = sorted(r for r in deps.get(k, {k}) if r in errors)
            if k not in rows_by_key:
                issue = {"company": c, "status": "missing",
                         "message": "This figure is not in the report for this company."}
            elif bad:
                issue = {"company": c, "status": "error", "rows": [
                    {"key": r, "label": errors[r].get("label") or r, "formula": errors[r].get("formula"),
                     "months": sorted(int(m) for m in (errors[r].get("months") or {}))} for r in bad],
                    "message": "Calculation failed in " + ", ".join(errors[r].get("label") or r for r in bad) + "."}
            else:
                issue = None
            if issue:
                kpi_issues[k].append(issue)
                kpis[k] = {"status": issue["status"], "message": issue["message"], "rows": issue.get("rows"),
                           "native_total": None, "native_monthly": [None] * 12,
                           "presentation_total": None, "presentation_monthly": [None] * 12}
                continue
            monthly = rows_by_key[k].get("monthly") or {}
            native = [float(monthly.get(m, monthly.get(str(m))) or 0.0) for m in months_all]
            pres = [None if rates[m] is None else native[m] * rates[m] for m in months_all]
            whole = all(v is not None for v in pres)
            kpis[k] = {
                "status": "ok",
                "native_total": sum(native),
                "native_monthly": native,
                "presentation_total": sum(pres) if whole else None,
                "presentation_monthly": pres,
            }
            for m in months_all:
                if pres[m] is not None:
                    bucket = group_by_period[k]
                    bucket[periods[m]] = bucket.get(periods[m], 0.0) + pres[m]

        by_company.append({"company": c, "currency": cur,
                           "status": "partial" if any(kpis[k]["status"] != "ok" for k in KPI_KEYS) else "ok",
                           "own_calendar": own_start == group_start_month,
                           "kpis": kpis, "rates_used": rates if cur != pres_cur else None})

    reasons = []
    if failed:
        reasons.append("Not every company could be produced: " + ", ".join(failed) + ".")
    if fx_gaps:
        reasons.append("Exchange rates are missing for: "
                       + "; ".join(f"{g['company']} {g['from']}→{g['to']} ({', '.join(g['months'])})"
                                   for g in fx_gaps) + ".")
    for k in KPI_KEYS:
        for iss in kpi_issues[k]:
            reasons.append(f"{KPI_LABELS.get(k, k)} for {iss['company']}: {iss['message']}")
    group_totals = {}
    for k in KPI_KEYS:
        ok = not failed and not fx_gaps and not kpi_issues[k]
        group_totals[k] = ({"status": "ok", "total": sum(group_by_period[k].values()),
                            "monthly": [group_by_period[k].get(p, 0.0) for p in periods]}
                           if ok else {"status": "withheld", "total": None, "monthly": [None] * len(periods)})
    complete = all(g["status"] == "ok" for g in group_totals.values())
    all_periods = periods
    other_calendars = [r["company"] for r in by_company if not r["own_calendar"]]

    return {
        "report": doc.name,
        "fiscal_year": fy,
        "companies": companies,
        "presentation_currency": pres_cur,
        "group": group_totals,
        "periods": all_periods,
        "period": {"from": periods[0], "to": periods[-1], "calendar_of": ref,
                   "restated_companies": other_calendars},
        "complete": complete,
        "withheld_reason": " ".join(reasons),
        "failed_companies": failed,
        "by_company": by_company,
        "fx_gaps": fx_gaps,
        "notes": {
            "layer": "Layer 1 — aggregation only",
            "intercompany": "Not eliminated. Intercompany transactions are included in both revenue and expense.",
            "rate_convention": "Average rate for each calendar month, from ERPNext Currency Exchange; a month without a rate withholds the group total.",
            "period": "Every company is measured over the same calendar months, those of the reference company's fiscal year; a company with a different fiscal year is restated to them.",
            "comparatives": "Prior-year figures use prior-year rates (no retranslation).",
        },
    }
