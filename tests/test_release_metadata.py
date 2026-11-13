from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def release_steps():
    metadata = (ROOT / '.github/actions/release-please/action.yml').read_text()
    steps = {}
    for block in re.split(r'(?m)^    - name: ', metadata)[1:]:
        name, _, body = block.partition('\n')
        steps[name] = dict(re.findall(r'(?m)^ {6,8}([\w-]+): (.+?)(?: #.*)?$', body))
    return steps


class ReleaseMetadataTests(unittest.TestCase):
    def test_shouldPublishMergedReleasesFirstWhenMaintainingReleases(self):
        steps = release_steps()
        names = list(steps)
        publish = steps['Publish merged releases']
        maintain = steps['Maintain release PR']

        self.assertLess(names.index('Publish merged releases'),
                        names.index('Verify merged releases were processed'))
        self.assertLess(names.index('Verify merged releases were processed'),
                        names.index('Maintain release PR'))
        for step in [publish, maintain]:
            with self.subTest(action=step):
                self.assertRegex(step['uses'], r'^googleapis/release-please-action@[a-f0-9]{40}$')
                self.assertEqual(step['token'], '${{ steps.bot.outputs.token }}')
                self.assertEqual(step['target-branch'], 'main')
        self.assertEqual(publish['skip-github-pull-request'], 'true')
        self.assertEqual(maintain['skip-github-release'], 'true')

    def test_shouldAdoptCreatedReleasesBeforePublishingWhenMaintainingReleases(self):
        steps = release_steps()
        names = list(steps)
        adopt = steps['Adopt releases that an earlier run created']

        self.assertLess(names.index('Mint release bot token'),
                        names.index('Adopt releases that an earlier run created'))
        self.assertLess(names.index('Adopt releases that an earlier run created'),
                        names.index('Publish merged releases'))
        self.assertEqual(adopt['run'], 'bash "$GITHUB_ACTION_PATH/release-please.sh" adopt')
        self.assertEqual(adopt['GH_TOKEN'], '${{ steps.bot.outputs.token }}')

    def test_shouldRunPendingCheckAsReleaseBotWhenVerifyingMergedReleases(self):
        verify = release_steps()['Verify merged releases were processed']

        self.assertEqual(verify['run'], 'bash "$GITHUB_ACTION_PATH/release-please.sh" pending')
        self.assertEqual(verify['GH_TOKEN'], '${{ steps.bot.outputs.token }}')

    def test_shouldAuthenticateAsReleaseAppWhenMaintainingReleases(self):
        steps = release_steps()
        token = steps['Mint release bot token']

        self.assertEqual(token['id'], 'bot')
        self.assertRegex(token['uses'], r'^actions/create-github-app-token@[a-f0-9]{40}$')
        self.assertEqual(token['client-id'], '${{ inputs.app-client-id }}')
        self.assertEqual(token['private-key'], '${{ inputs.app-private-key }}')
        for permission in ['contents', 'pull-requests', 'issues']:
            with self.subTest(permission=permission):
                self.assertEqual(token['permission-' + permission], 'write')
        names = list(steps)
        self.assertLess(names.index('Mint release bot token'), names.index('Publish merged releases'))
