#!/usr/bin/env bash
set -euo pipefail

case "${1:?Supply the release preparation step}" in
  auto-merge)
    auto_merge="$(gh api "repos/${GITHUB_REPOSITORY}" --jq '.allow_auto_merge')"
    case "${auto_merge}" in
      true) ;;
      false) echo "::error::Enable repository auto-merge before running release automation" >&2; exit 1 ;;
      *) echo "::error::Cannot determine repository auto-merge setting: allow_auto_merge=${auto_merge}. Check release App access." >&2; exit 1 ;;
    esac
    ;;
  pending)
    pending="$(gh pr list --repo "${GITHUB_REPOSITORY}" --base main --state merged \
      --label 'autorelease: pending' --limit 1 --json number --jq '.[0].number // empty')"
    if [[ -n "${pending}" ]]; then
      echo "::error::Unprocessed merged release PR #${pending}: restore its release title and body, then rerun Release Please" >&2
      exit 1
    fi
    ;;
  snapshot)
    if ! jq -e '.labels | index("autorelease: snapshot")' <<<"${RELEASE_PR}" >/dev/null; then
      exit 0
    fi
    number="$(jq -r '.number' <<<"${RELEASE_PR}")"
    title="$(jq -r '.title' <<<"${RELEASE_PR}")"
    head="$(gh api "repos/${GITHUB_REPOSITORY}/pulls/${number}" --jq '.head.sha')"
    if [[ ! "${head}" =~ ^[a-f0-9]{40}$ ]]; then
      echo "::error::Release PR has no head revision" >&2
      exit 1
    fi
    gh pr merge "${number}" --repo "${GITHUB_REPOSITORY}" --auto --squash \
      --match-head-commit "${head}" --subject "${title}" --body ''
    ;;
  *) echo 'Unknown release preparation step' >&2; exit 1 ;;
esac
