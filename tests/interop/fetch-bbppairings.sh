#!/usr/bin/env bash
# Fetch and checksum-verify the pinned bbpPairings v6.0.0 Linux release, and
# extract its binary to tests/interop/bin/bbpPairings.exe.
#
# See PLAN-REGRESSION.md section 2.1 for where these values come from, and
# section 8 for how this script is used (the same script both local Docker
# iteration and CI call, so the two cannot drift). This is a thin, pinned call
# into fetch-engine-binary.sh, which is the general-purpose form used to fetch
# an arbitrary engine binary (e.g. from the interop-sweep GitHub Action's
# workflow_dispatch URL input) -- see that script for the generic path.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VERSION="v6.0.0"
URL="https://github.com/BieremaBoyzProgramming/bbpPairings/releases/download/${VERSION}/bbpPairings-${VERSION}-x86_64-pc-linux.tar.gz"
TARBALL_SHA256="bffd2d5a4dc9d86eb3d9886339e8ca446d88683f77559f0889ea0d2040e7d827"
BINARY_SHA256="81904eae52e5345e96344e4fd2ffd4f317497edf568dadff69b50e5844ad7c51"
ARCHIVE_BINARY_PATH="bbpPairings-${VERSION}/bbpPairings.exe"
DEST="${SCRIPT_DIR}/bin/bbpPairings.exe"

"${SCRIPT_DIR}/fetch-engine-binary.sh" \
    --url "${URL}" \
    --sha256 "${TARBALL_SHA256}" \
    --path-in-archive "${ARCHIVE_BINARY_PATH}" \
    --out "${DEST}"

# Belt-and-suspenders: the tarball hash above already guarantees a
# byte-identical extraction, but this is the one binary this repo pins by
# name, so it gets a second, independent check against the binary's own
# published hash too.
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}
ACTUAL="$(sha256_of "${DEST}")"
if [ "${ACTUAL}" != "${BINARY_SHA256}" ]; then
    echo "fetch-bbppairings.sh: installed binary SHA-256 mismatch" >&2
    echo "  expected ${BINARY_SHA256}" >&2
    echo "  got      ${ACTUAL}" >&2
    exit 1
fi
