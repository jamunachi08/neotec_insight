/* v3.9.7 — account tree in ERPNext's order. ERPNext's chart-of-accounts tree
 * lists each level's children by account name (e.g. "1/0/00/00/000 - Assets - DSC"
 * before "2/0/…", and numbered accounts before "Retained Earnings"). Pure. */

export interface TreeAcct { name: string; parent_account?: string | null; [k: string]: any }

const byName = (a: TreeAcct, b: TreeAcct) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });

/** parent name → children (sorted as ERPNext); top level under '__root__'. */
export function childrenByParent<T extends TreeAcct>(rows: T[]): Record<string, T[]> {
  const m: Record<string, T[]> = {};
  for (const n of rows || []) { const p = n.parent_account || '__root__'; (m[p] ||= []).push(n); }
  for (const k of Object.keys(m)) m[k].sort(byName);
  return m;
}
