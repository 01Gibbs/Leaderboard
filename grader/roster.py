"""participants.csv: reading and writing it, and the facilitator actions that change it.

Every facilitator action records the cells it changed in grader/history.json, so `undo` can change exactly
those back, keeping anything anyone changed since.
"""
import csv
import difflib
import io
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CSV_FILE = ROOT / 'participants.csv'
HISTORY = HERE / 'history.json'
LESSONS_FILE = ROOT / 'lessons.json'

STATUSES = ['none', 'submitted', 'correct']
RANK = {s: i for i, s in enumerate(STATUSES)}
COUNTS = ['stretch', 'helped', 'bonus']  # numbers a facilitator can award
BASE_COLUMNS = ['name', 'github']
HISTORY_LIMIT = 100
BOM = '﻿'


class ActionError(Exception):
    """A facilitator action that cannot be done, with a message saying why."""


class NotFound(ActionError):
    pass


def lessons():
    return json.loads(LESSONS_FILE.read_text())


def lesson_keys():
    return [l['key'] for l in lessons()]


def columns():
    return BASE_COLUMNS + lesson_keys() + COUNTS


def norm_status(v):
    s = (v or '').strip().lower()
    if s in ('correct', 'passed', 'pass', 'yes', 'y', 'done'):
        return 'correct'
    if s in ('submitted', 'partial', 'attempted', 'in review'):
        return 'submitted'
    return 'none'


def to_int(v):
    try:
        return int(str(v or '').strip())
    except ValueError:
        return 0


def logins(row):
    """A row's `github` cell may list several accounts, separated by spaces."""
    return [l.lstrip('@') for l in re.split(r'[\s,;|]+', row.get('github', '')) if l.lstrip('@')]


# ---------- reading and writing ----------

class Roster:
    """participants.csv in memory. Writing it back keeps the delimiter, BOM and column order."""

    def __init__(self):
        raw = CSV_FILE.read_text(encoding='utf-8') if CSV_FILE.exists() else ''
        self.text = raw
        self.bom = raw.startswith(BOM)
        body = raw.lstrip(BOM)
        first = body.splitlines()[0] if body else ''
        self.delim = max([',', ';', '\t'], key=first.count) if first else ','  # same rule as index.html
        table = list(csv.reader(io.StringIO(body), delimiter=self.delim))
        self.head = [re.sub(r'[\s-]+', '_', h.strip().lower()) for h in table[0]] if table else []  # same rule as index.html
        self.head += [c for c in columns() if c not in self.head]
        self.rows = []
        for r in table[1:]:
            if any(v.strip() for v in r):
                self.rows.append({h: (r[i].strip() if i < len(r) else '') for i, h in enumerate(self.head)})
        self.loaded = {id(r): dict(r) for r in self.rows}  # to work out which cells an action changed

    def changes(self):
        """[{before, after}] for every row added, removed or edited since loading (None for a missing side)."""
        out = []
        for r in self.rows:
            before = self.loaded.get(id(r))
            if before != r:
                out.append({'before': before, 'after': dict(r)})
        kept = {id(r) for r in self.rows}
        out += [{'before': before, 'after': None} for i, before in self.loaded.items() if i not in kept]
        return out

    def serialise(self):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=self.delim, lineterminator='\n')
        w.writerow(self.head)
        for r in self.rows:
            w.writerow([r.get(h, '') for h in self.head])
        return (BOM if self.bom else '') + buf.getvalue()

    def save(self):
        CSV_FILE.write_text(self.serialise(), encoding='utf-8')

    def new_row(self, name, github=''):
        row = {h: '' for h in self.head} | {'name': name, 'github': github}
        self.rows.append(row)
        return row

    def find(self, who):
        """The one row whose GitHub login (with or without @) or name matches, ignoring case."""
        key = who.strip().lower()
        hits = [r for r in self.rows
                if key.lstrip('@') in (l.lower() for l in logins(r)) or r['name'].strip().lower() == key]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise ActionError(f'More than one row matches "{who}": ' + ', '.join(f'{r["name"]} (@{r["github"] or "no GitHub"})' for r in hits)
                              + '. Use their GitHub login instead.')
        known = [r['name'] for r in self.rows] + [l for r in self.rows for l in logins(r)]
        close = difflib.get_close_matches(who.strip(), known, n=3, cutoff=0.5)
        raise NotFound(f'Nobody called "{who}" is on the leaderboard.' + (f' Did you mean {" or ".join(map(repr, close))}?' if close else '')
                          + ' To add someone new, use "add".')

    def by_login(self):
        """{lowercase login: row}, plus warnings for logins that appear on more than one row."""
        found, warnings = {}, []
        for r in self.rows:
            for l in logins(r):
                if l.lower() in found:
                    warnings.append(f'@{l} is on two rows ({found[l.lower()]["name"]}, {r["name"]}); only the first is updated. '
                                    f'Combine them with the merge action.')
                    continue
                found[l.lower()] = r
        return found, warnings


# ---------- history ----------

