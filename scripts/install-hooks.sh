#!/usr/bin/env bash
# Install ArborDocs git hooks (pre-commit).
# Usage: sh scripts/install-hooks.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
HOOKS_DIR="$ROOT/.githooks"

mkdir -p "$HOOKS_DIR"
cp "$ROOT/scripts/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit" "$ROOT/scripts/pre-commit" "$ROOT/scripts/install-hooks.sh"

git -C "$ROOT" config core.hooksPath .githooks

echo "Installed git hooks → core.hooksPath=.githooks"
echo "Pre-commit script: .githooks/pre-commit"
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "Note: install gitleaks for staged secret scanning (optional but recommended)."
fi
