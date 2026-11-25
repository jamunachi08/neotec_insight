// v3.9.7 — General Ledger account tree in ERPNext's chart-of-accounts order
import assert from 'node:assert/strict';
import { childrenByParent, sortByTree, treeRank } from '../src/utils/accountTree.ts';

const A = (name, parent = null) => ({ name, parent_account: parent, is_group: 1 });
const L = (name, parent) => ({ name, parent_account: parent, is_group: 0 });
const E = '3/0/00/00/000 - Shareholder`s Equity.. Shareholder`s Equity.. - DSC';
const C = '5/0/00/00/000 - Costs of Goods and Providing Services - DSC';
// rows as they came before (internal lft order)
const rows = [
  A('1/0/00/00/000 - Assets - DSC'), A(E), A('Retained Earnings - DSC', E), A('3/1/00/00/000 - Capital & Equity - DSC', E),
  A(C), A('Direct Expenses - DSC', C), A('Indirect Expenses - DSC', C), A('5/1/00/00/000 - Costs of Goods - DSC', C),
  A('4/0/00/00/000 - Revenue - DSC'), A('2/0/00/00/000 - Liabilities - DSC'), A('6/0/00/00/000 - Operating Expenses - DSC'),
];
const m = childrenByParent(rows);
assert.deepEqual(m.__root__.map((n) => n.name.slice(0, 1)), ['1', '2', '3', '4', '5', '6']);        // as ERPNext
assert.deepEqual(m[E].map((n) => n.name), ['3/1/00/00/000 - Capital & Equity - DSC', 'Retained Earnings - DSC']);
assert.deepEqual(m[C].map((n) => n.name),
  ['5/1/00/00/000 - Costs of Goods - DSC', 'Direct Expenses - DSC', 'Indirect Expenses - DSC']);
assert.deepEqual(childrenByParent([]), {});

// v3.9.11 — the ledger in tree order whatever order the accounts were picked
// (the reported export: 5/… accounts first, 4/… in between)
const chart = [
  A('4/0/00/00/000 - Income - DSC'), A('5/0/00/00/000 - Expenses - DSC'),
  A('4/1/01/00/000 - Revenue - DSC', '4/0/00/00/000 - Income - DSC'),
  A('5/1/01/00/000 - Direct Costs - DSC', '5/0/00/00/000 - Expenses - DSC'),
  L('4/1/01/01/001 - Software/Subscription Revenue - DSC', '4/1/01/00/000 - Revenue - DSC'),
  L('4/1/01/01/003 - Camera & Training revenues - DSC', '4/1/01/00/000 - Revenue - DSC'),
  L('4/1/01/02/001 - Support دعم - DSC', '4/1/01/00/000 - Revenue - DSC'),
  L('4/1/01/02/002 - Others Revenue - DSC', '4/1/01/00/000 - Revenue - DSC'),
  L('5/1/01/01/001 - Hosting Expenses - DSC', '5/1/01/00/000 - Direct Costs - DSC'),
  L('5/1/01/01/003 - Internal Engineering - DSC', '5/1/01/00/000 - Direct Costs - DSC'),
  L('5/1/01/01/004 - Customer Success & Operations - DSC', '5/1/01/00/000 - Direct Costs - DSC'),
  L('5/1/01/01/005 - Direct Third Party Costs - DSC', '5/1/01/00/000 - Direct Costs - DSC'),
];
const picked = ['5/1/01/01/004', '5/1/01/01/005', '4/1/01/01/001', '4/1/01/01/003', '5/1/01/01/003',
  '4/1/01/02/001', '5/1/01/01/001', '4/1/01/02/002']
  .map((n) => ({ name: chart.find((c) => c.name.startsWith(n)).name }));
const rank = treeRank(childrenByParent(chart));
assert.deepEqual(sortByTree(picked, rank).map((a) => a.name.slice(0, 13)),
  ['4/1/01/01/001', '4/1/01/01/003', '4/1/01/02/001', '4/1/01/02/002',
   '5/1/01/01/001', '5/1/01/01/003', '5/1/01/01/004', '5/1/01/01/005']);
// not in the chart (tree not loaded yet): last, by name
assert.deepEqual(sortByTree([{ name: 'Z' }, { name: 'B' }, picked[0]], rank).map((a) => a.name.slice(0, 13)),
  ['5/1/01/01/004', 'B', 'Z']);

console.log('account tree: passed');
