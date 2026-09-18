#!/usr/bin/env bash
set -euo pipefail

if [[ ${GITHUB_REPOSITORY:-} != streamarr/* || ${IMAGE_REPOSITORY:-} != "${GITHUB_REPOSITORY:-}" ]]; then
  echo 'Image publication requires the matching Streamarr repository.' >&2
  exit 1
fi
if [[ ! ${SOURCE_REVISION:-} =~ ^[a-f0-9]{40}$ ]]; then
  echo 'Image publication requires a full source revision.' >&2
  exit 1
fi

case ${PUBLICATION_KIND:-} in
  snapshot)
    if [[ ${GITHUB_EVENT_NAME:-} != push || ${GITHUB_REF:-} != refs/heads/main \
      || $SOURCE_REVISION != "${GITHUB_SHA:-}" ]]; then
      echo 'Snapshot publication requires the source revision of a reviewed main push.' >&2
      exit 1
    fi
    tag="sha-${SOURCE_REVISION}"
    ;;
  release)
    if [[ $IMAGE_VERSION == *-SNAPSHOT || ! ( ${GITHUB_EVENT_NAME:-} == workflow_dispatch \
      || ( ${GITHUB_EVENT_NAME:-} == release && ${GITHUB_EVENT_ACTION:-} == released ) ) ]]; then
      echo 'Stable publication requires a published release or its manual retry.' >&2
      exit 1
    fi
    tag=$IMAGE_VERSION
    ;;
  *) echo 'Publication kind must be snapshot or release.' >&2; exit 1 ;;
esac
if [[ ! ${IMAGE_VERSION:-} =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-SNAPSHOT)?$ ]]; then
  echo 'Maven version must be X.Y.Z or X.Y.Z-SNAPSHOT.' >&2
  exit 1
fi

references=()
for architecture in amd64 arm64; do
  if ! reference=$(jq -er --arg source "$SOURCE_REVISION" --arg architecture "$architecture" \
    --arg repository "$IMAGE_REPOSITORY" \
    'select(.sourceRevision == $source and .architecture == $architecture) | .image |
    select(startswith($repository + "@sha256:")) | select(test("@sha256:[a-f0-9]{64}$"))' \
    "${architecture}-image.json"); then
    echo "Invalid native image receipt for ${architecture}." >&2
    exit 1
  fi
  references+=("$reference")
done

docker buildx imagetools create --metadata-file image-metadata.json \
  --tag "${IMAGE_REPOSITORY}:${tag}" "${references[@]}"
digest=$(jq -er '."containerimage.descriptor".digest' image-metadata.json)
if [[ ! $digest =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo 'The registry did not return a valid manifest digest.' >&2
  exit 1
fi

image="${IMAGE_REPOSITORY}@${digest}"
docker buildx imagetools inspect --raw "$image" > image-index.json
jq -e '[.manifests[].platform | .os + "/" + .architecture] | sort == ["linux/amd64", "linux/arm64"]' image-index.json

if [[ $IMAGE_VERSION == *-SNAPSHOT ]]; then
  main_revision=$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq '.object.sha')
  if [[ ! $main_revision =~ ^[a-f0-9]{40}$ ]]; then
    echo 'GitHub did not return a valid main revision.' >&2
    exit 1
  fi
  if [[ $main_revision == "$SOURCE_REVISION" ]]; then
    docker buildx imagetools create --tag "${IMAGE_REPOSITORY}:${IMAGE_VERSION}" "$image"
  fi
fi

if [[ $PUBLICATION_KIND == release ]]; then
  latest_tag=$(gh api "repos/${GITHUB_REPOSITORY}/releases/latest" --jq '.tag_name')
  if [[ $latest_tag == "v${IMAGE_VERSION}" ]]; then
    docker buildx imagetools create --tag "${IMAGE_REPOSITORY}:latest" "$image"
  fi
fi

jq -n --arg source "$SOURCE_REVISION" --arg version "$IMAGE_VERSION" --arg image "$image" \
  --arg amd64 "${references[0]}" --arg arm64 "${references[1]}" \
  '{sourceRevision: $source, version: $version, image: $image, nativeImages: {amd64: $amd64, arm64: $arm64}}' \
  > image.json
echo "image=${image}" >> "$GITHUB_OUTPUT"
cat image.json >> "$GITHUB_STEP_SUMMARY"
