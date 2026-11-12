"""The roster: facilitator actions, undo, and applying graded results, driven through the command line.

Run: python3 -m unittest discover grader/tests
Each test points the command line at its own scratch copy of the repository (participants.csv, lessons.json,
grader/results.json, grader/history.json), never the real one.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

GRADER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GRADER))
import leaderboard  # noqa: E402
import roster  # noqa: E402
import rules  # noqa: E402

LESSONS = [
    {'key': 'fizzbuzz', 'label': 'FizzBuzz', 'repo': 'o/fizz', 'check': 'fizzbuzz'},
    {'key': 'rest_api', 'label': 'REST API', 'repo': 'o/rest', 'check': 'rest_api'},
    {'key': 'manual', 'label': 'Manual', 'repo': 'o/manual', 'check': 'none'},
]
CSV = '''name,github,fizzbuzz,rest_api,manual,stretch,helped,bonus
Stuart Smith,StuartJSmith10-dev,correct,,,1,,
Bukky Adeyemi,,,,,2,1,
bukkie-create,bukkie-create,submitted,submitted,,,3,
'''


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / 'grader').mkdir()
        (self.dir / 'lessons.json').write_text(json.dumps(LESSONS))
        (self.dir / 'participants.csv').write_text(CSV)

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def cli(self, *argv):
        """Run a command the way a terminal or workflow does. Returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = leaderboard.main(list(argv), root=self.dir)
        return code, out.getvalue(), err.getvalue()

    def csv_text(self):
        return (self.dir / 'participants.csv').read_text()

    def roster(self):
        return roster.Roster(self.dir)

    def row(self, who):
        return self.roster().find(who)

    def results(self, *subs):
        people = {s[0]: s[3] if len(s) > 3 else s[0] for s in subs}
        data = {'people': people, 'submissions': {
            f'o/x#{i}': {'login': s[0], 'task': s[1], 'passed': s[2]} for i, s in enumerate(subs)}}
        (self.dir / 'grader' / 'results.json').write_text(json.dumps(data))


class AwardTests(Sandbox):
    def test_award_adds_to_existing_count(self):
        code, out, _ = self.cli('award', 'Stuart Smith', 'stretch', '2')
        self.assertEqual(code, 0)
        self.assertEqual(self.row('Stuart Smith')['stretch'], '3')
        self.assertIn('Gave 2 stretch tasks to Stuart Smith (stretch: 1 -> 3)', out)

    def test_award_defaults_to_one_and_matches_login_case_insensitively(self):
        self.cli('award', '@stuartjsmith10-DEV', 'helped')
        self.assertEqual(self.row('Stuart Smith')['helped'], '1')

    def test_bonus_points_can_go_negative(self):
        self.cli('award', 'Stuart Smith', 'bonus', '5')
        self.cli('award', 'Stuart Smith', 'bonus', '-8')
        self.assertEqual(self.row('Stuart Smith')['bonus'], '-3')

    def test_counts_cannot_go_below_zero(self):
        code, _, err = self.cli('award', 'Stuart Smith', 'stretch', '-2')
        self.assertEqual(code, 1)
        self.assertIn('cannot take away 2', err)
        self.assertEqual(self.csv_text(), CSV)

    def test_zero_or_text_amount_is_rejected(self):
        for amount in ('0', 'lots'):
            code, _, err = self.cli('award', 'Stuart Smith', 'bonus', amount)
            self.assertEqual(code, 1)
            self.assertIn('whole number', err)
        self.assertEqual(self.csv_text(), CSV)

    def test_unknown_person_suggests_close_names_and_changes_nothing(self):
        code, _, err = self.cli('award', 'Stuart Smit', 'helped')
        self.assertEqual(code, 1)
        self.assertIn("Did you mean 'Stuart Smith'", err)
        self.assertEqual(self.csv_text(), CSV)
        self.assertEqual(self.roster().history(), [])


