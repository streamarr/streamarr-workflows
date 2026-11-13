#!/usr/bin/env bash
set -euo pipefail

stable_release_title='^chore\(main\): release ((0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*))$'

# Release Please creates a release before it comments on the PR and swaps its labels. When a
# later call fails, the PR stays pending, and GitHub accepts a second draft for the same tag.
adopt_created_release() {
  local number="$1" title="$2" merge_commit="$3"
  if [[ ! "${title}" =~ ${stable_release_title} ]]; then
    return 0
  fi
  local tag="v${BASH_REMATCH[1]}"
  local tagged elsewhere
  tagged="$(jq -s --arg tag "${tag}" 'map(select(.tag_name == $tag)) | length' <<<"${releases}")"
  elsewhere="$(jq -s --arg tag "${tag}" --arg commit "${merge_commit}" \
    'map(select(.tag_name == $tag and .target_commitish != $commit)) | length' <<<"${releases}")"
  if (( elsewhere > 0 )); then
    echo "::error::Release ${tag} targets a commit other than ${merge_commit}, the merge commit of release PR #${number}. Delete that release if it does not belong to the PR, then rerun Release Please" >&2
    exit 1
  fi
  if (( tagged == 0 )); then
    return 0
  fi
  if (( tagged > 1 )); then
    echo "::error::Release PR #${number} has ${tagged} releases tagged ${tag}. Keep the one whose notes you edited, delete the others, then rerun Release Please" >&2
    exit 1
  fi
  gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels" --method POST \
    -f 'labels[]=autorelease: tagged' >/dev/null
  gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels/autorelease%3A%20pending" \
    --method DELETE >/dev/null
  echo "::notice::Release PR #${number} already has release ${tag}, so it is now marked tagged"
}

case "${1:?Supply the release preparation step}" in
  auto-merge)
    auto_merge="$(gh api "repos/${GITHUB_REPOSITORY}" --jq '.allow_auto_merge')"
    case "${auto_merge}" in
      true) ;;
      false) echo "::error::Enable repository auto-merge before running release automation" >&2; exit 1 ;;
      *) echo "::error::Cannot determine repository auto-merge setting: allow_auto_merge=${auto_merge}. Check release App access." >&2; exit 1 ;;
    esac
    ;;
  adopt)
    pending="$(gh pr list --repo "${GITHUB_REPOSITORY}" --base main --state merged \
      --label 'autorelease: pending' --limit 100 --json number,title,mergeCommit \
      --jq '.[] | [.number, .title, .mergeCommit.oid] | @tsv')"
    if [[ -z "${pending}" ]]; then
      exit 0
    fi
    releases="$(gh api "repos/${GITHUB_REPOSITORY}/releases?per_page=100" --paginate \
      --jq '.[] | {tag_name, target_commitish}')"
    while IFS=$'\t' read -r -u 3 number title merge_commit; do
      adopt_created_release "${number}" "${title}" "${merge_commit}"
    done 3<<<"${pending}"
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
