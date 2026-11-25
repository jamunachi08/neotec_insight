import { useEffect, useMemo, useState } from 'react';
import { t } from '../../utils/i18n';
import { api } from '../../utils/api';
import { useDimFilters, compactDimFilters } from '../../utils/dimFilters';
import { ActiveDimFiltersChips } from '../ActiveDimFiltersChips';

/* ─── Group view (v1.9.38) ──────────────────────────────────────────────────
 * Multi-company aggregated dashboard.
 *
 * Layer 1 scope: pick a P&L report + fiscal year + a subset of companies,
 * pick a presentation currency, and see (a) the rolled-up group totals in
 * that currency, and (b) each subsidiary's KPIs in its OWN native currency
 * side-by-side. Currency translation uses ERP Currency Exchange period
 * averages (with fallbacks).
 *
 * INTERCOMPANY IS NOT ELIMINATED. The banner says so. This is an indicative
 * group roll-up, not a statutory consolidation.
 */

type Company = { name: string; label: string; currency: string; is_group: number; parent_company: string };

const KPI_KEYS = ['total_revenue', 'gross_profit', 'ebitda', 'net_income'] as const;
const KPI_LABELS: Record<string, string> = {
  total_revenue: 'Revenue',
  gross_profit: 'Gross Profit',
  ebitda: 'EBITDA',
  net_income: 'Net Income',
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function fmt(v: number, decimals = 0): string {
  if (!isFinite(v)) return '—';
  return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtShort(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
  if (abs >= 1_000) return (v / 1_000).toFixed(0) + 'K';
  return v.toFixed(0);
}

export function GroupApp() {
  const [reports, setReports] = useState<Array<{ name: string; report_name: string; slug: string }>>([]);
  const [report, setReport] = useState<string>('');
  const [fy, setFy] = useState<number>(new Date().getFullYear());
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [presCur, setPresCur] = useState<string>('');
  // v3.9.9 — whose fiscal calendar the group year follows (every company is
  // measured over those same calendar months)
  const [refCompany, setRefCompany] = useState<string>('');
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  // v1.9.52 — group view honours custom Accounting Dimension filters set
  // in the Run tab. Each per-company execute_report in the aggregation
  // pipeline receives the same scope, so the rollup totals reflect the
  // active filter scope.
  const { filters: dimFilters } = useDimFilters();

  // Initial load: reports + companies.
  useEffect(() => {
    let cancelled = false;
    api.listReports()
      .then((rs) => {
        if (cancelled) return;
        const list = (rs || []) as any[];
        setReports(list);
        if (list.length && !report) setReport(list[0].slug || list[0].name);
      })
      .catch(() => { /* leave empty */ });
    api.listGroupCompanies()
      .then((cs) => {
        if (cancelled) return;
        const list = (cs || []) as Company[];
        setCompanies(list);
        // Default presentation currency: the currency of the first non-group
        // company (heuristic: holding companies often have is_group=1, so
        // pick the first operating one). If none, take the very first.
        const firstOp = list.find((c) => !c.is_group && c.currency) || list[0];
        if (firstOp?.currency && !presCur) setPresCur(firstOp.currency);
      })
      .catch((e: any) => {
        if (cancelled) return;
        // 403 etc. — set a friendly error so the page doesn't render blank.
        setError(String(e?.message || e || 'Failed to load companies.'));
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const distinctCurrencies = useMemo(() => {
    const s = new Set<string>();
    for (const c of companies) if (c.currency) s.add(c.currency);
    return Array.from(s).sort();
  }, [companies]);

  const selectedList = useMemo(() => Array.from(selected), [selected]);

  function toggleCompany(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }
  function selectAll() { setSelected(new Set(companies.map((c) => c.name))); }
  function clearAll() { setSelected(new Set()); }

  function run() {
    if (!report || !fy || selected.size === 0 || !presCur) {
      setData(null);
      return;
    }
    setLoading(true);
    setError('');
    const ref = refCompany && selected.has(refCompany) ? refCompany : selectedList[0];
    api.getGroupDashboard(report, fy, selectedList, presCur, compactDimFilters(dimFilters) || null, ref)
      .then((r) => setData(r))
      .catch((e: any) => { setError(String(e?.message || e || 'Failed to load group data.')); setData(null); })
      .finally(() => setLoading(false));
  }

  if (error && companies.length === 0) {
    return (
      <div className="dash-shell">
        <div className="dash-empty">
          <h2>{t('Group view unavailable')}</h2>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dash-shell group-shell">
      {/* Header */}
      <div className="dash-head">
        <div>
          <h2 className="dash-title">{t('Group view')}</h2>
          <span className="dash-sub">Multi-company aggregated dashboard — pick subsidiaries to roll up.</span>
          <ActiveDimFiltersChips />
        </div>
        <div className="dash-controls">
          <label>
            <span className="flbl">{t('Report')}</span>
            <select value={report} onChange={(e) => setReport(e.target.value)}>
              {reports.map((r) => (
                <option key={r.name} value={r.slug || r.name}>{r.report_name}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="flbl">{t('Fiscal Year')}</span>
            <input type="number" value={fy} onChange={(e) => setFy(Number(e.target.value) || fy)} style={{ width: 84 }} />
          </label>
          <label>
            <span className="flbl">{t('Presentation Currency')}</span>
            <select value={presCur} onChange={(e) => setPresCur(e.target.value)}>
              {distinctCurrencies.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label>
            <span className="flbl">{t('Fiscal calendar of')}</span>
            <select value={refCompany && selected.has(refCompany) ? refCompany : (selectedList[0] || '')}
                    onChange={(e) => setRefCompany(e.target.value)} disabled={selected.size === 0}>
              {selectedList.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <button className="dash-run-btn" onClick={run} disabled={selected.size === 0 || loading}>
            {loading ? 'Running…' : `Run group view (${selected.size})`}
          </button>
        </div>
      </div>

      {/* Banner — honest scope statement */}
      <div className="group-banner">
        <i className="ti ti-alert-circle" aria-hidden />
        <div>
          <strong>Layer 1 — aggregated, not eliminated.</strong> Intercompany transactions are included in both revenue
          and expense. Comparatives use the original-period rates (no retranslation). This is an indicative group view,
          not a statutory consolidation.
        </div>
      </div>

      {/* Company picker */}
      <div className="group-picker">
        <div className="group-picker-head">
          <span className="dash-block-title">Companies in the roll-up ({selected.size} of {companies.length})</span>
          <div className="group-picker-actions">
            <button className="group-pick-action" onClick={selectAll}>{t('Select all')}</button>
            <button className="group-pick-action" onClick={clearAll}>{t('Clear')}</button>
          </div>
        </div>
        <div className="group-picker-grid">
          {companies.map((c) => {
            const on = selected.has(c.name);
            return (
              <label key={c.name} className={'group-pick-card' + (on ? ' is-on' : '')}>
                <input type="checkbox" checked={on} onChange={() => toggleCompany(c.name)} />
                <div className="group-pick-body">
                  <span className="group-pick-name">{c.label}</span>
                  <span className="group-pick-meta">
                    {c.currency || '—'}{c.is_group ? ' · holding' : ''}
                  </span>
                </div>
              </label>
            );
          })}
          {companies.length === 0 && <div className="dash-sub">No companies available in this bench.</div>}
        </div>
      </div>

      {data && <GroupResults data={data} />}
    </div>
  );
}

function GroupResults({ data }: { data: any }) {
  const presCur = data.presentation_currency || '';
  const group = data.group || {};
  const byCompany = data.by_company || [];
  const fxGaps = data.fx_gaps || [];
  // v3.9.8 — figures by calendar month; the group total is withheld when a company
  // failed or a month has no exchange rate (never zero-filled or translated at 1.0)
  const complete = data.complete !== false;
  const periods: string[] = data.periods || [];
  const periodLabel = (p: string) => {
    const [y, m] = p.split('-');
    return `${MONTHS[Number(m) - 1] || m} ${y.slice(2)}`;
  };
  const cols = periods.length ? periods.map(periodLabel) : MONTHS;

  return (
    <>
      {data.period && (
        <div className="group-banner">
          <i className="ti ti-calendar" aria-hidden />
          <div>
            <strong>{t('Period')}:</strong> {periodLabel(data.period.from)} – {periodLabel(data.period.to)}, {t('the fiscal year of')} {data.period.calendar_of}.
            {(data.period.restated_companies || []).length > 0 && (
              <> {t('Restated to these months (their own fiscal year differs)')}: {data.period.restated_companies.join(', ')}.</>
            )}
          </div>
        </div>
      )}
      {(data.failed_companies || []).length > 0 && (
        <div className="group-banner group-banner-warn">
          <i className="ti ti-alert-triangle" aria-hidden />
          <div>
            <strong>Incomplete group.</strong> These companies could not be produced, so the group total is
            withheld: {(data.failed_companies || []).join(', ')}. See the Error Log.
          </div>
        </div>
      )}
      {!complete && (data.failed_companies || []).length === 0 && fxGaps.length === 0 && (
        <div className="group-banner group-banner-warn">
          <i className="ti ti-alert-triangle" aria-hidden />
          <div><strong>{t('Some group figures are withheld.')}</strong> {data.withheld_reason}</div>
        </div>
      )}
      {fxGaps.length > 0 && (
        <div className="group-banner group-banner-warn">
          <i className="ti ti-currency-exchange" aria-hidden />
          <div>
            <strong>Missing exchange rates.</strong> Add Currency Exchange records for these months; the group
            total is withheld until then:
            <ul style={{ margin: '4px 0 0 18px' }}>
              {fxGaps.map((g: any, i: number) => (
                <li key={i}>{g.company}: {g.from} → {g.to}{g.months?.length ? ` (${g.months.map(periodLabel).join(', ')})` : ''}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Group KPI tiles in presentation currency */}
      <div className="dash-tiles">
        {KPI_KEYS.map((k) => {
          const v = group[k]?.total;
          const ok = group[k]?.status !== 'withheld';
          const monthly = group[k]?.monthly || [];
          return (
            <div key={k} className="dash-tile">
              <div className="dash-tile-head">
                <span className="dash-tile-lbl">{KPI_LABELS[k]}</span>
                <span className="dash-tile-cur">{presCur}</span>
              </div>
              <div className="dash-tile-val" title={ok ? undefined : data.withheld_reason}>{ok && v != null ? fmt(v) : '—'}</div>
              <div className="dash-tile-spark">
                {ok && <MiniSpark data={monthly} />}
              </div>
            </div>
          );
        })}
      </div>

      {/* Per-company breakdown in native currencies */}
      <div className="dash-card" style={{ marginTop: 18 }}>
        <div className="dash-block-head">
          <div>
            <h3 className="dash-variance-title">By company — native currency</h3>
            <span className="dash-sub">
              Each subsidiary in its own currency. The group totals above are in {presCur}.
            </span>
          </div>
        </div>
        <table className="dash-variance-table group-by-co">
          <thead>
            <tr>
              <th>{t('Company')}</th>
              <th className="num">{t('Currency')}</th>
              {KPI_KEYS.map((k) => <th key={k} className="num">{KPI_LABELS[k]}</th>)}
              <th className="num" title={`Equivalent net income in ${presCur}`}>Net in {presCur}</th>
            </tr>
          </thead>
          <tbody>
            {byCompany.map((row: any) => row.status === 'failed' ? (
              <tr key={row.company}>
                <td>{row.company}</td>
                <td className="num">{row.currency}</td>
                <td colSpan={KPI_KEYS.length + 1} className="num" title={row.error}>{t('Failed')} — {row.error}</td>
              </tr>
            ) : (
              <tr key={row.company}>
                <td>{row.company}</td>
                <td className="num">{row.currency}</td>
                {KPI_KEYS.map((k) => {
                  const kp = row.kpis?.[k];
                  return kp && kp.status && kp.status !== 'ok'
                    ? <td key={k} className="num" title={kp.message}>{t(kp.status === 'missing' ? 'Not in report' : 'Calculation failed')}</td>
                    : <td key={k} className="num">{fmt(kp?.native_total ?? 0)}</td>;
                })}
                <td className="num">{row.kpis?.net_income?.presentation_total == null ? '—' : fmt(row.kpis.net_income.presentation_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Monthly group revenue (presentation currency) — a sanity-check view */}
      <div className="dash-card" style={{ marginTop: 18 }}>
        <div className="dash-block-head">
          <div>
            <h3 className="dash-variance-title">Group monthly — {presCur}</h3>
            <span className="dash-sub">Sum of all selected companies, translated month by month.</span>
          </div>
        </div>
        <table className="dash-variance-table">
          <thead>
            <tr>
              <th>{t('KPI')}</th>
              {cols.map((m) => <th key={m} className="num">{m}</th>)}
              <th className="num">{t('Total')}</th>
            </tr>
          </thead>
          <tbody>
            {KPI_KEYS.map((k) => {
              const monthly = group[k]?.monthly || [];
              const total = group[k]?.total;
              const ok = group[k]?.status !== 'withheld';
              return (
                <tr key={k}>
                  <td>{KPI_LABELS[k]}</td>
                  {cols.map((_, i) => (
                    <td key={i} className="num">{ok && monthly[i] != null ? fmtShort(monthly[i]) : '—'}</td>
                  ))}
                  <td className="num"><strong>{ok && total != null ? fmt(total) : '—'}</strong></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function MiniSpark({ data }: { data: number[] }) {
  if (!data || data.length === 0) return null;
  const min = Math.min(...data, 0);
  const max = Math.max(...data, 0);
  const span = (max - min) || 1;
  const W = 120, H = 28;
  const stepX = W / Math.max(1, data.length - 1);
  const pts = data.map((v, i) => [i * stepX, H - ((v - min) / span) * H] as [number, number]);
  const path = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H}>
      <path d={path} fill="none" stroke="#0c447c" strokeWidth="1.5" />
    </svg>
  );
}
