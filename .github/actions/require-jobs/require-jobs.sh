#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "::error::$1" >&2
  exit 1
}

lists() {
  grep --quiet --line-regexp --fixed-strings -- "$2" <<<"$1"
}

results="$(jq --raw-output '
  if type == "object" and all(.[]; type == "object" and (.result | type) == "string")
  then to_entries[] | "\(.key) \(.value.result)"
  else error("unreadable needs context")
  end' <<<"${NEEDED_JOBS}" 2>/dev/null)" || results=''
[[ -n "${results}" ]] || fail 'Pass toJSON(needs) from a job that needs at least one job'

needed_jobs="$(cut -d ' ' -f 1 <<<"${results}")"
allowed_skips="$(tr ', ' '\n\n' <<<"${ALLOWED_SKIPS}" | sed '/^$/d')"

while read -r allowed; do
  [[ -n "${allowed}" ]] || continue
  lists "${needed_jobs}" "${allowed}" \
    || fail "allowed-skips lists ${allowed}, which the calling job does not need"
done <<<"${allowed_skips}"

failed=0
while read -r job result; do
  echo "${job}: ${result}"
  if [[ "${result}" == success ]]; then
    continue
  fi
  if [[ "${result}" == skipped ]] && lists "${allowed_skips}" "${job}"; then
    continue
  fi
  echo "::error::${job} finished as ${result}" >&2
  failed=1
done <<<"${results}"
exit "${failed}"
