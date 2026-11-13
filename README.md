# Streamarr Workflows

Shared GitHub Actions workflows and actions for Streamarr CI, releases and image publication.

Each application owns its build, tests, native image verification, and required `build` check.
This repository owns Release Please orchestration, stable release validation, and publication
of the verified multi-architecture image. It also holds the actions that every repository's CI
shares. Workflows require human review and merge.

## Workflows

| Workflow | Caller supplies | Result |
| --- | --- | --- |
| `release-please.yml` | Release App client ID and PEM private key | Processes merged releases, maintains release PRs, queues snapshot-version PR auto-merge |
| `validate-release.yml` | Optional published `vX.Y.Z` tag for a manual retry | Validated Maven `version` and source `revision` |
| `publish-image.yml` | Image repository, version, source revision, publication kind, and native receipt artifact pattern | Immutable `image` output and publication receipts |

Keep Release Please configuration in the application repository. Pass the organization
secrets `ORG_STREAMARR_RELEASE_CLIENT_ID` and `ORG_STREAMARR_RELEASE_PRIVATE_KEY` as
`app-client-id` and `app-private-key`. Stable release PRs require human merge. The existing
snapshot-version PR auto-merge exception still respects repository review and check rules.

Release Please creates a merged PR's release, then comments on the PR, then swaps its
`autorelease: pending` label for `autorelease: tagged`. If the comment or the label swap fails,
the PR stays pending. Before releases are created, `release-please.yml` therefore looks at each
merged `chore(main): release X.Y.Z` PR that is still pending. When exactly one release, draft or
published, has the tag `vX.Y.Z` at the PR's merge commit, the workflow swaps the labels and
Release Please skips the PR. A rerun therefore leaves one release, not a second draft. The tag's
commit counts, because GitHub ignores a release's target once its tag exists. A release whose tag
does not exist yet counts by its target. When no release has the tag, nothing changes. A release
with the tag at another commit, or more than one release with the tag, fails the run.

Pin each cross-repository workflow call to its reviewed full commit SHA. Once a version is
released, add its version comment so Renovate can propose pin updates. Adopt those updates
through human-reviewed PRs. Bundled actions use GitHub.com's `$/` references so they run from
the same repository revision as the reusable workflow, while checkout obtains application code.

## Actions

| Action | Caller supplies | Result |
| --- | --- | --- |
| `require-jobs` | The calling job's `needs` context and the jobs that may be skipped | Fails unless every needed job succeeded |
| `setup-ffmpeg` | A streamarr-ffmpeg release tag and the SHA-256 checksum of its archive | `ffmpeg` and `ffprobe` on the `PATH` |

Pin each action to a full commit SHA, as for a workflow call.

### Required `build` check

Each repository requires one check, `build`. Make it the last job of the CI workflow:

```yaml
build:
  name: build
  needs: [static, unit, browser]
  if: ${{ always() }}
  runs-on: ubuntu-latest
  timeout-minutes: 5
  steps:
    - uses: streamarr/streamarr-workflows/.github/actions/require-jobs@<full commit SHA>
      with:
        jobs: ${{ toJSON(needs) }}
```

- List every other job in `needs`.
- Keep `if: always()`. GitHub skips a job when a job it needs did not succeed, and a skipped
  required check counts as passing. With `always()` the job also runs after a needed job timed
  out or the run was cancelled, and the check then fails.
- Check out nothing and keep the time limit short. GitHub warns that an `always()` job that
  fetches sources can hang.
- `allowed-skips` lists the needed jobs that may be skipped, separated by commas or spaces. A
  listed job passes when it succeeded or was skipped. Every other result fails the check.

### FFmpeg

`setup-ffmpeg` installs the FFmpeg build that the transcode worker ships, from a
[streamarr-ffmpeg](https://github.com/streamarr/streamarr-ffmpeg/releases) release:

```yaml
- uses: streamarr/streamarr-workflows/.github/actions/setup-ffmpeg@<full commit SHA>
  with:
    release: v8.1.3-2-streamarr.1
    sha256: <SHA-256 checksum of the archive for the runner's architecture>
```

Each release publishes a `.sha256` file beside its archive. The action keeps the archive in the
Actions cache and verifies the checksum on every run, whether the archive came from the cache or
from the release. It supports Linux runners on x64 and arm64.

## Image publication contract

Build and test images in the application repository. Push each verified native image under
`sha-<source-revision>-<architecture>` and upload one JSON file per architecture:

```json
{
  "sourceRevision": "<full Git commit SHA>",
  "architecture": "amd64",
  "image": "streamarr/streamarr-server@sha256:<64 hexadecimal characters>"
}
```

Name the files `amd64-image.json` and `arm64-image.json`. Upload them as separate artifacts
from the current run. Their names must match the caller's `artifact-pattern`.

Call `publish-image.yml` after all required tests and both native image jobs succeed. Inputs:

- `image-repository`: Docker Hub name matching the calling Streamarr repository.
- `source-revision`: the full tested Git SHA. For a release, use the validator's `revision` output.
- `version`: the Maven version. For a release, use the validator's `version` output.
- `artifact-pattern`: artifact names containing this run's native receipts.
- `publication-kind`: `snapshot` for main builds or `release` for stable releases.

Pass `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` explicitly as `dockerhub-username` and
`dockerhub-token`. Grant `contents: read`. The publisher validates the native receipts,
builds the index from their digests, and verifies exactly `linux/amd64` and `linux/arm64`.

Main pushes publish `sha-<source-revision>`. A Maven `X.Y.Z-SNAPSHOT` also advances that
snapshot tag if the source is still current main. Main builds with a stable Maven version
leave version tags to the release workflow. PR and manual main CI runs do not publish.

Stable releases publish `X.Y.Z`. They advance `latest` only when GitHub identifies that
version as the latest release. Release retries use the validated tagged revision, which
can differ from the revision running the workflow. Aliases reference the inspected index
digest. SHA and version tags identify builds but can be republished. Consume `@sha256`
references when immutable contents are required.

Publication is serialized per repository and publication kind. Keep caller concurrency groups
distinct from the shared `publish-image-*` group. Callers retain their existing Release Please
and release-build serialization.

The `published-image-<source-revision>` artifact contains `image.json`, the native receipts,
and Docker's index and metadata. `image.json` records version, source revision, immutable image
reference, and both native references. Worker-specific contract metadata remains in its OCI label.

## Validation

Run `python3 -m unittest discover -s tests -v`. The tests execute the shell entry points with
real temporary Git repositories and stateful GitHub and registry fakes. They exercise publication
and release guards without writing to GitHub or Docker Hub.
