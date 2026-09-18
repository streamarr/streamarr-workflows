#!/usr/bin/env bash
set -euo pipefail

revision="$(git rev-parse HEAD)"
tagged_revision="$(git rev-parse --verify "refs/tags/${RELEASE_TAG}^{commit}")"
if [[ "${revision}" != "${tagged_revision}" ]]; then
  echo "::error::Release tag does not match the checked-out revision" >&2
  exit 1
fi
if ! git merge-base --is-ancestor "${revision}" origin/main; then
  echo "::error::Release revision is not an ancestor of main" >&2
  exit 1
fi
pom_version="$(./mvnw --batch-mode --quiet help:evaluate -Dexpression=project.version -DforceStdout)"
if [[ ! "${RELEASE_TAG}" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "::error::Release tag must be stable SemVer (vX.Y.Z)" >&2
  exit 1
fi
if [[ "${RELEASE_TAG}" != "v${pom_version}" ]]; then
  echo "::error::Release tag and Maven version must agree" >&2
  exit 1
fi
release_draft="$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/${RELEASE_TAG}" --jq '.draft')"
if [[ "${release_draft}" != "false" ]]; then
  echo "::error::Publish the GitHub release before publishing images" >&2
  exit 1
fi
echo "version=${pom_version}" >> "${GITHUB_OUTPUT}"
echo "revision=${revision}" >> "${GITHUB_OUTPUT}"
