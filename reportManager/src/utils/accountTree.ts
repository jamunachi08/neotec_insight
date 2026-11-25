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

/** v3.9.11 — position of every account in the tree (depth-first, each level by
 *  name), for putting any list of accounts in the chart's order. */
export function treeRank(childrenOf: Record<string, TreeAcct[]>): Map<string, number> {
  const rank = new Map<string, number>();
  const visit = (key: string) => {
    for (const n of childrenOf[key] || []) {
      if (rank.has(n.name)) continue;          // a cycle never loops
      rank.set(n.name, rank.size);
      visit(n.name);
    }
  };
  visit('__root__');
  // accounts whose parent is not in the list (a partial chart) still get a place
  for (const k of Object.keys(childrenOf)) if (!rank.has(k) && k !== '__root__') visit(k);
  return rank;
}

/** `items` in tree order; anything not in the tree goes last, by name. Pure. */
export function sortByTree<T extends { name: string }>(items: T[], rank: Map<string, number>): T[] {
  const big = Number.MAX_SAFE_INTEGER;
  return [...items].sort((a, b) =>
    (rank.get(a.name) ?? big) - (rank.get(b.name) ?? big)
    || a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}
