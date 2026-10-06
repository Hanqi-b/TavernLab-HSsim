#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
manifest="$script_dir/source-manifest.txt"
output_dir=${TAVERNLAB_DEB_OUTPUT_DIR:-"$repo_root/dist"}
image=${TAVERNLAB_DEB_IMAGE:-tavernlab-deb-build:22.04}
base_image=${TAVERNLAB_DEB_BASE_IMAGE:-ubuntu:22.04}
docker_network=${TAVERNLAB_DOCKER_NETWORK:-host}
docker_platform=${TAVERNLAB_DEB_PLATFORM:-linux/amd64}

# APT expects lowercase proxy names; callers often configure uppercase names.
export http_proxy="${http_proxy:-${HTTP_PROXY:-}}"
export https_proxy="${https_proxy:-${HTTPS_PROXY:-}}"
export no_proxy="${no_proxy:-${NO_PROXY:-}}"

if ! command -v docker >/dev/null 2>&1; then
    printf '%s\n' 'Docker is required for the Ubuntu 22.04 package builder.' >&2
    exit 1
fi

for xml in \
    "$repo_root/fireplace/cards/CardDefs.xml" \
    "$repo_root/fireplace/cards/Scholomance.xml"; do
    if [ ! -s "$xml" ] || grep -q '^version https://git-lfs.github.com/spec/v1$' "$xml"; then
        printf 'Card data is missing or still a Git LFS pointer: %s\n' "$xml" >&2
        exit 1
    fi
    if ! head -n 1 "$xml" | grep -q '^<?xml'; then
        printf 'Card data is not an XML document: %s\n' "$xml" >&2
        exit 1
    fi
done

if [ ! -f "$manifest" ]; then
    printf 'Source manifest is missing: %s\n' "$manifest" >&2
    exit 1
fi

stage=$(mktemp -d "${TMPDIR:-/tmp}/tavernlab-deb-stage.XXXXXXXX")
cleanup() {
    rm -rf -- "$stage"
}
trap cleanup EXIT

copy_one() {
    local relative=$1
    local source="$repo_root/$relative"
    local destination="$stage/$relative"

    if [ -d "$source" ]; then
        while IFS= read -r -d '' file; do
            local file_relative=${file#"$repo_root/"}
            case "$file_relative" in
                */__pycache__/*|*.pyc|*.pyo)
                    continue
                    ;;
            esac
            mkdir -p -- "$(dirname -- "$stage/$file_relative")"
            cp -p -- "$file" "$stage/$file_relative"
        done < <(find "$source" -type f -print0)
        return
    fi

    if [ ! -f "$source" ]; then
        printf 'Manifest entry is missing: %s\n' "$relative" >&2
        exit 1
    fi
    mkdir -p -- "$(dirname -- "$destination")"
    cp -p -- "$source" "$destination"
}

while IFS= read -r entry || [ -n "$entry" ]; do
    case "$entry" in
        ''|\#*)
            continue
            ;;
    esac
    copy_one "$entry"
done < "$manifest"

mkdir -p -- "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)

proxy_args=()
runtime_proxy_args=()
for variable in \
    HTTP_PROXY HTTPS_PROXY FTP_PROXY NO_PROXY \
    http_proxy https_proxy ftp_proxy no_proxy; do
    if [ -n "${!variable:-}" ]; then
        # Docker reads the value from the client environment.  Passing only
        # the variable name avoids putting proxy credentials in the command
        # line or Dockerfile history.
        proxy_args+=(--build-arg "$variable")
        runtime_proxy_args+=(--env "$variable")
    fi
done

docker build \
    --platform "$docker_platform" \
    --network "$docker_network" \
    --build-arg "BASE_IMAGE=$base_image" \
    "${proxy_args[@]}" \
    --tag "$image" \
    --file "$stage/packaging/Dockerfile" \
    "$stage"

docker run --rm \
    --platform "$docker_platform" \
    --network "$docker_network" \
    --user "$(id -u):$(id -g)" \
    "${runtime_proxy_args[@]}" \
    --volume "$stage:/build/src" \
    --volume "$output_dir:/build/out" \
    --workdir /build/src \
    --entrypoint /bin/bash \
    "$image" \
    -ec '
        dpkg-buildpackage -us -uc -b
        found=0
        for artifact in /build/tavernlab_*.deb; do
            [ -f "$artifact" ] || continue
            output_temp=$(mktemp /build/out/.tavernlab.XXXXXXXX)
            cp -p "$artifact" "$output_temp"
            mv "$output_temp" "/build/out/${artifact##*/}"
            found=1
        done
        [ "$found" -eq 1 ]
    '

checksum_temp=$(mktemp "$output_dir/.SHA256SUMS.XXXXXXXX")
(
    cd -- "$output_dir"
    sha256sum -- tavernlab_*.deb
) > "$checksum_temp"
mv -- "$checksum_temp" "$output_dir/SHA256SUMS"

printf 'Debian package and SHA256SUMS written to %s\n' "$output_dir"
