/* v3.9.8 — Insight's own small .xlsx writer and reader.
 *
 * Replaces the third-party spreadsheet library (open advisories, no fixed
 * release on the public registry). Insight only ever needs:
 *   - write: one or more sheets from rows of plain values, with column widths;
 *   - read: the first sheet of an uploaded template, as rows of values.
 * Built on fflate (zip). The reader is deliberately narrow: cached cell values
 * only (formulas are never evaluated), bounded sizes, no external references.
 */
import { strToU8, strFromU8, unzipSync, zipSync } from 'fflate';

/** A cell that holds no usable value: an Excel error (#DIV/0!, #REF!, …) or a
 * formula whose result was never saved (the file was written by a program that
 * does not calculate). Kept distinct from a blank cell and from zero (v3.9.9). */
export class CellError {
  readonly kind: 'error' | 'no_result';
  readonly text: string;
  constructor(kind: 'error' | 'no_result', text: string) { this.kind = kind; this.text = text; }
  toString(): string { return this.text; }
}

export type Cell = string | number | boolean | CellError | null | undefined;
export interface SheetSpec { name: string; rows: Cell[][]; cols?: number[] }

const MAX_UNZIPPED = 40 * 1024 * 1024;   // whole package, uncompressed
const MAX_ROWS = 20000;
const MAX_COLS = 200;

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    // characters XML 1.0 cannot carry
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '');
}

