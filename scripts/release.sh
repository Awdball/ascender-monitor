#!/usr/bin/env bash
set -euo pipefail

# Ascender Monitor Release Helper
# Usage: ./scripts/release.sh 1.2.0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ $# -lt 1 ]; then
    echo "Error: Version number required."
    echo "Usage: $0 <version> (e.g. $0 1.2.0)"
    exit 1
fi

RAW_VERSION="$1"
# Strip leading 'v' if provided
VERSION="${RAW_VERSION#v}"
TAG_NAME="v${VERSION}"

# Validate 3-part SemVer format (e.g. 1.2.0)
if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version '${VERSION}' must be in SemVer format (e.g. 1.2.0 or 1.10.0)"
    exit 1
fi

echo "==> Preparing release ${TAG_NAME}..."

# Update app/__version__.py
VERSION_FILE="${ROOT_DIR}/app/__version__.py"
echo "__version__ = \"${VERSION}\"" > "${VERSION_FILE}"
echo "--> Updated ${VERSION_FILE} to ${VERSION}"

# Stage and commit
git -C "${ROOT_DIR}" add app/__version__.py
if ! git -C "${ROOT_DIR}" diff --cached --quiet; then
    git -C "${ROOT_DIR}" commit -m "chore: release ${TAG_NAME}"
fi

# Create annotated tag
echo "--> Creating git tag ${TAG_NAME}..."
git -C "${ROOT_DIR}" tag -a "${TAG_NAME}" -m "Release ${TAG_NAME}"

# Push commit and tag to origin
echo "--> Pushing to origin main and tag ${TAG_NAME}..."
git -C "${ROOT_DIR}" push origin main
git -C "${ROOT_DIR}" push origin "${TAG_NAME}"

echo ""
echo "✅ Successfully released and pushed ${TAG_NAME}!"
echo "GitHub Actions workflow will now build and publish ghcr.io/awdball/ascender-monitor:${VERSION}"
