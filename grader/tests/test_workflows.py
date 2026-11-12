"""The GitHub Actions workflows, run locally by simulate_workflows.py. Needs git and Ruby (to read the YAML)."""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('ruby') and shutil.which('git'), 'needs git and Ruby')
class WorkflowTests(unittest.TestCase):
    def test_facilitator_and_publish_workflows(self):
        script = Path(__file__).with_name('simulate_workflows.py')
        r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('workflow checks passed', r.stdout)


if __name__ == '__main__':
    unittest.main()
