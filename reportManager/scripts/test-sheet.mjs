// v3.9.8 — Insight's own .xlsx writer/reader (replaces the third-party library)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { zipSync, strToU8 } from 'fflate';
import { buildXlsx, readFirstSheet, colName, readAmount, CellError, parseBudgetSheet } from '../src/utils/sheet.ts';

const fx = (n) => readFileSync(new URL(`./fixtures/${n}`, import.meta.url));
const header = (rows) => rows.findIndex((r) => r[0] === 'Dimension Value');

// 1. the budget template as the server builds it (shared strings, styles)
let rows = readFirstSheet(fx('budget-template-current.xlsx'));
let hi = header(rows);
assert.equal(hi, 1);
assert.deepEqual(rows[hi + 1].slice(0, 5), ['Main - DSC', 'revenue', 'Revenue & Sales', 1000, 1000]);
assert.equal(rows[hi + 2][2], 'تكلفة المبيعات');
assert.equal(rows[hi + 2][3], 250.5);
assert.equal(rows.length, 5);

// 2. the same template filled in and re-saved by a spreadsheet application,
//    with a formula: its calculated value is read, the formula is not run
rows = readFirstSheet(fx('budget-template-resaved.xlsx'));
hi = header(rows);
assert.equal(rows[hi + 3][0], 'Riyadh - DSC');
assert.equal(rows[hi + 3][4], 200);
assert.equal(rows[hi + 1][2], 'Revenue & Sales');

// 3. round trip of what Insight writes: text, numbers, blanks, escaping, widths
const aoa = [['Title <&> "q"'], [], ['Row', 'Key', 'M1', 'Annual'], ['Revenue', 'rev', 12.5, -3], [null, '', 0, true]];
const back = readFirstSheet(buildXlsx([{ name: 'Budget', rows: aoa, cols: [40, 18] }, { name: 'Budget', rows: [[1]] }]));
assert.deepEqual(back, [['Title <&> "q"'], [], ['Row', 'Key', 'M1', 'Annual'], ['Revenue', 'rev', 12.5, -3], [null, null, 0, true]]);
assert.equal(colName(0), 'A'); assert.equal(colName(25), 'Z'); assert.equal(colName(26), 'AA'); assert.equal(colName(701), 'ZZ');

// 4. refusals: not an xlsx; an oversized package
assert.throws(() => readFirstSheet(new TextEncoder().encode('Dimension Value,Row Key')), /not an \.xlsx/);
const big = zipSync({ 'xl/workbook.xml': strToU8('<workbook/>'), 'xl/worksheets/sheet1.xml': new Uint8Array(41 * 1024 * 1024) });
assert.throws(() => readFirstSheet(big), /too large/);

// 5. v3.9.9 — error values and formulas without a saved result stay distinct
const ws = '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
  + '<row r="1"><c r="A1" t="inlineStr"><is><t>Dimension Value</t></is></c></row>'
  + '<row r="2"><c r="A2" t="inlineStr"><is><t>Main</t></is></c><c r="B2" t="inlineStr"><is><t>rev</t></is></c>'
  + '<c r="D2" t="e"><v>#DIV/0!</v></c><c r="E2"><f>1+1</f></c><c r="F2"><v>50</v></c><c r="G2"><v>0</v></c>'
  + '<c r="H2" t="inlineStr"><is><t>1,250.50</t></is></c><c r="I2" t="inlineStr"><is><t>n/a</t></is></c></row>'
  + '<row r="3"><c r="A3" t="inlineStr"><is><t>Main</t></is></c><c r="B3" t="inlineStr"><is><t>cost</t></is></c>'
  + '<c r="E3"><v>7</v></c></row></sheetData></worksheet>';
const book = zipSync({
  'xl/workbook.xml': strToU8('<workbook><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>'),
  'xl/_rels/workbook.xml.rels': strToU8('<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'),
  'xl/worksheets/sheet1.xml': strToU8(ws) });
const grid = readFirstSheet(book);
assert.ok(grid[1][3] instanceof CellError && grid[1][3].kind === 'error');
assert.ok(grid[1][4] instanceof CellError && grid[1][4].kind === 'no_result');
assert.equal(grid[1][5], 50);
assert.deepEqual(readAmount(null), { kind: 'blank' });
assert.deepEqual(readAmount('  '), { kind: 'blank' });
assert.deepEqual(readAmount(0), { kind: 'number', value: 0 });
assert.deepEqual(readAmount('(75)'), { kind: 'number', value: -75 });
assert.equal(readAmount(true).kind, 'invalid');
assert.equal(readAmount('1.2.3').kind, 'invalid');
const parsed = parseBudgetSheet(grid);
assert.deepEqual(parsed.problems, ['D2: error #DIV/0!', 'E2: formula without a saved result', 'I2: "n/a" is not an amount']);
assert.deepEqual(parsed.rows[0].months, { 2: 50, 3: 0, 4: 1250.5 });           // blanks are absent, zero kept
assert.deepEqual(parsed.rows[1], { value: 'Main', row_key: 'cost', sheet_row: 3, months: { 1: 7 } });
assert.deepEqual(parseBudgetSheet([['x']]).problems, ['Header row not found — use the downloaded template.']);
assert.deepEqual(parseBudgetSheet([['Dimension Value'], [null, null, null, 5]]).problems,
  ['Row 2: amounts without a dimension value and row key']);

console.log('sheet: passed');
