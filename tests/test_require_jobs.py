import json
import os
from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / '.github/actions/require-jobs/require-jobs.sh'


def needs(**results):
    return json.dumps({job: {'result': result, 'outputs': {}} for job, result in results.items()})


def require_jobs(jobs, allowed_skips=''):
    environment = dict(os.environ, NEEDED_JOBS=jobs, ALLOWED_SKIPS=allowed_skips)
    return subprocess.run(['bash', str(SCRIPT)], env=environment, capture_output=True, text=True,
                          timeout=10)


class RequireJobsTests(unittest.TestCase):
    def test_shouldPassWhenEveryNeededJobSucceeded(self):
        result = require_jobs(needs(static='success', unit='success'))

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shouldFailWhenANeededJobDidNotSucceed(self):
        for outcome in ['failure', 'cancelled', 'skipped']:
            with self.subTest(outcome=outcome):
                result = require_jobs(needs(static='success', unit=outcome))

                self.assertEqual(result.returncode, 1)
                self.assertIn('::error::unit finished as ' + outcome, result.stderr)
                self.assertNotIn('static finished', result.stderr)

    def test_shouldReportEveryJobThatDidNotSucceed(self):
        result = require_jobs(needs(static='failure', unit='success', browser='cancelled'))

        self.assertEqual(result.returncode, 1)
        self.assertIn('::error::static finished as failure', result.stderr)
        self.assertIn('::error::browser finished as cancelled', result.stderr)

    def test_shouldPassWhenAnAllowedSkipWasSkippedOrSucceeded(self):
        for allowed_skips in ['package_image,publish', 'package_image, publish',
                              'publish package_image']:
            for outcome in ['skipped', 'success']:
                with self.subTest(allowed_skips=allowed_skips, outcome=outcome):
                    result = require_jobs(
                        needs(unit='success', package_image=outcome, publish='skipped'),
                        allowed_skips)

                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_shouldFailWhenAnAllowedSkipFailedOrWasCancelled(self):
        for outcome in ['failure', 'cancelled']:
            with self.subTest(outcome=outcome):
                result = require_jobs(needs(unit='success', package_image=outcome),
                                      'package_image')

                self.assertEqual(result.returncode, 1)
                self.assertIn('::error::package_image finished as ' + outcome, result.stderr)

    def test_shouldFailWhenASkippedJobIsNotAnAllowedSkip(self):
        result = require_jobs(needs(unit='skipped', package_image='skipped'), 'package_image')

        self.assertEqual(result.returncode, 1)
        self.assertIn('::error::unit finished as skipped', result.stderr)

    def test_shouldFailWhenAnAllowedSkipIsNotANeededJob(self):
        result = require_jobs(needs(unit='success'), 'package-image')

        self.assertEqual(result.returncode, 1)
        self.assertIn('package-image', result.stderr)

    def test_shouldFailWhenTheNeedsContextListsNoReadableJobs(self):
        for jobs in ['', '{}', 'null', '[]', 'not json', '{"unit": {}}', '{"unit": "success"}',
                     '{"unit": {"result": null}}']:
            with self.subTest(jobs=jobs):
                result = require_jobs(jobs)

                self.assertEqual(result.returncode, 1)
                self.assertIn('::error::', result.stderr)