export function colName(i: number): string {
  let s = '';
  let n = i + 1;
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

function colIndex(letters: string): number {
  let n = 0;
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
}

function safeSheetName(name: string, used: Set<string>): string {
  let base = (name || 'Sheet').replace(/[[\]:*?/\\]/g, ' ').trim().slice(0, 31) || 'Sheet';
  let n = 2;
  let out = base;
  while (used.has(out.toLowerCase())) { const sfx = ` (${n++})`; out = base.slice(0, 31 - sfx.length) + sfx; }
  used.add(out.toLowerCase());
  base = out;
  return base;
}

function sheetXml(spec: SheetSpec): string {
  const cols = (spec.cols || []).map((w, i) =>
    `<col min="${i + 1}" max="${i + 1}" width="${Math.max(1, Math.min(255, Number(w) || 10))}" customWidth="1"/>`).join('');
  const rows = spec.rows.map((row, r) => {
    const cells = (row || []).map((v, c) => {
      if (v === null || v === undefined || v === '') return '';
      const ref = colName(c) + (r + 1);
      if (typeof v === 'number') return Number.isFinite(v) ? `<c r="${ref}"><v>${v}</v></c>` : '';
      if (typeof v === 'boolean') return `<c r="${ref}" t="b"><v>${v ? 1 : 0}</v></c>`;
      if (v instanceof CellError) return `<c r="${ref}" t="inlineStr"><is><t>${esc(v.text)}</t></is></c>`;
      return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${esc(String(v))}</t></is></c>`;
    }).join('');
    return `<row r="${r + 1}">${cells}</row>`;
  }).join('');
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    + (cols ? `<cols>${cols}</cols>` : '') + `<sheetData>${rows}</sheetData></worksheet>`;
}

/** The .xlsx package bytes for these sheets. */
export function buildXlsx(sheets: SheetSpec[]): Uint8Array {
  const used = new Set<string>();
  const names = sheets.map((s) => safeSheetName(s.name, used));
  const files: Record<string, Uint8Array> = {
    '[Content_Types].xml': strToU8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + '<Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + sheets.map((_s, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')
      + '</Types>'),
    '_rels/.rels': strToU8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
      + '</Relationships>'),
    'xl/workbook.xml': strToU8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
      + names.map((n, i) => `<sheet name="${esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')
      + '</sheets></workbook>'),
    'xl/_rels/workbook.xml.rels': strToU8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + sheets.map((_s, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')
      + '</Relationships>'),
  };
  sheets.forEach((s, i) => { files[`xl/worksheets/sheet${i + 1}.xml`] = strToU8(sheetXml(s)); });
  return zipSync(files, { level: 6 });
}

/** Build and download an .xlsx in the browser. */
export function downloadXlsx(sheets: SheetSpec[], fileName: string): void {
  const bytes = buildXlsx(sheets);
  const blob = new Blob([bytes as BlobPart], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName.endsWith('.xlsx') ? fileName : fileName + '.xlsx';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ── reader ─────────────────────────────────────────────────────────────── */

function unesc(s: string): string {
  return s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|lt|gt|amp|quot|apos);/g, (_m, e: string) => {
    if (e === 'lt') return '<';
    if (e === 'gt') return '>';
    if (e === 'amp') return '&';
    if (e === 'quot') return '"';
    if (e === 'apos') return "'";
    const code = e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
    return code > 0 && code < 0x110000 ? String.fromCodePoint(code) : '';
  });
}

/** Attribute value from an opening tag's text (no regex backtracking over input). */
function attr(tag: string, name: string): string | null {
  const key = ' ' + name + '="';
  const i = tag.indexOf(key);
  if (i < 0) return null;
  const j = tag.indexOf('"', i + key.length);
  return j < 0 ? null : tag.slice(i + key.length, j);
}

/** Every <tag ...>...</tag> (or self-closed) element of `name`, in order. */
function* elements(xml: string, name: string): Generator<{ tag: string; body: string }> {
  const open = '<' + name;
  const close = '</' + name + '>';
  let i = 0;
  for (;;) {
    i = xml.indexOf(open, i);
    if (i < 0) return;
    const after = xml[i + open.length];
    if (after !== ' ' && after !== '>' && after !== '/') { i += open.length; continue; }
    const gt = xml.indexOf('>', i);
    if (gt < 0) return;
    const tag = xml.slice(i, gt + 1);
    if (tag.endsWith('/>')) { yield { tag, body: '' }; i = gt + 1; continue; }
    const end = xml.indexOf(close, gt);
    if (end < 0) return;
    yield { tag, body: xml.slice(gt + 1, end) };
    i = end + close.length;
  }
}

/** Text of all <t> runs inside a string item (plain or rich text). */
function textOf(body: string): string {
  let out = '';
  for (const t of elements(body, 't')) out += unesc(t.body);
  return out;
}

function resolvePath(target: string): string {
  const t = target.replace(/\\/g, '/');
  return t.startsWith('/') ? t.slice(1) : 'xl/' + t.replace(/^\.\//, '');
}

/** Rows of the first worksheet of an .xlsx file, as plain values. */
export function readFirstSheet(data: ArrayBuffer | Uint8Array): Cell[][] {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  if (bytes.length < 4 || bytes[0] !== 0x50 || bytes[1] !== 0x4b) {
    throw new Error('This is not an .xlsx workbook. Save it as Excel Workbook (.xlsx) and try again.');
  }
  let total = 0;
  const wanted = (n: string) => n === 'xl/workbook.xml' || n === 'xl/_rels/workbook.xml.rels'
    || n === 'xl/sharedStrings.xml' || n.startsWith('xl/worksheets/sheet');
  const files = unzipSync(bytes, {
    filter: (f) => {
      if (!wanted(f.name)) return false;
      total += f.originalSize;
      if (total > MAX_UNZIPPED) throw new Error('The workbook is too large to import.');
      return true;
    },
  });
  const text = (n: string) => (files[n] ? strFromU8(files[n]) : '');
  const wbXml = text('xl/workbook.xml');
  const first = elements(wbXml, 'sheet').next().value;
  let sheetPath = 'xl/worksheets/sheet1.xml';
  if (first) {
    const rid = attr(first.tag, 'r:id');
    for (const rel of elements(text('xl/_rels/workbook.xml.rels'), 'Relationship')) {
      if (attr(rel.tag, 'Id') === rid) { sheetPath = resolvePath(attr(rel.tag, 'Target') || ''); break; }
    }
  }
  if (!files[sheetPath]) throw new Error('The workbook has no readable first sheet.');
  const shared: string[] = [];
  for (const si of elements(text('xl/sharedStrings.xml'), 'si')) shared.push(textOf(si.body));

  const rows: Cell[][] = [];
  let nextRow = 0;
  for (const row of elements(text(sheetPath), 'row')) {
    const rAttr = Number(attr(row.tag, 'r'));
    const r = Number.isFinite(rAttr) && rAttr > 0 ? rAttr - 1 : nextRow;
    nextRow = r + 1;
    if (r >= MAX_ROWS) throw new Error(`The sheet has more than ${MAX_ROWS} rows.`);
    const out: Cell[] = [];
    let nextCol = 0;
    for (const c of elements(row.body, 'c')) {
      const ref = attr(c.tag, 'r') || '';
      let letters = '';
      for (const ch of ref) { if (ch >= 'A' && ch <= 'Z') letters += ch; else break; }
      const col = letters ? colIndex(letters) : nextCol;
      nextCol = col + 1;
      if (col >= MAX_COLS) continue;
      const t = attr(c.tag, 't') || 'n';
      const vEl = elements(c.body, 'v').next().value;
      const raw = vEl ? unesc(vEl.body) : '';
      const hasFormula = elements(c.body, 'f').next().value !== undefined;
      let v: Cell = null;
      if (t === 'e') v = new CellError('error', raw || '#ERROR');
      else if (hasFormula && !vEl) v = new CellError('no_result', 'formula without a saved result');
      else if (t === 's') v = shared[Number(raw)] ?? null;
      else if (t === 'inlineStr') v = textOf(c.body);
      else if (t === 'str') v = raw;
      else if (t === 'b') v = raw === '1';
      else if (raw !== '') { const n = Number(raw); v = Number.isFinite(n) ? n : raw; }
      out[col] = v;
    }
    for (let i = 0; i < out.length; i++) if (out[i] === undefined) out[i] = null;
    rows[r] = out;
  }
  for (let i = 0; i < rows.length; i++) if (!rows[i]) rows[i] = [];
  return rows;
}

/* ── budget template cells (v3.9.9) ──────────────────────────────────────── */

export type Amount = { kind: 'blank' } | { kind: 'number'; value: number } | { kind: 'invalid'; reason: string };

/** One amount cell of an import: blank (leave the stored amount as it is), a
 * number (zero included), or invalid (error, formula without a result, text,
 * true/false). Never turns an unusable cell into 0. */
export function readAmount(v: Cell): Amount {
  if (v === null || v === undefined) return { kind: 'blank' };
  if (v instanceof CellError) return { kind: 'invalid', reason: v.kind === 'error' ? `error ${v.text}` : v.text };
  if (typeof v === 'number') return Number.isFinite(v) ? { kind: 'number', value: v } : { kind: 'invalid', reason: 'not a number' };
  if (typeof v === 'boolean') return { kind: 'invalid', reason: `${v ? 'TRUE' : 'FALSE'} is not an amount` };
  const s = v.trim();
  if (s === '') return { kind: 'blank' };
  // plain number text, optionally with thousands separators: 1,234.50 / -75 / (75)
  const neg = /^\(.*\)$/.test(s);
  const body = neg ? s.slice(1, -1).trim() : s;
  if (/^-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$/.test(body)) {
    const n = Number(body.replace(/,/g, ''));
    return { kind: 'number', value: neg ? -n : n };
  }
  return { kind: 'invalid', reason: `"${s.slice(0, 30)}" is not an amount` };
}

/* The budget template: A Dimension Value · B Row Key · C Row Label · D..O M1..M12.
 * An amount cell is a number (zero included) or blank (the stored amount is left
 * unchanged); an error, a formula without a saved result, text or TRUE/FALSE
 * stops the whole import with the cell named. */
export interface ImportRow { value: string; row_key: string; sheet_row: number; months: Record<string, number> }
export interface ParsedImport { rows: ImportRow[]; problems: string[] }

export const HEADER = 'Dimension Value';
const FIRST_MONTH_COL = 3;

export function parseBudgetSheet(arr: Cell[][]): ParsedImport {
  const hi = arr.findIndex((r) => String(r?.[0] ?? '').trim() === HEADER);
  if (hi < 0) return { rows: [], problems: ['Header row not found — use the downloaded template.'] };
  const rows: ImportRow[] = [];
  const problems: string[] = [];
  for (let r = hi + 1; r < arr.length; r++) {
    const line = arr[r] || [];
    const value = String(line[0] ?? '').trim();
    const key = String(line[1] ?? '').trim();
    const months: Record<string, number> = {};
    let cellsUsed = false;
    for (let i = 0; i < 12; i++) {
      const c = FIRST_MONTH_COL + i;
      const a = readAmount(line[c]);
      if (a.kind === 'blank') continue;
      cellsUsed = true;
      if (a.kind === 'invalid') problems.push(`${colName(c)}${r + 1}: ${a.reason}`);
      else months[String(i)] = a.value;
    }
    if (!value && !key) {
      if (cellsUsed) problems.push(`Row ${r + 1}: amounts without a dimension value and row key`);
      continue;
    }
    if (!value || !key) { problems.push(`Row ${r + 1}: both the dimension value and the row key are needed`); continue; }
    rows.push({ value, row_key: key, sheet_row: r + 1, months });
  }
  return { rows, problems };
}