class MarkRenameAddTests(Sandbox):
    def test_mark_sets_status(self):
        code, out, _ = self.cli('mark', 'Stuart Smith', 'manual', 'correct')
        self.assertEqual(code, 0)
        self.assertEqual(self.row('Stuart Smith')['manual'], 'correct')

    def test_mark_lower_warns_grader_may_raise_again(self):
        _, out, _ = self.cli('mark', 'Stuart Smith', 'fizzbuzz', 'none')
        self.assertEqual(self.row('Stuart Smith')['fizzbuzz'], '')
        self.assertIn('never lowers', out)

    def test_mark_unknown_lesson_lists_valid_ones(self):
        code, _, err = self.cli('mark', 'Stuart Smith', 'docker', 'correct')
        self.assertEqual(code, 1)
        self.assertIn('fizzbuzz, rest_api, manual', err)

    def test_rename_keeps_github_so_grader_still_matches(self):
        self.cli('rename', 'bukkie-create', 'Bukola A')
        self.assertEqual(self.row('bukkie-create')['name'], 'Bukola A')

    def test_add_person_and_reject_duplicates(self):
        self.assertEqual(self.cli('add', 'New Person', '@newbie')[0], 0)
        self.assertEqual(self.row('newbie')['name'], 'New Person')
        code, _, err = self.cli('add', 'Someone Else', 'NEWBIE')
        self.assertEqual(code, 1)
        self.assertIn('already on the leaderboard as New Person', err)

    def test_add_refuses_a_name_already_on_the_board(self):
        code, _, err = self.cli('add', 'stuart smith', 'other-stuart')
        self.assertEqual(code, 1)
        self.assertIn('already on the leaderboard', err)

    def test_add_refuses_a_name_that_is_already_ambiguous(self):
        self.results(('other-stuart', 'rest_api', False, 'Stuart Smith'))
        self.cli('apply')
        code, _, err = self.cli('add', 'Stuart Smith')
        self.assertEqual(code, 1)
        self.assertIn('More than one row matches', err)
        self.assertEqual(sum(r['name'] == 'Stuart Smith' for r in self.roster().rows()), 2)

    def test_ambiguous_name_asks_for_login(self):
        # Two people can share a name when the grader adds someone whose GitHub profile name matches.
        self.results(('other-stuart', 'rest_api', False, 'Stuart Smith'))
        self.cli('apply')
        code, _, err = self.cli('award', 'Stuart Smith', 'helped')
        self.assertEqual(code, 1)
        self.assertIn('More than one row matches', err)
        self.assertEqual(self.cli('award', 'other-stuart', 'helped')[0], 0)


class MergeTests(Sandbox):
    def test_merge_keeps_the_higher_value_of_every_column(self):
        code, out, _ = self.cli('merge', 'Bukky Adeyemi', 'bukkie-create')
        self.assertEqual(code, 0)
        r = self.roster()
        self.assertEqual(len(r.rows()), 2)
        row = r.find('Bukky Adeyemi')
        self.assertEqual((row['github'], row['fizzbuzz'], row['rest_api'], row['stretch'], row['helped']),
                         ('bukkie-create', 'submitted', 'submitted', '2', '3'))

    def test_merged_row_is_not_recreated_by_the_grader(self):
        self.results(('bukkie-create', 'fizzbuzz', True))
        self.cli('merge', 'Bukky Adeyemi', 'bukkie-create')
        self.cli('apply')
        rows = self.roster().rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.roster().find('Bukky Adeyemi')['fizzbuzz'], 'correct')

    def test_merged_person_never_has_fewer_points_than_either_row(self):
        keys = [l['key'] for l in LESSONS]
        points = lambda: {r['name']: rules.points(r, keys) for r in rules.read_participants(self.csv_text(), keys)['rows']}
        before = points()
        self.cli('merge', 'Bukky Adeyemi', 'bukkie-create')
        after = points()['Bukky Adeyemi']
        self.assertGreaterEqual(after, max(before['Bukky Adeyemi'], before['bukkie-create']))
        self.assertEqual(after, 10 + 10 + 2 * 5 + 3 * 5)  # submitted twice, 2 stretch, 3 helps

    def test_two_github_accounts_on_one_row_both_count(self):
        self.cli('add', 'Alt', 'second-account')
        self.cli('merge', 'Bukky Adeyemi', 'bukkie-create', 'second-account')
        self.assertEqual(self.row('second-account')['github'], 'bukkie-create second-account')
        self.results(('second-account', 'rest_api', True))
        self.cli('apply')
        self.assertEqual(self.row('Bukky Adeyemi')['rest_api'], 'correct')

    def test_same_duplicate_named_twice_is_refused_cleanly(self):
        code, _, err = self.cli('merge', 'Stuart Smith', 'bukkie-create', '@BUKKIE-CREATE')
        self.assertEqual(code, 1)
        self.assertIn('already being merged', err)

    def test_cannot_merge_into_itself(self):
        code, _, err = self.cli('merge', 'bukkie-create', 'bukkie-create')
        self.assertEqual(code, 1)
        self.assertIn('into itself', err)


