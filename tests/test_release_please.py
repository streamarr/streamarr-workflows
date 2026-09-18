import json
import tempfile
import unittest

from release_fixture import ReleaseFixture


class ReleasePleaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.release = ReleaseFixture(directory.name)

    def test_shouldRequireRepositoryAutoMergeWhenPreparingReleaseAutomation(self):
        for enabled, expected in [(True, 0), (False, 1), (None, 1)]:
            with self.subTest(enabled=enabled):
                self.release.state(allow_auto_merge=enabled)

                result = self.release.run('release-please', 'auto-merge')

                self.assertEqual(result.returncode, expected, result.stderr)

    def test_shouldBlockNextReleaseOnlyWhenMergedReleaseRemainsPending(self):
        for pulls, expected in [
            ([{'number': 42, 'base': 'main', 'state': 'merged',
               'labels': ['autorelease: pending']}], 1),
            ([{'number': 42, 'base': 'main', 'state': 'merged',
               'labels': ['autorelease: tagged']},
              {'number': 43, 'base': 'main', 'state': 'open',
               'labels': ['autorelease: pending']},
              {'number': 44, 'base': 'other', 'state': 'merged',
               'labels': ['autorelease: pending']}], 0),
        ]:
            with self.subTest(pulls=pulls):
                self.release.state(pulls=pulls)

                result = self.release.run('release-please', 'pending')

                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn('Unprocessed merged release PR #42', result.stderr)

    def test_shouldQueueAutoMergeOnlyWhenReleasePullRequestIsSnapshot(self):
        for label, queued in [('pending', False), ('snapshot', True)]:
            with self.subTest(label=label):
                self.release.environment['RELEASE_PR'] = json.dumps({
                    'number': 43, 'title': 'chore(main): release 1.2.4-SNAPSHOT',
                    'labels': ['autorelease: ' + label]})

                result = self.release.run('release-please', 'snapshot')

                self.assertEqual(result.returncode, 0, result.stderr)
                state = self.release.state()
                if not queued:
                    self.assertNotIn('autoMerge', state)
                    continue
                self.assertEqual(state['autoMerge'], {
                    'number': 43, 'head': self.release.revision,
                    'subject': 'chore(main): release 1.2.4-SNAPSHOT',
                    'body': '', 'method': 'squash'})

    def test_shouldLeaveSnapshotUnqueuedWhenGitHubReturnsInvalidHeadRevision(self):
        self.release.environment['RELEASE_PR'] = json.dumps({
            'number': 43, 'title': 'chore(main): release 1.2.4-SNAPSHOT',
            'labels': ['autorelease: snapshot']})
        for head in ['', None, 'abc123']:
            with self.subTest(head=head):
                self.release.state(head={'sha': head})

                result = self.release.run('release-please', 'snapshot')

                self.assertEqual(result.returncode, 1)
                self.assertIn('Release PR has no head revision', result.stderr)
                self.assertNotIn('autoMerge', self.release.state())

    def test_shouldStopReleasePreparationWhenGitHubIsUnavailable(self):
        self.release.state(unavailable=True)
        self.release.environment['RELEASE_PR'] = json.dumps({
            'number': 43, 'title': 'chore(main): release 1.2.4-SNAPSHOT',
            'labels': ['autorelease: snapshot']})
        for step in ['auto-merge', 'pending', 'snapshot']:
            with self.subTest(step=step):
                result = self.release.run('release-please', step)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn('GitHub unavailable', result.stderr)
                self.assertNotIn('autoMerge', self.release.state())

    def test_shouldLeaveSnapshotUnqueuedWhenHeadChangesBeforeMergeRequest(self):
        self.release.state(head_after_read='f' * 40)
        self.release.environment['RELEASE_PR'] = json.dumps({
            'number': 43, 'title': 'chore(main): release 1.2.4-SNAPSHOT',
            'labels': ['autorelease: snapshot']})

        result = self.release.run('release-please', 'snapshot')

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Pull request head changed', result.stderr)
        self.assertNotIn('autoMerge', self.release.state())
