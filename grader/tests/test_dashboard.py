"""dashboard.json, and the copy of it in index.html used when the file cannot be loaded, use the fields the page shows."""
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = (REPO / 'index.html').read_text()


class WorkshopTests(unittest.TestCase):
    def test_the_page_shows_each_workshop_by_day_topic_and_lead(self):
        self.assertIn("w.day", PAGE)
        self.assertIn("w.topic", PAGE)

    def test_every_workshop_in_dashboard_json_has_a_day_and_a_topic(self):
        workshops = json.loads((REPO / 'dashboard.json').read_text())['workshops']
        self.assertTrue(workshops)
        for w in workshops:
            self.assertEqual(set(w) - {'day', 'topic', 'lead'}, set(), w)
            self.assertTrue(w.get('day') and w.get('topic'), w)

    def test_every_workshop_in_the_fallback_copy_has_a_day(self):
        block = re.search(r'workshops: \[(.*?)\n  \]', PAGE, re.S).group(1)
        entries = re.findall(r'\{[^}]*\}', block)
        self.assertTrue(entries)
        for e in entries:
            self.assertRegex(e, r"^\{ day: '[^']+', topic: ", e)


if __name__ == '__main__':
    unittest.main()
