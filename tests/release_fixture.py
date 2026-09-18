import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


class ReleaseFixture:
    def __init__(self, directory):
        self.root = Path(directory)
        self.state_path = self.root / 'github.json'
        self.environment = dict(os.environ, GITHUB_REPOSITORY='streamarr/example',
            GITHUB_OUTPUT=str(self.root / 'outputs'), RELEASE_TAG='v1.2.3',
            GH_TOKEN='fixture-token', RELEASE_PR='{}',
            RELEASE_FIXTURE=str(self.state_path),
            GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
            GIT_AUTHOR_NAME='Release fixture', GIT_COMMITTER_NAME='Release fixture',
            GIT_AUTHOR_EMAIL='fixture@example.test', GIT_COMMITTER_EMAIL='fixture@example.test')
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'gh').symlink_to(ROOT / 'tests/fixtures/release-gh')
        self.environment['PATH'] = str(tools) + os.pathsep + os.environ['PATH']
        self.git('init', '--quiet', '--initial-branch=main')
        self.git('commit', '--quiet', '--allow-empty', '-m', 'fixture')
        self.git('tag', 'v1.2.3')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.revision = self.git('rev-parse', 'HEAD')
        self.state(allow_auto_merge=True, pulls=[], releases={'v1.2.3': {'draft': False}},
                   head={'sha': self.revision})
        (self.root / 'mvnw').write_text(
            '#!/bin/sh\nset -eu\ncase "$*" in *-Dexpression=project.version*) '
            'cat maven-version;; *) exit 81;; esac\n')
        (self.root / 'mvnw').chmod(0o755)
        self.version('1.2.3')

    def state(self, **changes):
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        state.update(changes)
        self.state_path.write_text(json.dumps(state))
        return state

    def version(self, value):
        (self.root / 'maven-version').write_text(value)

    def git(self, *arguments):
        return subprocess.check_output(
            ['git', '-c', 'commit.gpgsign=false', *arguments], cwd=self.root,
            env=self.environment, text=True).strip()

    def run(self, action, *arguments):
        return subprocess.run(['bash', str(ROOT / '.github/actions' / action / (action + '.sh')),
                               *arguments], cwd=self.root, env=self.environment,
                              capture_output=True, text=True, timeout=10)

    def outputs(self):
        path = self.root / 'outputs'
        return path.read_text() if path.exists() else ''
