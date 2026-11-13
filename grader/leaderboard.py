"""Leaderboard commands. Facilitators normally run these from the Actions tab on GitHub (see FACILITATOR.md);
this is the same thing from a terminal. A person is named by their GitHub login or their name.

  add      "Name" [github-login]          put someone on the board who has not opened a pull request
  award    <person> stretch|helped|bonus [amount]   add points (a negative amount takes them away)
  mark     <person> <lesson> correct|submitted|none  set an exercise result by hand
  rename   <person> "New name"            show a real name instead of a GitHub login
  merge    <keep> <duplicate> [...]       combine rows for one person, keeping the higher value of each column
  undo                                    reverse the latest of the actions above
  history  [count]                        list recent actions
  grade    [--no-run] [--only owner/repo#N]   grade new pull requests (normally run by GitHub Actions)
  apply                                   write graded results into participants.csv
  pin-tests <lesson> [commit]             grade a lesson with its exercise repository's own tests, as they are at
                                          that full commit id (default: the latest), copied into grader/fixtures/<lesson>/
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exercise_tests  # noqa: E402
import grade  # noqa: E402
import roster  # noqa: E402
from rules import COUNTS, STATUSES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def parser():
    p = argparse.ArgumentParser(prog='leaderboard', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True, metavar='command')
    c = sub.add_parser('add', help='add a person')
    c.add_argument('name')
    c.add_argument('github', nargs='?', default='')
    c = sub.add_parser('award', help='add stretch, helped or bonus points')
    c.add_argument('person')
    c.add_argument('kind', choices=COUNTS)
    c.add_argument('amount', nargs='?', default='1')
    c = sub.add_parser('mark', help='set an exercise result by hand')
    c.add_argument('person')
    c.add_argument('lesson')
    c.add_argument('status', choices=STATUSES)
    c = sub.add_parser('rename', help='change the name shown')
    c.add_argument('person')
    c.add_argument('new_name')
    c = sub.add_parser('merge', help='combine duplicate rows')
    c.add_argument('keep')
    c.add_argument('duplicates', nargs='+')
    sub.add_parser('undo', help='reverse the latest action')
    c = sub.add_parser('history', help='list recent actions')
    c.add_argument('count', nargs='?', type=int, default=10)
    c = sub.add_parser('grade', help='grade new pull requests')
    c.add_argument('--no-run', action='store_true', help='record submissions without running checks')
    c.add_argument('--only', help='grade one pull request, e.g. AtulKumarSharma79/Frameworkupgrade#3')
    sub.add_parser('apply', help='write graded results into participants.csv')
    c = sub.add_parser('pin-tests', help="grade a lesson with its exercise repository's own tests")
    c.add_argument('lesson')
    c.add_argument('commit', nargs='?')
    return p


def run(argv, root):
    a = parser().parse_args(argv)
    board = roster.Roster(root)
    if a.cmd == 'add':
        return board.add(a.name, a.github)
    if a.cmd == 'award':
        return board.award(a.person, a.kind, a.amount)
    if a.cmd == 'mark':
        return board.mark(a.person, a.lesson, a.status)
    if a.cmd == 'rename':
        return board.rename(a.person, a.new_name)
    if a.cmd == 'merge':
        return board.merge(a.keep, a.duplicates)
    if a.cmd == 'undo':
        return board.undo()
    if a.cmd == 'history':
        return board.recent(a.count)
    if a.cmd == 'pin-tests':
        lessons_file, fixtures = root / 'lessons.json', root / 'grader' / 'fixtures'
        sha = exercise_tests.pin(lessons_file, fixtures, a.lesson, a.commit)
        count = sum(1 for f in (fixtures / a.lesson).rglob('*') if f.is_file())
        return f'{a.lesson} is graded with its repository\'s {count} test files as of {sha[:7]}'
    if a.cmd == 'grade':
        grade.grade_all(root, no_run=a.no_run, only=a.only)
        return None
    changes, warnings = board.apply_results()
    print('\n'.join([f'Warning: {w}' for w in warnings] + changes) or 'No changes')
    return None


def main(argv, root=ROOT):
    # Workflows pass their form inputs as one JSON array, so no input is ever read by a shell.
    if argv[:1] == ['--args-json']:
        argv = [str(v) for v in json.loads(argv[1])]
    try:
        summary = run(argv, Path(root))
    except (roster.ActionError, exercise_tests.PinFailed) as e:
        report(f'Nothing was changed. {e}', failed=True)
        return 1
    if summary and argv[:1] == ['history']:
        print(summary)  # a listing, not a change: keep it off the run page's ✅ line
    elif summary:
        report(summary)
    return 0


def report(text, failed=False):
    print(text, file=sys.stderr if failed else sys.stdout)
    if os.environ.get('GITHUB_STEP_SUMMARY'):  # shows on the workflow run page
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(('### ❌ ' if failed else '### ✅ ') + text.splitlines()[0] + '\n\n' + '\n'.join(text.splitlines()[1:]) + '\n')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
