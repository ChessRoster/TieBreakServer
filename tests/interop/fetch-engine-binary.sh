#!/usr/bin/env bash
# Fetch a comparison-engine binary from an arbitrary public URL and install it
# to tests/interop/bin/<name>, for pointing the interop sweep at something
# other than the pinned bbpPairings release -- see PLAN-REGRESSION.md section
# 6.1: the Engine protocol is what makes a second engine "a module plus a
# registry line, not a rewrite," and this script is the binary-provisioning
# half of that for anything fetched over HTTP rather than vendored.
#
# fetch-bbppairings.sh is a thin, pinned call into this script and is what
# local iteration and CI both use for the one engine this repo knows about by
# name; this script is what the interop-sweep GitHub Action uses to fetch
# WHATEVER binary a run was dispatched with.
#
# Usage:
#   fetch-engine-binary.sh --url URL [--sha256 HEX] [--path-in-archive PATH]
#                           [--out PATH] [--name NAME]
#
#   --url URL             Required. Downloaded as-is. A .tar.gz/.tgz is
#                          extracted; anything else is installed as the binary
#                          directly.
#   --sha256 HEX          Optional. Verified against the downloaded file (the
#                          archive itself if URL is an archive, the binary
#                          directly otherwise). Skipped with a warning if
#                          omitted -- callers that need a supply-chain
#                          guarantee (this repo's own pinned bbpPairings build)
#                          must always pass this.
#   --path-in-archive PATH
#                          Required if URL is an archive containing more than
#                          one regular file: the path inside the archive to
#                          install. If the archive extracts to exactly one
#                          regular file, this is inferred and may be omitted.
#   --out PATH             Default: tests/interop/bin/<name>.
#   --name NAME            Default: the URL's basename with any archive
#                          extension stripped. Used only to name --out's
#                          default and in log output.
#
# Idempotent: if a file already exists at --out and --sha256 was given and
# matches the FINAL installed binary's hash from a prior run (recorded
# alongside it in <out>.sha256), this exits without downloading anything.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/bin"

URL=""
SHA256=""
PATH_IN_ARCHIVE=""
OUT=""
NAME=""

while [ $# -gt 0 ]; do
    case "$1" in
        --url) URL="$2"; shift 2 ;;
        --sha256) SHA256="$2"; shift 2 ;;
        --path-in-archive) PATH_IN_ARCHIVE="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        *) echo "fetch-engine-binary.sh: unrecognised argument: $1" >&2; exit 2 ;;
    esac
done

if [ -z "${URL}" ]; then
    echo "fetch-engine-binary.sh: --url is required" >&2
    exit 2
fi

BASENAME="$(basename "${URL}")"
IS_ARCHIVE=0
case "${BASENAME}" in
    *.tar.gz|*.tgz) IS_ARCHIVE=1 ;;
esac

if [ -z "${NAME}" ]; then
    NAME="${BASENAME%.tar.gz}"
    NAME="${NAME%.tgz}"
fi
if [ -z "${OUT}" ]; then
    OUT="${BIN_DIR}/${NAME}"
fi

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

# The stamp records exactly what produced the file at OUT -- the source URL
# plus whichever hash was actually checked (the archive's, or the raw
# binary's) -- so idempotency is "these are the same inputs", not a hash
# comparison across two different things (an archive's hash is not the
# installed binary's hash).
STAMP="${OUT}.fetch-stamp"
STAMP_VALUE="${URL}|${SHA256}|${PATH_IN_ARCHIVE}"
if [ -f "${OUT}" ] && [ -f "${STAMP}" ] && [ "$(cat "${STAMP}")" = "${STAMP_VALUE}" ]; then
    echo "fetch-engine-binary.sh: ${OUT} already present for these inputs, skipping fetch"
    exit 0
fi

mkdir -p "$(dirname "${OUT}")"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

DOWNLOADED="${WORKDIR}/download"
echo "fetch-engine-binary.sh: downloading ${URL}"
if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "${DOWNLOADED}" "${URL}"
else
    wget -q -O "${DOWNLOADED}" "${URL}"
fi

if [ "${IS_ARCHIVE}" = "1" ]; then
    if [ -n "${SHA256}" ]; then
        ACTUAL="$(sha256_of "${DOWNLOADED}")"
        if [ "${ACTUAL}" != "${SHA256}" ]; then
            echo "fetch-engine-binary.sh: archive SHA-256 mismatch" >&2
            echo "  expected ${SHA256}" >&2
            echo "  got      ${ACTUAL}" >&2
            exit 1
        fi
    else
        echo "fetch-engine-binary.sh: WARNING no --sha256 given, archive is unverified" >&2
    fi

    EXTRACT_DIR="${WORKDIR}/extracted"
    mkdir -p "${EXTRACT_DIR}"
    tar -xzf "${DOWNLOADED}" -C "${EXTRACT_DIR}"

    if [ -n "${PATH_IN_ARCHIVE}" ]; then
        SRC="${EXTRACT_DIR}/${PATH_IN_ARCHIVE}"
        if [ ! -f "${SRC}" ]; then
            echo "fetch-engine-binary.sh: ${PATH_IN_ARCHIVE} not found in archive" >&2
            exit 1
        fi
    else
        # Infer the binary: the only regular file in the extracted tree.
        mapfile -t CANDIDATES < <(find "${EXTRACT_DIR}" -type f)
        if [ "${#CANDIDATES[@]}" -eq 0 ]; then
            echo "fetch-engine-binary.sh: archive contains no files" >&2
            exit 1
        elif [ "${#CANDIDATES[@]}" -gt 1 ]; then
            echo "fetch-engine-binary.sh: archive contains multiple files, pass --path-in-archive:" >&2
            for c in "${CANDIDATES[@]}"; do echo "  ${c#${EXTRACT_DIR}/}" >&2; done
            exit 1
        fi
        SRC="${CANDIDATES[0]}"
    fi
    cp "${SRC}" "${OUT}"
else
    if [ -n "${SHA256}" ]; then
        ACTUAL="$(sha256_of "${DOWNLOADED}")"
        if [ "${ACTUAL}" != "${SHA256}" ]; then
            echo "fetch-engine-binary.sh: binary SHA-256 mismatch" >&2
            echo "  expected ${SHA256}" >&2
            echo "  got      ${ACTUAL}" >&2
            exit 1
        fi
    else
        echo "fetch-engine-binary.sh: WARNING no --sha256 given, binary is unverified" >&2
    fi
    cp "${DOWNLOADED}" "${OUT}"
fi

chmod +x "${OUT}"
echo "${STAMP_VALUE}" > "${STAMP}"
echo "fetch-engine-binary.sh: installed ${OUT} ($(sha256_of "${OUT}"))"