class UndoTests(Sandbox):
    def test_undo_reverses_actions_one_at_a_time(self):
        self.cli('award', 'Stuart Smith', 'helped', '2')
        after_first = self.csv_text()
        self.cli('merge', 'Bukky Adeyemi', 'bukkie-create')
        code, out, _ = self.cli('undo')
        self.assertEqual(code, 0)
        self.assertIn('Undid: Merged bukkie-create into Bukky Adeyemi', out)
        self.assertEqual(self.csv_text(), after_first)
        self.cli('undo')
        self.assertEqual(self.csv_text(), CSV)
        code, _, err = self.cli('undo')
        self.assertEqual(code, 1)
        self.assertIn('nothing to undo', err)

    def test_undo_keeps_grader_results_that_arrived_after_the_action(self):
        self.cli('rename', 'Stuart Smith', 'Stu')
        self.results(('newcomer', 'rest_api', True, 'New Comer'))
        self.cli('apply')
        self.cli('undo')
        r = self.roster()
        self.assertEqual(r.find('Stuart Smith')['name'], 'Stuart Smith')
        self.assertEqual(r.find('newcomer')['rest_api'], 'correct')

    def test_undo_keeps_edits_made_directly_to_the_csv_since(self):
        self.cli('award', 'Stuart Smith', 'helped', '2')
        edited = self.csv_text().replace('Bukky Adeyemi,,,,,2,1,', 'Bukky Adeyemi,,,,,5,1,')  # the lead edits the file on GitHub
        (self.dir / 'participants.csv').write_text(edited)
        self.cli('undo')
        self.assertEqual(self.row('Stuart Smith')['helped'], '')
        self.assertEqual(self.row('Bukky Adeyemi')['stretch'], '5')

    def test_undo_leaves_a_cell_changed_again_since_and_says_so(self):
        self.cli('award', 'Stuart Smith', 'helped', '2')
        (self.dir / 'participants.csv').write_text(self.csv_text().replace('correct,,,1,2,', 'correct,,,1,4,'))
        code, out, _ = self.cli('undo')
        self.assertEqual(code, 0)
        self.assertEqual(self.row('Stuart Smith')['helped'], '4')
        self.assertIn("Kept: Stuart Smith's helped was changed again since, so it stays 4", out)

    def test_undo_merge_restores_both_rows_exactly(self):
        self.cli('merge', 'Bukky Adeyemi', 'bukkie-create')
        self.cli('undo')
        self.assertEqual(self.csv_text().splitlines()[1:], CSV.splitlines()[1:])

    def test_undo_add_removes_the_person_again(self):
        self.cli('add', 'New Person')
        self.cli('award', 'New Person', 'helped')
        self.cli('undo')
        self.cli('undo')
        self.assertEqual(self.csv_text(), CSV)

    def test_undo_rename_of_someone_without_github(self):
        self.cli('rename', 'Bukky Adeyemi', 'Bukola Adeyemi')
        self.cli('undo')
        self.assertEqual(self.row('Bukky Adeyemi')['stretch'], '2')

    def test_history_lists_newest_first_with_who(self):
        self.patch(roster, 'actor', lambda: 'facilitator-1')
        self.cli('award', 'Stuart Smith', 'helped')
        self.cli('rename', 'Stuart Smith', 'Stu')
        _, out, _ = self.cli('history')
        lines = out.strip().splitlines()
        self.assertIn('facilitator-1: Renamed Stuart Smith to Stu', lines[0])
        self.assertIn('Gave 1 help to Stuart Smith', lines[1])

    def test_history_is_capped(self):
        self.patch(roster, 'HISTORY_LIMIT', 3)
        for _ in range(5):
            self.cli('award', 'Stuart Smith', 'bonus')
        self.assertEqual(len(self.roster().history()), 3)


