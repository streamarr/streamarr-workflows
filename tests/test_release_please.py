import json
import tempfile
import unittest

from release_fixture import ReleaseFixture


MERGE_COMMIT = 'c' * 40


def merged_release_pull(**changes):
    return {'number': 42, 'base': 'main', 'state': 'merged', 'title': 'chore(main): release 1.2.4',
            'mergeCommit': {'oid': MERGE_COMMIT}, 'labels': ['autorelease: pending']} | changes


def created_release(**changes):
    return {'tag_name': 'v1.2.4', 'target_commitish': MERGE_COMMIT, 'draft': True} | changes


def lightweight_tag(commit):
    return {'type': 'commit', 'sha': commit}


def labels_of(state, number):
    return next(pull['labels'] for pull in state['pulls'] if pull['number'] == number)


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

    def test_shouldMarkPullRequestTaggedWhenEarlierRunCreatedItsRelease(self):
        for draft in [True, False]:
            for labels in [['autorelease: pending'], ['autorelease: pending', 'autorelease: tagged']]:
                with self.subTest(draft=draft, labels=labels):
                    releases = [self.release.published_release(), created_release(draft=draft)]
                    self.release.state(pulls=[merged_release_pull(labels=labels)], releases=releases,
                                       tags={'v1.2.4': lightweight_tag(MERGE_COMMIT)})

                    result = self.release.run('release-please', 'adopt')

                    self.assertEqual(result.returncode, 0, result.stderr)
                    state = self.release.state()
                    self.assertEqual(labels_of(state, 42), ['autorelease: tagged'])
                    self.assertEqual(state['releases'], releases)
                    pending = self.release.run('release-please', 'pending')
                    self.assertEqual(pending.returncode, 0, pending.stderr)

    def test_shouldMarkPullRequestTaggedWhenItsReleaseResolvesToMergeCommit(self):
        annotated = 'a' * 40
        for case, release, tags in [
            ('annotated tag at the merge commit', created_release(),
             {'v1.2.4': {'type': 'tag', 'sha': annotated}}),
            ('tag at the merge commit, release target a branch',
             created_release(target_commitish='main'), {'v1.2.4': lightweight_tag(MERGE_COMMIT)}),
            ('no tag yet, release target the merge commit', created_release(), {}),
            ('no tag yet, a longer tag shares its name', created_release(),
             {'v1.2.40': lightweight_tag('e' * 40)}),
        ]:
            with self.subTest(case=case):
                self.release.state(pulls=[merged_release_pull()], releases=[release], tags=tags,
                                   tag_objects={annotated: lightweight_tag(MERGE_COMMIT)})

                result = self.release.run('release-please', 'adopt')

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(labels_of(self.release.state(), 42), ['autorelease: tagged'])

    def test_shouldMarkOnlyPullRequestsWithCreatedReleasesWhenSeveralRemainPending(self):
        self.release.state(
            pulls=[merged_release_pull(number=41),
                   merged_release_pull(number=42, title='chore(main): release 1.2.5',
                                       mergeCommit={'oid': 'd' * 40})],
            releases=[self.release.published_release(),
                      created_release(tag_name='v1.2.5', target_commitish='d' * 40)])

        result = self.release.run('release-please', 'adopt')

        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.release.state()
        self.assertEqual(labels_of(state, 41), ['autorelease: pending'])
        self.assertEqual(labels_of(state, 42), ['autorelease: tagged'])

    def test_shouldChangeNothingWhenNoReleaseHasPendingPullRequestTag(self):
        for pull, releases in [
            (merged_release_pull(), [self.release.published_release()]),
            (merged_release_pull(title='chore(main): release 1.2.4-SNAPSHOT'),
             [created_release(tag_name='v1.2.4-SNAPSHOT')]),
            (merged_release_pull(title='release 1.2.4'), [created_release()]),
        ]:
            with self.subTest(title=pull['title']):
                before = self.release.state(pulls=[pull], releases=releases)

                result = self.release.run('release-please', 'adopt')

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.release.state(), before)

    def test_shouldFailWithoutChangesWhenReleaseWithPendingTagIsAtAnotherCommit(self):
        other, annotated = 'e' * 40, 'a' * 40
        for case, releases, tags in [
            ('no tag yet, release target a branch', [created_release(target_commitish='main')], {}),
            ('no tag yet, one release target another commit',
             [created_release(), created_release(target_commitish=other)], {}),
            ('tag at another commit', [created_release()], {'v1.2.4': lightweight_tag(other)}),
            ('annotated tag at another commit', [created_release()],
             {'v1.2.4': {'type': 'tag', 'sha': annotated}}),
        ]:
            with self.subTest(case=case):
                before = self.release.state(pulls=[merged_release_pull()], releases=releases,
                                            tags=tags, tag_objects={annotated: lightweight_tag(other)})

                result = self.release.run('release-please', 'adopt')

                self.assertEqual(result.returncode, 1)
                self.assertIn(MERGE_COMMIT + ', the merge commit of release PR #42', result.stderr)
                self.assertEqual(self.release.state(), before)

    def test_shouldFailWithoutChangesWhenSeveralReleasesHavePendingTag(self):
        before = self.release.state(pulls=[merged_release_pull()],
                                    releases=[created_release(), created_release()],
                                    tags={'v1.2.4': lightweight_tag(MERGE_COMMIT)})

        result = self.release.run('release-please', 'adopt')

        self.assertEqual(result.returncode, 1)
        self.assertIn('Release PR #42 has 2 releases tagged v1.2.4', result.stderr)
        self.assertEqual(self.release.state(), before)

    def test_shouldKeepPullRequestPendingWhenTagCannotBeRead(self):
        self.release.state(pulls=[merged_release_pull()], releases=[created_release()],
                           tags_unavailable=True)

        result = self.release.run('release-please', 'adopt')

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Tags unavailable', result.stderr)
        self.assertEqual(labels_of(self.release.state(), 42), ['autorelease: pending'])

    def test_shouldKeepPullRequestPendingWhenTaggedLabelCannotBeAdded(self):
        self.release.state(pulls=[merged_release_pull()], releases=[created_release()],
                           label_addition_fails=True)

        result = self.release.run('release-please', 'adopt')

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(labels_of(self.release.state(), 42), ['autorelease: pending'])

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
        for step in ['auto-merge', 'adopt', 'pending', 'snapshot']:
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
