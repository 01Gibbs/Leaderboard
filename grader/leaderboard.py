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
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade  # noqa: E402
import roster  # noqa: E402


def parser():
    p = argparse.ArgumentParser(prog='leaderboard', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True, metavar='command')
    c = sub.add_parser('add', help='add a person')
    c.add_argument('name')
    c.add_argument('github', nargs='?', default='')
    c = sub.add_parser('award', help='add stretch, helped or bonus points')
    c.add_argument('person')
    c.add_argument('kind', choices=roster.COUNTS)
    c.add_argument('amount', nargs='?', default='1')
    c = sub.add_parser('mark', help='set an exercise result by hand')
    c.add_argument('person')
    c.add_argument('lesson')
    c.add_argument('status', choices=roster.STATUSES)
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
    return p


def run(argv):
    a = parser().parse_args(argv)
    if a.cmd == 'add':
        return roster.add(a.name, a.github)
    if a.cmd == 'award':
        return roster.award(a.person, a.kind, a.amount)
    if a.cmd == 'mark':
        return roster.mark(a.person, a.lesson, a.status)
    if a.cmd == 'rename':
        return roster.rename(a.person, a.new_name)
    if a.cmd == 'merge':
        return roster.merge(a.keep, a.duplicates)
    if a.cmd == 'undo':
        return roster.undo(lambda: grade.apply(quiet=True))
    if a.cmd == 'history':
        return roster.recent(a.count)
    if a.cmd == 'grade':
        grade.grade(a.no_run, a.only)
        return None
    grade.apply()
    return None


def main(argv):
    # Workflows pass their form inputs as one JSON array, so no input is ever read by a shell.
    if argv[:1] == ['--args-json']:
        argv = [str(v) for v in json.loads(argv[1])]
    try:
        summary = run(argv)
    except roster.ActionError as e:
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
