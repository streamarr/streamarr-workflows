import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'streamarr/streamarr-server'
REVISION = 'a' * 40
AMD64 = 'sha256:' + '1' * 64
ARM64 = 'sha256:' + '2' * 64
INDEX = 'sha256:' + '3' * 64


class ImagePublicationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.registry = self.root / 'registry.json'
        self.native = [
            {'digest': AMD64, 'platform': {'os': 'linux', 'architecture': 'amd64'}},
            {'digest': ARM64, 'platform': {'os': 'linux', 'architecture': 'arm64'}},
        ]
        self.registry.write_text(json.dumps({
            'indexDigest': INDEX,
            'images': {f'{IMAGE}@{image["digest"]}': [image] for image in self.native},
        }))
        for architecture, digest in [('amd64', AMD64), ('arm64', ARM64)]:
            self.receipt(architecture, image=f'{IMAGE}@{digest}')
        self.environment = dict(os.environ,
            PATH=str(ROOT / 'tests/fixtures/publication') + os.pathsep + os.environ['PATH'],
            FAKE_REGISTRY=str(self.registry), FAKE_MAIN_REVISION=REVISION,
            FAKE_LATEST_TAG='v1.2.3',
            GITHUB_SHA=REVISION, GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='push',
            GITHUB_REPOSITORY=IMAGE, IMAGE_REPOSITORY=IMAGE,
            SOURCE_REVISION=REVISION, IMAGE_VERSION='1.2.3-SNAPSHOT', PUBLICATION_KIND='snapshot',
            GITHUB_OUTPUT=str(self.root / 'output'),
            GITHUB_STEP_SUMMARY=str(self.root / 'summary'),
        )

    def receipt(self, architecture, /, **overrides):
        value = {'sourceRevision': REVISION, 'architecture': architecture,
                 'image': f'{IMAGE}@{AMD64 if architecture == "amd64" else ARM64}'}
        (self.root / f'{architecture}-image.json').write_text(json.dumps(value | overrides))

    def publish(self):
        return subprocess.run(['bash', str(ROOT / '.github/actions/publish-image/publish.sh')],
                              cwd=self.root, env=self.environment, capture_output=True,
                              text=True, timeout=10)

    def images(self):
        return json.loads(self.registry.read_text())['images']

    def registry_state(self, **overrides):
        self.registry.write_text(json.dumps(json.loads(self.registry.read_text()) | overrides))

    def test_shouldPublishSnapshotAndImmutableReceiptWhenBothArchitecturesPass(self):
        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.images()[f'{IMAGE}:1.2.3-SNAPSHOT'], self.native)
        self.assertEqual(self.images()[f'{IMAGE}:sha-{REVISION}'], self.native)
        self.assertEqual(json.loads((self.root / 'image.json').read_text()), {
            'sourceRevision': REVISION, 'version': '1.2.3-SNAPSHOT', 'image': f'{IMAGE}@{INDEX}',
            'nativeImages': {'amd64': f'{IMAGE}@{AMD64}', 'arm64': f'{IMAGE}@{ARM64}'},
        })
        self.assertEqual((self.root / 'output').read_text(), f'image={IMAGE}@{INDEX}\n')

    def test_shouldPublishStableAndLatestWhenVerifiedImagesBelongToLatestRelease(self):
        self.environment.update(PUBLICATION_KIND='release', IMAGE_VERSION='1.2.3',
                                GITHUB_EVENT_NAME='release', GITHUB_EVENT_ACTION='released',
                                GITHUB_REF='refs/tags/v1.2.3')

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.images()[f'{IMAGE}:1.2.3'], self.native)
        self.assertEqual(self.images()[f'{IMAGE}:latest'], self.native)
        self.assertEqual((self.root / 'output').read_text(), f'image={IMAGE}@{INDEX}\n')

    def test_shouldKeepNewerSnapshotWhenAnOlderMainRunIsRetried(self):
        newer = [{'digest': 'sha256:' + '9' * 64}]
        self.registry_state(images=self.images() | {f'{IMAGE}:1.2.3-SNAPSHOT': newer})
        self.environment['FAKE_MAIN_REVISION'] = 'b' * 40

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.images()[f'{IMAGE}:1.2.3-SNAPSHOT'], newer)
        self.assertEqual(self.images()[f'{IMAGE}:sha-{REVISION}'], self.native)

    def test_shouldLeaveStableTagsToReleaseWorkflowWhenMainHasStableMavenVersion(self):
        self.environment['IMAGE_VERSION'] = '1.2.3'

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(f'{IMAGE}:1.2.3', self.images())
        self.assertNotIn(f'{IMAGE}:latest', self.images())
        self.assertEqual(self.images()[f'{IMAGE}:sha-{REVISION}'], self.native)

    def test_shouldRejectPublicationWhenTriggerOrSourceIsUntrusted(self):
        for overrides in [
            {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': 'refs/pull/1/merge'},
            {'GITHUB_REF': 'refs/heads/feature/image'},
            {'GITHUB_EVENT_NAME': 'workflow_dispatch'},
            {'GITHUB_REPOSITORY': 'fork/streamarr-server'},
            {'IMAGE_REPOSITORY': 'streamarr/unrelated'},
            {'SOURCE_REVISION': 'abc123'},
            {'SOURCE_REVISION': 'b' * 40},
            {'PUBLICATION_KIND': 'unknown'},
        ]:
            with self.subTest(overrides=overrides):
                original = self.environment.copy()
                before = self.images()
                self.environment.update(overrides)
                result = self.publish()
                self.environment = original

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.images(), before)
                self.assertFalse((self.root / 'output').exists())

    def test_shouldRejectMalformedVersionWhenChoosingPublishedTag(self):
        for version in ['1.2.3-SNAPSHOT-SNAPSHOT', '01.2.3', '1.2', '1.2.3-RC1', '']:
            with self.subTest(version=version):
                self.environment['IMAGE_VERSION'] = version
                result = self.publish()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Maven version', result.stderr)
                self.assertEqual(len(self.images()), 2)

    def test_shouldRejectNativeReceiptWhenSourceArchitectureOrImageDoesNotMatch(self):
        for overrides in [
            {'sourceRevision': 'b' * 40}, {'architecture': 'amd64'},
            {'image': f'{IMAGE}:latest'}, {'image': f'streamarr/unrelated@{ARM64}'},
            {'image': f'{IMAGE}@sha256:invalid'},
        ]:
            with self.subTest(overrides=overrides):
                self.receipt('arm64', **overrides)
                result = self.publish()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Invalid native image receipt', result.stderr)
                self.assertEqual(len(self.images()), 2)

    def test_shouldRejectMissingReceiptWhenOnlyOneArchitectureFinished(self):
        (self.root / 'arm64-image.json').unlink()

        result = self.publish()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid native image receipt', result.stderr)
        self.assertEqual(len(self.images()), 2)

    def test_shouldWithholdAliasWhenIndexDoesNotContainExactlyBothLinuxArchitectures(self):
        for manifests in [self.native[:1], self.native[1:], self.native + self.native[:1],
                          [self.native[0], {'platform': {'os': 'windows', 'architecture': 'arm64'}}]]:
            with self.subTest(manifests=manifests):
                self.registry_state(indexOverride=manifests)
                result = self.publish()

                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(f'{IMAGE}:1.2.3-SNAPSHOT', self.images())
                self.assertFalse((self.root / 'output').exists())

    def test_shouldWithholdAliasWhenRegistryDoesNotReturnValidDigest(self):
        self.registry_state(indexDigest='sha256:invalid')

        result = self.publish()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('manifest digest', result.stderr)
        self.assertNotIn(f'{IMAGE}:1.2.3-SNAPSHOT', self.images())
        self.assertFalse((self.root / 'image.json').exists())

    def test_shouldPreserveRegistryFailureWhenInspectionAlsoReturnsValidPlatforms(self):
        self.registry_state(inspectExit=23)

        result = self.publish()

        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertNotIn(f'{IMAGE}:1.2.3-SNAPSHOT', self.images())
        self.assertFalse((self.root / 'image.json').exists())

    def test_shouldUseVerifiedDigestWhenCreatedTagIsReplaced(self):
        self.registry_state(replaceCreatedTag=True)

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.images()[f'{IMAGE}:1.2.3-SNAPSHOT'], self.native)
        self.assertEqual(json.loads((self.root / 'image.json').read_text())['image'], f'{IMAGE}@{INDEX}')

    def test_shouldWithholdSnapshotWhenGitHubCannotIdentifyCurrentMain(self):
        for overrides in [{'FAKE_GITHUB_FAILURE': 'true'}, {'FAKE_MAIN_REVISION': 'null'},
                          {'FAKE_MAIN_REVISION': ''}, {'FAKE_MAIN_REVISION': 'short'}]:
            with self.subTest(overrides=overrides):
                original = self.environment.copy()
                self.environment.update(overrides)
                result = self.publish()
                self.environment = original

                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(f'{IMAGE}:1.2.3-SNAPSHOT', self.images())

    def test_shouldKeepNewerLatestWhenManuallyRetryingOlderRelease(self):
        newer = [{'digest': 'sha256:' + '9' * 64}]
        self.registry_state(images=self.images() | {f'{IMAGE}:latest': newer})
        self.environment.update(PUBLICATION_KIND='release', IMAGE_VERSION='1.2.3',
                                GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA='b' * 40,
                                FAKE_LATEST_TAG='v1.3.0')

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.images()[f'{IMAGE}:1.2.3'], self.native)
        self.assertEqual(self.images()[f'{IMAGE}:latest'], newer)
        self.assertEqual(json.loads((self.root / 'image.json').read_text())['sourceRevision'], REVISION)

    def test_shouldWithholdStablePublicationWhenEventIsNotReleaseOrRetry(self):
        self.environment.update(PUBLICATION_KIND='release', IMAGE_VERSION='1.2.3')
        for overrides in [{'GITHUB_EVENT_NAME': 'push'}, {'GITHUB_EVENT_NAME': 'pull_request'},
                          {'GITHUB_EVENT_NAME': 'release', 'GITHUB_EVENT_ACTION': 'created'},
                          {'GITHUB_EVENT_NAME': 'release', 'GITHUB_EVENT_ACTION': 'released',
                           'IMAGE_VERSION': '1.2.3-SNAPSHOT'}]:
            with self.subTest(overrides=overrides):
                self.environment.update(overrides)
                result = self.publish()

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(self.images()), 2)

    def test_shouldWithholdLatestWhenGitHubIsUnavailableDuringReleasePublication(self):
        self.environment.update(PUBLICATION_KIND='release', IMAGE_VERSION='1.2.3',
                                GITHUB_EVENT_NAME='workflow_dispatch', FAKE_GITHUB_FAILURE='true')

        result = self.publish()

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(f'{IMAGE}:latest', self.images())

    def test_shouldPublishWorkerImageWhenCalledFromWorkerRepository(self):
        worker = 'streamarr/streamarr-transcode-worker'
        self.registry_state(images={key.replace(IMAGE, worker): value for key, value in self.images().items()})
        self.environment.update(IMAGE_REPOSITORY=worker, GITHUB_REPOSITORY=worker)
        self.receipt('amd64', image=f'{worker}@{AMD64}')
        self.receipt('arm64', image=f'{worker}@{ARM64}')

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.images()[f'{worker}:1.2.3-SNAPSHOT'], self.native)
