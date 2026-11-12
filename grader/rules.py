"""The leaderboard's rules, read from the page's own scoring.js so the grader and the page always agree.

The RULES block in scoring.js (points, status words, columns, delimiters) is the single copy. parse_csv,
norm_header, norm_status, to_int, read_participants and points are ports of scoring.js's functions of the same
names (read_participants always takes the lesson keys; only the page needs to guess them from the columns).
grader/tests/test_rules.py runs both on the same files to prove they agree.
"""
import json
import re
from pathlib import Path

SCORING_JS = Path(__file__).resolve().parents[1] / 'scoring.js'


def _load(path=SCORING_JS):
    text = Path(path).read_text(encoding='utf-8')
    m = re.search(r'/\* rules:start \*/(.*?)/\* rules:end \*/', text, re.S)
    if not m:
        raise RuntimeError(f'{path} has no /* rules:start */ ... /* rules:end */ block')
    return json.loads(m.group(1))


RULES = _load()
STATUSES = ['none', 'submitted', 'correct']  # lowest to highest
RANK = {s: i for i, s in enumerate(STATUSES)}
BASE_COLUMNS = list(RULES['baseColumns'])
COUNTS = list(RULES['counts'])
EARLY_BONUS = RULES['earlyBonus']  # the grader works out this column; facilitators do not edit it
GENERATED = [EARLY_BONUS['column']]


def parse_csv(text):
    """Rows of cells, as scoring.js's parseCSV reads them. Returns (rows, delimiter, had_bom)."""
    bom = text.startswith('﻿')
    text = text[1:] if bom else text
    first = re.split(r'\r?\n', text, maxsplit=1)[0]
    delim = sorted(RULES['delimiters'], key=lambda ch: -first.count(ch))[0]  # stable, like JS sort
    out, row, cur, q, i = [], [], '', False, 0
    while i < len(text):
        c = text[i]
        if q:
            if c == '"':
                if text[i + 1:i + 2] == '"':
                    cur += '"'
                    i += 1
                else:
                    q = False
            else:
                cur += c
        elif c == '"':
            q = True
        elif c == delim:
            row.append(cur)
            cur = ''
        elif c in '\r\n':
            if c == '\r' and text[i + 1:i + 2] == '\n':
                i += 1
            row.append(cur)
            cur = ''
            out.append(row)
            row = []
        else:
            cur += c
        i += 1
    if cur != '' or row:
        row.append(cur)
        out.append(row)
    return [r for r in out if any(v.strip() for v in r)], delim, bom


def norm_header(h):
    key = re.sub(r'[\s-]+', '_', h.strip().lower())
    return RULES['headerAliases'].get(key, key)


def norm_status(v):
    s = str(v or '').strip().lower()
    for status in ('correct', 'submitted'):
        if s in RULES['statuses'][status]:
            return status
    return 'none'


def to_int(v):
    """Like JavaScript's parseInt: leading whole number, else 0 ("7.5" -> 7, "abc" -> 0)."""
    m = re.match(r'([+-]?[0-9]+)', str(v or '').strip())
    return int(m.group(1)) if m else 0


def to_count(v):
    return max(0, to_int(v))


def read_participants(text, tracks):
    """participants.csv text -> {'rows': [{name, tracks, stretch, helped, bonus}], 'skipped': n}, as the page reads it."""
    table, _, _ = parse_csv(text)
    if not table:
        return {'rows': [], 'skipped': 0}
    head = [norm_header(h) for h in table[0]]

    def cell(r, k):
        i = head.index(k) if k in head else -1
        return (r[i] if i < len(r) else '') if i >= 0 else ''

    rows, skipped = [], 0
    for r in table[1:]:
        name = cell(r, 'name').strip()[:80]
        if not name:
            skipped += 1
            continue
        rows.append({'name': name, 'tracks': {k: norm_status(cell(r, k)) for k in tracks},
                     'stretch': to_count(cell(r, 'stretch')), 'prStretch': to_count(cell(r, EARLY_BONUS['column'])),
                     'helped': to_count(cell(r, 'helped')), 'bonus': to_int(cell(r, 'bonus'))})
    return {'rows': rows, 'skipped': skipped}


def points(participant, tracks):
    p = RULES['points']
    return (sum(p[participant['tracks'].get(k, 'none')] for k in tracks)
            + (participant['stretch'] + participant['prStretch']) * p['stretch']
            + participant['helped'] * p['helped'] + participant['bonus'] * p['bonus'])
