// v3.9.7 — General Ledger account tree in ERPNext's chart-of-accounts order
import assert from 'node:assert/strict';
import { childrenByParent } from '../src/utils/accountTree.ts';

const A = (name, parent = null) => ({ name, parent_account: parent, is_group: 1 });
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
console.log('account tree: passed');
