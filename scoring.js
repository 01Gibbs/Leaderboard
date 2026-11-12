// The leaderboard's rules: what counts as each result, what everything is worth, and how participants.csv is
// read. index.html and the walkthrough load this file; the grader reads the RULES block below (grader/rules.py),
// so both sides always agree. Change points or status words here, and nowhere else.
// RULES must stay plain JSON (double quotes, no trailing commas) because Python reads it too.

const RULES = /* rules:start */ {
  "points": { "none": 0, "submitted": 10, "correct": 30, "stretch": 5, "helped": 5, "bonus": 1 },
  "statuses": {
    "correct": ["correct", "passed", "pass", "yes", "y", "done"],
    "submitted": ["submitted", "partial", "attempted", "in review"]
  },
  "baseColumns": ["name", "github"],
  "counts": ["stretch", "helped", "bonus"],
  "delimiters": [",", ";", "\t"]
} /* rules:end */;

/* ---- reading participants.csv (quotes, commas inside quotes, CRLF, BOM) ---- */
function parseCSV(text) {
  text = text.replace(/^﻿/, '');
  // Excel in some regions saves CSV with ";" or tabs, so use whichever the header row uses most.
  const first = text.split(/\r?\n/)[0] || '';
  const n = (ch) => first.split(ch).length - 1;
  const delim = RULES.delimiters.slice().sort((a, b) => n(b) - n(a))[0];
  const out = []; let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; }
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === delim) { row.push(cur); cur = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(cur); cur = ''; out.push(row); row = [];
    } else cur += c;
  }
  if (cur !== '' || row.length) { row.push(cur); out.push(row); }
  return out.filter((r) => r.some((v) => v.trim() !== ''));
}
function normHeader(h) { return h.trim().toLowerCase().replace(/[\s-]+/g, '_'); }
function normStatus(v) {
  const s = String(v || '').trim().toLowerCase();
  for (const status of ['correct', 'submitted']) if (RULES.statuses[status].includes(s)) return status;
  return 'none';
}
function toInt(v) { const n = parseInt(String(v || '').trim(), 10); return Number.isFinite(n) ? n : 0; }
function toCount(v) { return Math.max(0, toInt(v)); }
function titleCase(k) { const s = k.replace(/_/g, ' '); return s.charAt(0).toUpperCase() + s.slice(1); }

// participants.csv text -> { rows: [{ name, tracks: {key: status}, stretch, helped, bonus }], skipped, tracks }.
// `tracks` is the exercises as [{ k, label }]; when not given, every column that is not a base or count column is one.
function readParticipants(text, tracks) {
  const table = parseCSV(text);
  if (!table.length) return { rows: [], skipped: 0, tracks: tracks || [] };
  const head = table[0].map(normHeader);
  const cell = (r, k) => { const i = head.indexOf(k); return i < 0 ? '' : (r[i] || ''); };
  if (!tracks || !tracks.length) {
    const fixed = RULES.baseColumns.concat(RULES.counts);
    tracks = head.filter((h) => h && !fixed.includes(h)).map((k) => ({ k, label: titleCase(k) }));
  }
  const rows = []; let skipped = 0;
  for (const r of table.slice(1)) {
    const name = cell(r, 'name').trim().slice(0, 80);
    if (!name) { skipped++; continue; }
    const p = { name, tracks: {}, stretch: toCount(cell(r, 'stretch')), helped: toCount(cell(r, 'helped')), bonus: toInt(cell(r, 'bonus')) };
    tracks.forEach((t) => { p.tracks[t.k] = normStatus(cell(r, t.k)); });
    rows.push(p);
  }
  return { rows, skipped, tracks };
}

/* ---- scoring ---- */
function pointsOf(p, tracks) {
  let t = 0;
  for (const tr of tracks) t += RULES.points[p.tracks[tr.k] || 'none'] || 0;
  return t + p.stretch * RULES.points.stretch + p.helped * RULES.points.helped + p.bonus * RULES.points.bonus;
}
