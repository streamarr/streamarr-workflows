#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "::error::$1" >&2
  exit 1
}

target() {
  case "${RUNNER_OS}-${RUNNER_ARCH}" in
    Linux-X64) echo linux64 ;;
    Linux-ARM64) echo linuxarm64 ;;
    *) fail "streamarr-ffmpeg has no build for ${RUNNER_OS} ${RUNNER_ARCH}" ;;
  esac
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
    return
  fi
  shasum -a 256 "$1" | cut -d ' ' -f 1
}

[[ "${FFMPEG_RELEASE}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-[0-9]+-streamarr\.[0-9]+$ ]] \
  || fail 'release must be a streamarr-ffmpeg tag such as v8.1.3-2-streamarr.1'
[[ "${FFMPEG_SHA256}" =~ ^[0-9a-f]{64}$ ]] \
  || fail 'sha256 must be 64 lowercase hexadecimal characters'

asset="streamarr-ffmpeg_${FFMPEG_RELEASE#v}_portable_$(target)-gpl.tar.xz"
archive="${FFMPEG_ARCHIVE_DIRECTORY}/${asset}"

matches_checksum() {
  [[ -f "${archive}" && "$(sha256 "${archive}")" == "${FFMPEG_SHA256}" ]]
}

# The checksum is verified on every run, so a restored archive is trusted no more than a download.
if ! matches_checksum; then
  mkdir -p "${FFMPEG_ARCHIVE_DIRECTORY}"
  curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 --silent --show-error \
    "https://github.com/streamarr/streamarr-ffmpeg/releases/download/${FFMPEG_RELEASE}/${asset}" \
    --output "${archive}"
fi
if ! matches_checksum; then
  rm -f "${archive}"
  fail "${asset} does not match the pinned SHA-256 checksum"
fi

binaries="${FFMPEG_INSTALL_DIRECTORY}/bin"
mkdir -p "${binaries}"
tar --extract --xz --file "${archive}" --directory "${binaries}" ffmpeg ffprobe
echo "${binaries}" >>"${GITHUB_PATH}"
