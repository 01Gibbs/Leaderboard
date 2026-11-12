"""The roster: participants.csv and every change to it.

Two things change scores, and both go through Roster: facilitator actions (add, award, mark, rename, merge,
undo) and graded results (apply_results). The rules that protect people's points live here:
  - a graded result only ever raises a status, so it never overwrites a facilitator's change;
  - merging keeps the higher value of every column, so nobody loses points;
  - every facilitator action records the cells it changed, so undo can change exactly those back.
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

import lessons
from rules import BASE_COLUMNS, COUNTS, RANK, STATUSES, norm_header, norm_status, parse_csv, to_int

HISTORY_LIMIT = 100
BOM = '\ufeff'


class ActionError(Exception):
    """A change that cannot be made, with a message saying why. Nothing has been changed."""


class NotFound(ActionError):
    pass


def logins(row):
    """A row's `github` cell may list several accounts, separated by spaces (commas, ; and | also work)."""
    return [l.lstrip('@') for l in re.split(r'[\s,;|]+', row.get('github', '')) if l.lstrip('@')]


def actor():
    if os.environ.get('GITHUB_ACTOR'):
        return os.environ['GITHUB_ACTOR']
    try:
        name = subprocess.run(['git', 'config', 'user.name'], capture_output=True, text=True).stdout.strip()
    except OSError:
        name = ''
    return name or os.environ.get('USER', 'unknown')


class _Sheet:
    """participants.csv in memory, read exactly as the page reads it (rules.parse_csv). Writing it back keeps
    the delimiter, BOM and column order."""

    def __init__(self, path, lesson_keys):
        columns = BASE_COLUMNS + lesson_keys + COUNTS
        self.lesson_keys = lesson_keys
        raw = path.read_text(encoding='utf-8') if path.exists() else ''
        table, self.delim, self.bom = parse_csv(raw)
        self.path = path
        self.head = [norm_header(h) for h in table[0]] if table else []
        self.head += [c for c in columns if c not in self.head]
        self.rows = [{h: (r[i].strip() if i < len(r) else '') for i, h in enumerate(self.head)} for r in table[1:]]
        self.loaded = {id(r): dict(r) for r in self.rows}  # to work out which cells an action changed

    def save(self):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=self.delim, lineterminator='\n')
        w.writerow(self.head)
        for r in self.rows:
            w.writerow([r.get(h, '') for h in self.head])
        self.path.write_text((BOM if self.bom else '') + buf.getvalue(), encoding='utf-8')

    def changes(self):
        """[{before, after}] for every row added, removed or edited since loading (None for a missing side)."""
        out = [{'before': self.loaded.get(id(r)), 'after': dict(r)} for r in self.rows if self.loaded.get(id(r)) != r]
        kept = {id(r) for r in self.rows}
        return out + [{'before': before, 'after': None} for i, before in self.loaded.items() if i not in kept]

    def new_row(self, name, github=''):
        row = {h: '' for h in self.head} | {'name': name, 'github': github}
        self.rows.append(row)
        return row

    def find(self, who):
        """The one row whose GitHub login (with or without @) or name matches, ignoring case."""
        key = who.strip().lower()
        hits = [r for r in self.rows if key.lstrip('@') in (l.lower() for l in logins(r)) or r['name'].strip().lower() == key]
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

    def locate(self, row):
        """The current row that a logged row refers to: same GitHub login, or the same name if it has none."""
        accounts = {l.lower() for l in logins(row)}
        if accounts:
            hits = [r for r in self.rows if accounts & {l.lower() for l in logins(r)}]
        else:
            hits = [r for r in self.rows if r['name'].strip().lower() == row['name'].strip().lower()]
        return hits[0] if len(hits) == 1 else None


