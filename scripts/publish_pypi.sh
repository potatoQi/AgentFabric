#!/usr/bin/env bash
set -euo pipefail

# Publish AgentFabric to PyPI/TestPyPI.
#
# Prereqs:
#   - Have an account on PyPI/TestPyPI
#   - Create an API token
#   - Export TWINE_USERNAME=__token__
#   - Export TWINE_PASSWORD=<pypi-token>
#
# Usage:
#   bash scripts/publish_pypi.sh testpypi
#   bash scripts/publish_pypi.sh pypi
#
# Optional:
#   DRY_RUN=1 bash scripts/publish_pypi.sh pypi

REPO="${1:-}"
if [[ "$REPO" != "pypi" && "$REPO" != "testpypi" ]]; then
  echo "Usage: $0 <pypi|testpypi>" >&2
  exit 2
fi

if [[ -z "${TWINE_USERNAME:-}" || -z "${TWINE_PASSWORD:-}" ]]; then
  echo "Missing TWINE_USERNAME/TWINE_PASSWORD. Use an API token:" >&2
  echo "  export TWINE_USERNAME=__token__" >&2
  echo "  export TWINE_PASSWORD=<your-token>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if command -v git >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree is not clean. Commit/stash before publishing." >&2
    exit 2
  fi
fi

echo "Syncing dev deps (build/twine)…" >&2
uv sync --dev

rm -rf dist

echo "Building sdist + wheel…" >&2
uv run python -m build

echo "Checking dist metadata…" >&2
uv run twine check dist/*

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN=1 set; skipping upload." >&2
  ls -lh dist
  exit 0
fi

if [[ "$REPO" == "testpypi" ]]; then
  echo "Uploading to TestPyPI…" >&2
  uv run twine upload --repository testpypi dist/*
else
  echo "Uploading to PyPI…" >&2
  uv run twine upload dist/*
fi

echo "Done." >&2
