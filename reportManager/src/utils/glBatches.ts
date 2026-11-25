/* v3.9.12 — the General Ledger for every selected account in one result.
 *
 * The accounts are fetched in batches (each request stays small and quick) and
 * joined in tree order into one ledger, so the screen, print, PDF and Excel
 * hold every selected account, not one page of them. Pure. */

export const GL_BATCH = 25;

export function batches<T>(items: T[], size = GL_BATCH): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += Math.max(1, size)) out.push(items.slice(i, i + Math.max(1, size)));
  return out;
}

/** One ledger from the batch results, in the order of the batches. */
export function mergeLedgers(parts: any[]): any {
  const ok = parts.filter(Boolean);
  if (!ok.length) return null;
  const accounts = ok.flatMap((p) => p.accounts || []);
  const sum = (k: string) => ok.reduce((s, p) => s + Number(p.report_total?.[k] || 0), 0);
  return {
    ...ok[0],
    accounts,
    report_total: { debit: sum('debit'), credit: sum('credit'), balance_raw: sum('balance_raw') },
    filters: { ...(ok[0].filters || {}), account_count: accounts.length },
  };
}