class ApplyTests(Sandbox):
    def test_new_github_account_gets_a_row_named_from_profile(self):
        self.results(('newbie', 'rest_api', False, 'Newbie Person'))
        self.cli('apply')
        row = self.row('newbie')
        self.assertEqual((row['name'], row['rest_api']), ('Newbie Person', 'submitted'))

    def test_never_lowers_a_status(self):
        self.results(('StuartJSmith10-dev', 'fizzbuzz', False))
        self.cli('apply')
        self.assertEqual(self.row('Stuart Smith')['fizzbuzz'], 'correct')

    def test_best_result_across_several_pull_requests_wins(self):
        self.results(('bukkie-create', 'rest_api', False), ('bukkie-create', 'rest_api', True))
        self.cli('apply')
        self.assertEqual(self.row('bukkie-create')['rest_api'], 'correct')

    def test_ungraded_and_manual_lessons_count_as_submitted(self):
        self.results(('StuartJSmith10-dev', 'manual', None))
        self.cli('apply')
        self.assertEqual(self.row('Stuart Smith')['manual'], 'submitted')

    def test_results_for_a_removed_lesson_are_ignored(self):
        self.results(('StuartJSmith10-dev', 'old_lesson', True))
        self.cli('apply')
        self.assertNotIn('old_lesson', self.roster().columns())

    def test_duplicate_login_warns_and_points_at_merge(self):
        self.cli('add', 'Copy', 'other')
        (self.dir / 'participants.csv').write_text(self.csv_text().replace(',other,', ',bukkie-create,'))
        self.results(('bukkie-create', 'fizzbuzz', True))
        _, out, _ = self.cli('apply')
        self.assertIn('on two rows', out)
        self.assertIn('merge', out)

    def test_new_lesson_column_is_added(self):
        (self.dir / 'lessons.json').write_text(json.dumps(LESSONS + [{'key': 'docker', 'label': 'Docker', 'repo': 'o/d', 'check': 'none'}]))
        self.cli('apply')
        self.assertIn('docker', self.roster().columns())


class FileFormatTests(Sandbox):
    def test_semicolon_and_bom_from_excel_survive_a_change(self):
        (self.dir / 'participants.csv').write_text('﻿' + CSV.replace(',', ';'), encoding='utf-8')
        self.cli('award', 'Stuart Smith', 'helped')
        text = (self.dir / 'participants.csv').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('﻿'))
        self.assertIn('Stuart Smith;StuartJSmith10-dev;correct', text)

    def test_names_with_commas_and_quotes_round_trip(self):
        self.cli('add', 'Rao, Asha "AR"')
        self.assertEqual(self.row('Rao, Asha "AR"')['name'], 'Rao, Asha "AR"')

    def test_messy_whitespace_from_hand_edits_is_read(self):
        (self.dir / 'participants.csv').write_text('name,github,fizzbuzz\nStuart Smith,\tStuartJSmith10-dev ,\t correct\n')
        self.assertEqual(self.row('stuartjsmith10-dev')['fizzbuzz'], 'correct')


class WorkflowInputTests(Sandbox):
    """The facilitator workflows send form inputs as a JSON array (see .github/workflows/facilitator-*.yml)."""

    def test_json_args_with_shell_characters_are_plain_text(self):
        args = json.dumps(['rename', 'Stuart Smith', 'Stu "$(rm -rf /)" O\'Neil; `x`'])
        code, out, _ = self.cli('--args-json', args)
        self.assertEqual(code, 0)
        self.assertEqual(self.row('StuartJSmith10-dev')['name'], 'Stu "$(rm -rf /)" O\'Neil; `x`')

    def test_failure_is_shown_on_the_run_page(self):
        summary = self.dir / 'summary.md'
        self.patch(leaderboard.os, 'environ', {'GITHUB_STEP_SUMMARY': str(summary)})
        code, _, _ = self.cli('--args-json', json.dumps(['award', 'Nobody', 'helped', '1']))
        self.assertEqual(code, 1)
        self.assertIn('❌ Nothing was changed', summary.read_text())

    def test_every_facilitator_workflow_matches_a_command(self):
        workflows = GRADER.parent / '.github' / 'workflows'
        commands = set(leaderboard.parser()._subparsers._group_actions[0].choices)
        for wf in workflows.glob('facilitator-*.yml'):
            if wf.name == 'facilitator-action.yml':
                continue
            first = wf.read_text().split("args: '[\"", 1)[1].split('"', 1)[0]
            self.assertIn(first, commands, wf.name)


class BrokenLessonsTests(Sandbox):
    def test_a_broken_lessons_file_stops_actions_with_the_reason(self):
        (self.dir / 'lessons.json').write_text(json.dumps(LESSONS + [{'key': 'Bad Key', 'label': 'x', 'repo': 'o/r'}]))
        code, _, err = self.cli('award', 'Stuart Smith', 'helped')
        self.assertEqual(code, 1)
        self.assertIn('Nothing was changed', err)
        self.assertIn('must be lowercase', err)
        self.assertEqual(self.csv_text(), CSV)


if __name__ == '__main__':
    unittest.main()
