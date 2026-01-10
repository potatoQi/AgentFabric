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
#   ALLOW_DIRTY=1 bash scripts/publish_pypi.sh pypi

REPO="${1:-}"
if [[ "$REPO" != "pypi" && "$REPO" != "testpypi" ]]; then
  echo "Usage: $0 <pypi|testpypi>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

load_twine_from_dotenv() {
  local dotenv="$ROOT/.env"
  [[ -f "$dotenv" ]] || return 0

  # Parse only TWINE_USERNAME / TWINE_PASSWORD lines in KEY=VALUE form.
  # Supports optional single/double quotes and ignores blank lines/comments.
  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line//[[:space:]]/}" ]] && continue
    [[ "${line#\#}" != "$line" ]] && continue
    [[ "$line" != *"="* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    value="${value#${value%%[![:space:]]*}}"
    value="${value%${value##*[![:space:]]}}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"

    case "$key" in
      TWINE_USERNAME)
        if [[ -z "${TWINE_USERNAME:-}" && -n "$value" ]]; then
          export TWINE_USERNAME="$value"
        fi
        ;;
      TWINE_PASSWORD)
        if [[ -z "${TWINE_PASSWORD:-}" && -n "$value" ]]; then
          export TWINE_PASSWORD="$value"
        fi
        ;;
    esac
  done < "$dotenv"

  # Reasonable default when using PyPI API tokens.
  if [[ -z "${TWINE_USERNAME:-}" && -n "${TWINE_PASSWORD:-}" ]]; then
    export TWINE_USERNAME="__token__"
  fi
}

load_twine_from_dotenv

# In DRY_RUN mode we only build + check; uploading is skipped.
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  if [[ -z "${TWINE_USERNAME:-}" || -z "${TWINE_PASSWORD:-}" ]]; then
    echo "Missing TWINE_USERNAME/TWINE_PASSWORD. Use an API token:" >&2
    echo "  export TWINE_USERNAME=__token__" >&2
    echo "  export TWINE_PASSWORD=<your-token>" >&2
    echo "Or put them in $ROOT/.env as KEY=VALUE (TWINE_USERNAME/TWINE_PASSWORD)." >&2
    exit 2
  fi
fi

if command -v git >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain)" ]]; then
    if [[ "${ALLOW_DIRTY:-0}" == "1" ]]; then
      echo "Working tree is not clean (ALLOW_DIRTY=1 set); continuing." >&2
    else
      echo "Working tree is not clean. Commit/stash before publishing, or set ALLOW_DIRTY=1." >&2
      exit 2
    fi
  fi
fi

echo "Syncing dev deps (build/twine)…" >&2
uv sync --dev --locked

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