class Roster:
    """participants.csv of the leaderboard repository at `root`, with its lessons, history and graded results."""

    def __init__(self, root):
        root = Path(root)
        self.csv_file = root / 'participants.csv'
        self.lessons_file = root / 'lessons.json'
        self.history_file = root / 'grader' / 'history.json'
        self.results_file = root / 'grader' / 'results.json'

    # ---------- reading ----------

    def lesson_keys(self):
        try:
            return [l.key for l in lessons.load(self.lessons_file)]
        except lessons.LessonsInvalid as e:
            raise ActionError(str(e)) from None

    def _sheet(self):
        return _Sheet(self.csv_file, self.lesson_keys())

    def columns(self):
        return list(self._sheet().head)

    def rows(self):
        return [dict(r) for r in self._sheet().rows]

    def find(self, who):
        return dict(self._sheet().find(who))

    def history(self):
        return json.loads(self.history_file.read_text()) if self.history_file.exists() else []

    def recent(self, n=10):
        history = self.history()[-n:]
        if not history:
            return 'No facilitator actions yet.'
        return '\n'.join(f'{h["at"]}  {h["by"]}: {h["action"]}' for h in reversed(history))

    # ---------- facilitator actions (each returns a one-line summary) ----------

    def _record(self, sheet, description):
        """Write the change and log which cells it changed."""
        history = self.history()
        history.append({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'by': actor(),
                        'action': description, 'changes': sheet.changes()})
        self.history_file.write_text(json.dumps(history[-HISTORY_LIMIT:], indent=2) + '\n')
        sheet.save()
        return description

    def add(self, name, github=''):
        sheet = self._sheet()
        name, github = name.strip(), github.strip().lstrip('@')
        if not name:
            raise ActionError('Give the person a name.')
        for who in filter(None, [name, github]):
            try:
                existing = sheet.find(who)
            except NotFound:
                continue
            raise ActionError(f'"{who}" is already on the leaderboard as {existing["name"]}.')
        sheet.new_row(name, github)
        return self._record(sheet, f'Added {name}' + (f' (@{github})' if github else ''))

    def award(self, who, kind, amount=1):
        if kind not in COUNTS:
            raise ActionError(f'Award one of: {", ".join(COUNTS)} (got "{kind}").')
        amount = to_int(amount)
        if amount == 0:
            raise ActionError('The amount must be a whole number other than 0.')
        sheet = self._sheet()
        row = sheet.find(who)
        before = to_int(row.get(kind))
        if kind != 'bonus' and before + amount < 0:
            raise ActionError(f'{row["name"]} has {before} {kind}; cannot take away {-amount}.')
        row[kind] = str(before + amount)
        unit = {'stretch': 'stretch task', 'helped': 'help', 'bonus': 'bonus point'}[kind]
        return self._record(sheet, f'{"Gave" if amount > 0 else "Took"} {abs(amount)} {unit}{"" if abs(amount) == 1 else "s"} '
                                   f'{"to" if amount > 0 else "from"} {row["name"]} ({kind}: {before} -> {row[kind]})')

    def mark(self, who, lesson, status):
        sheet = self._sheet()
        if lesson not in sheet.lesson_keys:
            raise ActionError(f'Unknown exercise "{lesson}". Use one of: {", ".join(sheet.lesson_keys)}.')
        if status not in STATUSES:
            raise ActionError(f'Status must be one of: {", ".join(STATUSES)}.')
        row = sheet.find(who)
        before = norm_status(row.get(lesson))
        row[lesson] = '' if status == 'none' else status
        note = ' The automatic grader never lowers a status, so a pull request can raise this again.' if RANK[status] < RANK[before] else ''
        return self._record(sheet, f'Marked {row["name"]} {lesson} as {status} (was {before}).{note}')

    def rename(self, who, new_name):
        new_name = new_name.strip()
        if not new_name:
            raise ActionError('Give the new name.')
        sheet = self._sheet()
        row = sheet.find(who)
        old, row['name'] = row['name'], new_name
        return self._record(sheet, f'Renamed {old} to {new_name}')

    def merge(self, keep_who, drop_whos):
        """Fold other rows into one. Every value keeps the higher of the rows (best status per exercise, larger
        stretch, helped and bonus), so the merged row never has fewer points than any row it replaced."""
        sheet = self._sheet()
        keep, drops = sheet.find(keep_who), []
        for w in drop_whos:
            d = sheet.find(w)
            if d is keep:
                raise ActionError(f'"{w}" is the row being kept; cannot merge a row into itself.')
            if any(d is x for x in drops):
                raise ActionError(f'"{w}" names a row already being merged.')
            drops.append(d)
        accounts = list(dict.fromkeys(logins(keep) + [l for d in drops for l in logins(d)]))
        keys = sheet.lesson_keys
        for d in drops:
            for h in sheet.head:
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
            sheet.rows.remove(d)
        keep['github'] = ' '.join(accounts)
        return self._record(sheet, f'Merged {", ".join(d["name"] for d in drops)} into {keep["name"]}')

    def undo(self):
        """Reverse the latest action: change back exactly the cells it changed, re-add rows it removed and remove
        rows it added. A cell someone has changed again since is left as it is and reported. Graded results
        are then applied again, so anything the grader added since is kept."""
        history = self.history()
        if not history:
            raise ActionError('There is nothing to undo.')
        last = history.pop()
        sheet = self._sheet()
        kept = []
        # Handle removals and edits before re-adding rows, so a re-added row is not mistaken for the edited one.
        for c in sorted(last['changes'], key=lambda c: c['before'] is not None and c['after'] is None):
            before, after = c['before'], c['after']
            if after is None:  # the action removed this row (a merge): put it back
                sheet.rows.append(dict(before))
                continue
            current = sheet.locate(after)
            if current is None:
                kept.append(f'{after["name"]} is no longer on the board')
                continue
            if before is None:  # the action added this row
                sheet.rows.remove(current)
                continue
            for col, old in before.items():
                if after.get(col) == old:
                    continue
                if current.get(col, '') == after.get(col, ''):
                    current[col] = old
                else:
                    kept.append(f'{current["name"]}\'s {col} was changed again since, so it stays {current.get(col) or "empty"}')
        sheet.save()
        self.history_file.write_text(json.dumps(history, indent=2) + '\n')
        self.apply_results()
        return f'Undid: {last["action"]} (by {last["by"]} at {last["at"]})' + ''.join(f'\nKept: {k}.' for k in kept)

    # ---------- graded results ----------

    def apply_results(self):
        """Raise each person's exercise status to the best result of their pull requests (grader/results.json),
        adding a row for anyone new. Never lowers a status. Returns (changes, warnings) as lines of text."""
        results = json.loads(self.results_file.read_text()) if self.results_file.exists() else {}
        subs, people = results.get('submissions', {}), results.get('people', {})
        sheet = self._sheet()
        by_login, warnings = sheet.by_login()
        keys = set(sheet.lesson_keys)

        best, spelling = {}, {}  # (login, lesson) -> status; lowercase login -> login as GitHub spells it
        for s in subs.values():
            if s['task'] not in keys:  # a lesson removed from lessons.json
                continue
            status = 'correct' if s.get('passed') else 'submitted'
            k = (s['login'].lower(), s['task'])
            spelling[k[0]] = s['login']
            if RANK[status] > RANK.get(best.get(k), -1):
                best[k] = status

        changes = []
        for (login, lesson), status in sorted(best.items()):
            row = by_login.get(login)
            if row is None:
                gh = spelling[login]
                row = by_login[login] = sheet.new_row(people.get(gh) or gh, gh)
                changes.append(f'Added {row["name"]} (@{gh})')
            if RANK[status] > RANK[norm_status(row.get(lesson))]:
                changes.append(f'{row["name"]}: {lesson} -> {status}')
                row[lesson] = status
        sheet.save()
        return changes, warnings
