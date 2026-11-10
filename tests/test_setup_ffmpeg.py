import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'v8.1.3-2-streamarr.1'
RELEASES = 'https://github.com/streamarr/streamarr-ffmpeg/releases/download/' + RELEASE + '/'
LINUX64_ASSET = 'streamarr-ffmpeg_8.1.3-2-streamarr.1_portable_linux64-gpl.tar.xz'


class SetupFfmpegTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.release_archive = self.root / 'release.tar.xz'
        with tarfile.open(self.release_archive, 'w:xz') as archive:
            for member in ['ffmpeg', 'ffprobe', 'LICENSE.txt']:
                content = member.encode()
                entry = tarfile.TarInfo(member)
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'curl').symlink_to(ROOT / 'tests/fixtures/ffmpeg-curl')
        self.archives = self.root / 'archive'
        self.binaries = self.root / 'install/bin'
        self.environment = dict(
            os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
            RUNNER_OS='Linux', RUNNER_ARCH='X64', FFMPEG_RELEASE=RELEASE,
            FFMPEG_SHA256=hashlib.sha256(self.release_archive.read_bytes()).hexdigest(),
            FFMPEG_ARCHIVE_DIRECTORY=str(self.archives),
            FFMPEG_INSTALL_DIRECTORY=str(self.root / 'install'),
            GITHUB_PATH=str(self.root / 'path'), FFMPEG_FIXTURE=str(self.root / 'curl.json'))
        self.curl()

    def curl(self, **state):
        (self.root / 'curl.json').write_text(json.dumps(
            {'archive': str(self.release_archive), 'calls': str(self.root / 'calls')} | state))

    def run_setup(self):
        return subprocess.run(
            ['bash', str(ROOT / '.github/actions/setup-ffmpeg/setup-ffmpeg.sh')],
            env=self.environment, capture_output=True, text=True, timeout=10)

    def downloads(self):
        calls = self.root / 'calls'
        return calls.read_text().splitlines() if calls.exists() else []

    def added_paths(self):
        path = self.root / 'path'
        return path.read_text() if path.exists() else ''

    def assertNothingInstalled(self):
        self.assertFalse(self.binaries.exists())
        self.assertEqual(self.added_paths(), '')

    def test_shouldPutFfmpegAndFfprobeOnThePathWhenTheArchiveMatchesItsChecksum(self):
        result = self.run_setup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(entry.name for entry in self.binaries.iterdir()),
                         ['ffmpeg', 'ffprobe'])
        self.assertEqual(self.added_paths(), str(self.binaries) + '\n')
        self.assertEqual(self.downloads(), [RELEASES + LINUX64_ASSET])

    def test_shouldDownloadTheArchiveBuiltForTheRunnersArchitecture(self):
        for architecture, target in [('X64', 'linux64'), ('ARM64', 'linuxarm64')]:
            with self.subTest(architecture=architecture):
                self.environment['RUNNER_ARCH'] = architecture
                (self.root / 'calls').unlink(missing_ok=True)

                result = self.run_setup()

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.downloads(), [
                    RELEASES + 'streamarr-ffmpeg_8.1.3-2-streamarr.1_portable_' + target
                    + '-gpl.tar.xz'])

    def test_shouldInstallNothingWhenTheDownloadDoesNotMatchItsChecksum(self):
        self.environment['FFMPEG_SHA256'] = '0' * 64

        result = self.run_setup()

        self.assertEqual(result.returncode, 1)
        self.assertIn('does not match the pinned SHA-256 checksum', result.stderr)
        self.assertNothingInstalled()
        self.assertFalse((self.archives / LINUX64_ASSET).exists())

    def test_shouldNotDownloadWhenTheRestoredArchiveMatchesItsChecksum(self):
        self.archives.mkdir()
        (self.archives / LINUX64_ASSET).write_bytes(self.release_archive.read_bytes())

        result = self.run_setup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.downloads(), [])
        self.assertTrue((self.binaries / 'ffmpeg').exists())

    def test_shouldDownloadAgainWhenTheRestoredArchiveDoesNotMatchItsChecksum(self):
        self.archives.mkdir()
        (self.archives / LINUX64_ASSET).write_text('damaged')

        result = self.run_setup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.downloads(), [RELEASES + LINUX64_ASSET])
        self.assertTrue((self.binaries / 'ffmpeg').exists())

    def test_shouldInstallNothingWhenTheDownloadFails(self):
        self.curl(status=22)

        result = self.run_setup()

        self.assertNotEqual(result.returncode, 0)
        self.assertNothingInstalled()

    def test_shouldRejectARunnerThatHasNoBuild(self):
        for system, architecture in [('Windows', 'X64'), ('macOS', 'ARM64'), ('Linux', 'X86')]:
            with self.subTest(system=system, architecture=architecture):
                self.environment.update(RUNNER_OS=system, RUNNER_ARCH=architecture)

                result = self.run_setup()

                self.assertEqual(result.returncode, 1)
                self.assertIn('::error::', result.stderr)
                self.assertEqual(self.downloads(), [])
                self.assertNothingInstalled()

    def test_shouldRejectAMalformedReleaseOrChecksum(self):
        checksum = self.environment['FFMPEG_SHA256']
        for release, sha256 in [('8.1.3-2-streamarr.1', checksum), ('v8.1.3', checksum),
                                (RELEASE + '/../other', checksum), ('', checksum),
                                (RELEASE, ''), (RELEASE, checksum.upper()),
                                (RELEASE, checksum[:63])]:
            with self.subTest(release=release, sha256=sha256):
                self.environment.update(FFMPEG_RELEASE=release, FFMPEG_SHA256=sha256)

                result = self.run_setup()

                self.assertEqual(result.returncode, 1)
                self.assertIn('::error::', result.stderr)
                self.assertEqual(self.downloads(), [])
                self.assertNothingInstalled()