def load_history():
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def actor():
    if os.environ.get('GITHUB_ACTOR'):
        return os.environ['GITHUB_ACTOR']
    try:
        name = subprocess.run(['git', 'config', 'user.name'], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        name = ''
    return name or os.environ.get('USER', 'unknown')


def record(roster, description):
    """Write the change and log which cells it changed."""
    history = load_history()
    history.append({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'by': actor(),
                    'action': description, 'changes': roster.changes()})
    HISTORY.write_text(json.dumps(history[-HISTORY_LIMIT:], indent=2) + '\n')
    roster.save()
    return description


def locate(roster, row):
    """The current row that a logged row refers to: same GitHub login, or the same name if it has none."""
    accounts = {l.lower() for l in logins(row)}
    if accounts:
        hits = [r for r in roster.rows if accounts & {l.lower() for l in logins(r)}]
    else:
        hits = [r for r in roster.rows if r['name'].strip().lower() == row['name'].strip().lower()]
    return hits[0] if len(hits) == 1 else None


# ---------- facilitator actions (each returns a one-line summary) ----------

def add(name, github=''):
    roster = Roster()
    name, github = name.strip(), github.strip().lstrip('@')
    if not name:
        raise ActionError('Give the person a name.')
    for who in filter(None, [name, github]):
        try:
            existing = roster.find(who)
        except NotFound:
            continue
        raise ActionError(f'"{who}" is already on the leaderboard as {existing["name"]}.')
    roster.new_row(name, github)
    return record(roster, f'Added {name}' + (f' (@{github})' if github else ''))


def award(who, kind, amount=1):
    roster = Roster()
    if kind not in COUNTS:
        raise ActionError(f'Award one of: {", ".join(COUNTS)} (got "{kind}").')
    amount = to_int(amount)
    if amount == 0:
        raise ActionError('The amount must be a whole number other than 0.')
    row = roster.find(who)
    before = to_int(row.get(kind))
    if kind != 'bonus' and before + amount < 0:
        raise ActionError(f'{row["name"]} has {before} {kind}; cannot take away {-amount}.')
    row[kind] = str(before + amount)
    unit = {'stretch': 'stretch task', 'helped': 'help', 'bonus': 'bonus point'}[kind]
    return record(roster, f'{"Gave" if amount > 0 else "Took"} {abs(amount)} {unit}{"" if abs(amount) == 1 else "s"} '
                          f'{"to" if amount > 0 else "from"} {row["name"]} ({kind}: {before} -> {row[kind]})')


def mark(who, lesson, status):
    roster = Roster()
    keys = lesson_keys()
    if lesson not in keys:
        raise ActionError(f'Unknown exercise "{lesson}". Use one of: {", ".join(keys)}.')
    if status not in STATUSES:
        raise ActionError(f'Status must be one of: {", ".join(STATUSES)}.')
    row = roster.find(who)
    before = norm_status(row.get(lesson))
    row[lesson] = '' if status == 'none' else status
    note = ' The automatic grader never lowers a status, so a pull request can raise this again.' if RANK[status] < RANK[before] else ''
    return record(roster, f'Marked {row["name"]} {lesson} as {status} (was {before}).{note}')


def rename(who, new_name):
    roster = Roster()
    new_name = new_name.strip()
    if not new_name:
        raise ActionError('Give the new name.')
    row = roster.find(who)
    old = row['name']
    row['name'] = new_name
    return record(roster, f'Renamed {old} to {new_name}')


def merge(keep_who, drop_whos):
    """Fold other rows into one. Every value keeps the higher of the rows (best status per exercise, larger
    stretch, helped and bonus), so the merged row never has fewer points than any row it replaced."""
    roster = Roster()
    keep = roster.find(keep_who)
    drops = []
    for w in drop_whos:
        d = roster.find(w)
        if d is keep:
            raise ActionError(f'"{w}" is the row being kept; cannot merge a row into itself.')
        if any(d is x for x in drops):
            raise ActionError(f'"{w}" names a row already being merged.')
        drops.append(d)
    accounts = list(dict.fromkeys(logins(keep) + [l for d in drops for l in logins(d)]))
    keys = lesson_keys()
    for d in drops:
        for h in roster.head:
            if h in BASE_COLUMNS:
                continue
            if h in keys:
                if RANK[norm_status(d.get(h))] > RANK[norm_status(keep.get(h))]:
                    keep[h] = d[h]
            elif h in COUNTS:
                if to_int(d.get(h)) > to_int(keep.get(h)):
                    keep[h] = d[h]
            elif not keep.get(h):
                keep[h] = d.get(h, '')
        roster.rows.remove(d)
    keep['github'] = ' '.join(accounts)
    return record(roster, f'Merged {", ".join(d["name"] for d in drops)} into {keep["name"]}')


def undo(reapply):
    """Reverse the latest action: change back exactly the cells it changed, re-add rows it removed and remove
    rows it added. A cell someone has changed again since is left as it is and reported. `reapply` then
    re-adds automatic grading results, so anything the grader added since is kept."""
    history = load_history()
    if not history:
        raise ActionError('There is nothing to undo.')
    last = history.pop()
    roster = Roster()
    kept = []
    # Handle removals and edits before re-adding rows, so a re-added row is not mistaken for the edited one.
    for c in sorted(last['changes'], key=lambda c: c['before'] is not None and c['after'] is None):
        before, after = c['before'], c['after']
        if after is None:  # the action removed this row (a merge): put it back
            roster.rows.append(dict(before))
            continue
        current = locate(roster, after)
        if current is None:
            kept.append(f'{after["name"]} is no longer on the board')
            continue
        if before is None:  # the action added this row
            roster.rows.remove(current)
            continue
        for col, old in before.items():
            if after.get(col) == old:
                continue
            if current.get(col, '') == after.get(col, ''):
                current[col] = old
            else:
                kept.append(f'{current["name"]}\'s {col} was changed again since, so it stays {current.get(col) or "empty"}')
    roster.save()
    HISTORY.write_text(json.dumps(history, indent=2) + '\n')
    reapply()
    return f'Undid: {last["action"]} (by {last["by"]} at {last["at"]})' + ''.join(f'\nKept: {k}.' for k in kept)


def recent(n=10):
    history = load_history()[-n:]
    if not history:
        return 'No facilitator actions yet.'
    return '\n'.join(f'{h["at"]}  {h["by"]}: {h["action"]}' for h in reversed(history))
