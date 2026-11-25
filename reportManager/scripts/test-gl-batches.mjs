// v3.9.12 — the General Ledger holds every selected account (fetched in batches)
import assert from 'node:assert/strict';
import { batches, mergeLedgers, GL_BATCH } from '../src/utils/glBatches.ts';

const names = Array.from({ length: 63 }, (_v, i) => `A${String(i).padStart(3, '0')}`);
const b = batches(names);
assert.equal(GL_BATCH, 25);
assert.deepEqual(b.map((x) => x.length), [25, 25, 13]);
assert.deepEqual(b.flat(), names);                                  // nothing lost, order kept
assert.deepEqual(batches([], 25), []);

const part = (accs, dr, cr) => ({ accounts: accs.map((a) => ({ account: a })), report_total: { debit: dr, credit: cr, balance_raw: dr - cr },
  filters: { from_date: '2026-01-01', account_count: accs.length, is_filtered: 0 } });
const m = mergeLedgers([part(['A', 'B'], 100, 40), part(['C'], 5.5, 0.25)]);
assert.deepEqual(m.accounts.map((a) => a.account), ['A', 'B', 'C']);
assert.deepEqual(m.report_total, { debit: 105.5, credit: 40.25, balance_raw: 65.25 });
assert.equal(m.filters.account_count, 3);
assert.equal(m.filters.from_date, '2026-01-01');
assert.equal(mergeLedgers([]), null);
console.log('gl batches: passed');
