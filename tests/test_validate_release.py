import tempfile
import unittest

from release_fixture import ReleaseFixture


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.release = ReleaseFixture(directory.name)

    def test_shouldExportVersionAndRevisionWhenPublishedReleaseMatchesMaven(self):
        result = self.release.run('validate-release')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.release.outputs(),
                         'version=1.2.3\nrevision=' + self.release.revision + '\n')

    def test_shouldRejectDifferentCheckoutWhenTagNamesAnotherRevision(self):
        self.release.git('commit', '--quiet', '--allow-empty', '-m', 'later revision')

        result = self.release.run('validate-release')

        self.assertEqual(result.returncode, 1)
        self.assertIn('Release tag does not match the checked-out revision', result.stderr)
        self.assertEqual(self.release.outputs(), '')

    def test_shouldRejectUnmergedReleaseWhenTaggedCommitIsOutsideMain(self):
        self.release.git('commit', '--quiet', '--allow-empty', '-m', 'unmerged revision')
        self.release.git('tag', '--force', 'v1.2.3')

        result = self.release.run('validate-release')

        self.assertEqual(result.returncode, 1)
        self.assertIn('Release revision is not an ancestor of main', result.stderr)
        self.assertEqual(self.release.outputs(), '')

    def test_shouldRejectReleaseWhenTagIsNotStableSemver(self):
        for version in ['01.2.3', '1.2', '1.2.3-SNAPSHOT', '1.2.3-rc.1', '1.2.3+build']:
            with self.subTest(version=version):
                self.release.git('tag', 'v' + version)
                self.release.version(version)
                self.release.environment['RELEASE_TAG'] = 'v' + version

                result = self.release.run('validate-release')

                self.assertEqual(result.returncode, 1)
                self.assertIn('Release tag must be stable SemVer', result.stderr)
                self.assertEqual(self.release.outputs(), '')

    def test_shouldRejectVersionDriftWhenMavenDiffersFromReleaseTag(self):
        self.release.version('1.2.4-SNAPSHOT')

        result = self.release.run('validate-release')

        self.assertEqual(result.returncode, 1)
        self.assertIn('Release tag and Maven version must agree', result.stderr)
        self.assertEqual(self.release.outputs(), '')

    def test_shouldWithholdOutputsWhenGitHubCannotConfirmPublishedRelease(self):
        for state in [
            {'releases': {'v1.2.3': {'draft': True}}},
            {'releases': {'v1.2.3': {'draft': None}}},
            {'releases': {}},
            {'unavailable': True},
        ]:
            with self.subTest(state=state):
                self.release.state(**({'unavailable': False,
                                       'releases': {'v1.2.3': {'draft': False}}} | state))

                result = self.release.run('validate-release')

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.release.outputs(), '')
