"""One copy of the leaderboard's rules: the page (scoring.js) and the grader (grader/rules.py) must agree.

Run: python3 -m unittest discover grader/tests
The parity tests run the page's own scoring.js in Node.js; they skip when Node is not installed.
"""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

GRADER = Path(__file__).resolve().parents[1]
ROOT = GRADER.parent
sys.path.insert(0, str(GRADER))
import rules  # noqa: E402

TRACKS = ['fizzbuzz', 'rest_api', 'framework_upgrade']

# Each case is a participants.csv someone could plausibly produce, by hand, in Excel, or by the grader.
CASES = {
    'plain': 'name,github_username,fizzbuzz,rest_api,framework_upgrade,stretch,pr_stretch,helped,bonus\n'
             'Ann,ann,correct,submitted,,1,2,2,3\nBob,,submitted,,,,,,\n',
    'pr1_live_format': 'name,github_username,fizzbuzz,rest_api,framework_upgrade,stretch,pr_stretch,helped\n'
                       'j-r-wil,j-r-wil,Correct,Correct,Correct,1,2,\naindroid,aindroid,none,Correct,Correct,2,1,1,\n',
    'excel_semicolons_bom_crlf': '﻿name;github;fizzbuzz;rest_api;framework_upgrade;stretch;helped;bonus\r\n'
                                 'Ann;ann;Yes;in review;;2;;-4\r\n',
    'tabs_and_messy_headers': ' Name \tGitHub\tFizzBuzz\tREST-API\tFramework  Upgrade\tStretch\tHelped\tBonus\n'
                              'Ann\tann\t PASS \tattempted\tdone\t 1 \t\t\n',
    'quotes_commas_and_blank_rows': 'name,github,fizzbuzz,rest_api,framework_upgrade,stretch,helped,bonus\n'
                                    '"Rao, Asha ""AR""",asha,correct,,,,,\n,,,,,,,\n   ,x,correct,,,,,\n',
    'odd_values': 'name,github,fizzbuzz,rest_api,framework_upgrade,stretch,helped,bonus\n'
                  'Ann,ann,maybe,CORRECT,y,-3,abc,7.5\n',
    'missing_and_extra_columns': 'name,fizzbuzz,notes,stretch\nAnn,correct,"likes, commas",2\nBob\n',
    'stray_quotes_and_no_final_newline': 'name,github,fizzbuzz\nAnn "the" Smith,ann,correct\nBo,bo,"submitted',
}

NODE_HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const { cases, tracks } = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {};
for (const [name, text] of Object.entries(cases)) {
  const people = vm.runInContext('readParticipants', ctx)(text, tracks.map((k) => ({ k })));
  out[name] = { skipped: people.skipped, people: people.rows.map((p) => ({ ...p, points: vm.runInContext('pointsOf', ctx)(p, tracks.map((k) => ({ k }))) })) };
}
process.stdout.write(JSON.stringify(out));
'''


def page_results():
    r = subprocess.run(['node', '-e', NODE_HARNESS, str(ROOT / 'scoring.js')],
                       input=json.dumps({'cases': CASES, 'tracks': TRACKS}), capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError('scoring.js failed in Node:\n' + r.stderr)
    return json.loads(r.stdout)


def grader_results():
    out = {}
    for name, text in CASES.items():
        people = rules.read_participants(text, TRACKS)
        out[name] = {'skipped': people['skipped'],
                     'people': [{**p, 'points': rules.points(p, TRACKS)} for p in people['rows']]}
    return out


RANK_HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const tracks = [{ k: 'a' }, { k: 'b' }];
const read = vm.runInContext('readParticipants', ctx)(fs.readFileSync(0, 'utf8'), tracks);
const ranked = vm.runInContext('rankParticipants', ctx)(read.rows, tracks);
process.stdout.write(JSON.stringify(ranked.map((r) => [r.rank, r.p.name, r.pts])));
'''


class RulesTests(unittest.TestCase):
    def test_the_rules_are_read_from_the_page(self):
        self.assertEqual(rules.RULES['points']['correct'], 30)
        self.assertEqual(rules.RULES['counts'], ['stretch', 'helped', 'bonus'])

    def test_worked_example(self):
        people = rules.read_participants(CASES['plain'], TRACKS)
        ann = people['rows'][0]
        self.assertEqual(ann['tracks'], {'fizzbuzz': 'correct', 'rest_api': 'submitted', 'framework_upgrade': 'none'})
        self.assertEqual(rules.points(ann, TRACKS), 30 + 10 + (1 + 2) * 5 + 2 * 5 + 3)  # stretch + early-PR bonus, 68

    def test_old_and_pr1_header_spellings(self):
        for header in ('github', 'GitHub Username', 'github_username'):
            self.assertEqual(rules.norm_header(header), 'github_username', header)
        self.assertEqual(rules.norm_header('PR Stretch'), 'pr_stretch')

    def test_status_words(self):
        for word, status in [('Yes', 'correct'), (' PASS ', 'correct'), ('in review', 'submitted'), ('maybe', 'none'), ('', 'none')]:
            self.assertEqual(rules.norm_status(word), status, word)

    def test_the_page_does_not_hard_code_the_rules(self):
        page = (ROOT / 'index.html').read_text()
        self.assertTrue('<script src="scoring.js"></script>' in page, 'index.html must load scoring.js')
        for duplicate in ("'passed'", 'in review', 'submitted: 10', '<b>30</b>', 'function parseCSV', 'function normStatus'):
            self.assertFalse(duplicate in page, f'index.html repeats a rule that belongs in scoring.js: {duplicate}')


@unittest.skipUnless(shutil.which('node'), 'needs Node.js to run the page\'s scoring.js')
class ParityTests(unittest.TestCase):
    """The same file read by the page and by the grader gives the same people, results and points."""

    @classmethod
    def setUpClass(cls):
        cls.page, cls.grader = page_results(), grader_results()

    def test_every_case_agrees(self):
        for name in CASES:
            with self.subTest(name):
                self.assertEqual(self.page[name], self.grader[name])

    def test_ties_are_ranked_by_correct_exercises_then_name(self):
        csv_text = 'name,a,b,stretch\nZed,correct,submitted,\nAmy,submitted,submitted,4\nBen,correct,,2\nCal,,,\n'
        r = subprocess.run(['node', '-e', RANK_HARNESS, str(ROOT / 'scoring.js')], input=csv_text, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        # Zed, Amy and Ben all have 40 points: Zed and Ben have one correct exercise, so they come first (by name).
        self.assertEqual(json.loads(r.stdout), [[1, 'Ben', 40], [1, 'Zed', 40], [1, 'Amy', 40], [4, 'Cal', 0]])

    def test_cases_cover_what_they_claim(self):
        self.assertEqual([p['name'] for p in self.page['quotes_commas_and_blank_rows']['people']], ['Rao, Asha "AR"'])
        self.assertEqual(self.page['quotes_commas_and_blank_rows']['skipped'], 1)  # the row with only spaces for a name
        ann = self.page['excel_semicolons_bom_crlf']['people'][0]
        self.assertEqual((ann['tracks']['fizzbuzz'], ann['bonus'], ann['points']), ('correct', -4, 30 + 10 + 10 - 4))


if __name__ == '__main__':
    unittest.main()
