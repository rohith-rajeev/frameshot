#!/usr/bin/env bash
# Assemble the per-OS release bundle: wheel + docs + scripts + extension.
# Usage: bash scripts/make-release-bundle.sh <version> <linux|macos>
set -euo pipefail
VERSION="$1"
OS_LABEL="$2"
cd "$(dirname "$0")/.."

WHEEL=(dist/*.whl)
if [ ! -f "${WHEEL[0]}" ]; then
  echo "No wheel in dist/ — run 'python -m build' first." >&2
  exit 1
fi

STAGE="$(mktemp -d)/frameshot-${VERSION}"
mkdir -p "$STAGE"
cp dist/*.whl "$STAGE/"
cp README.md LICENSE pyproject.toml "$STAGE/"
cp -r scripts shell-extension assets "$STAGE/"
if [ "$OS_LABEL" = "macos" ]; then
  cat > "$STAGE/README.macos.txt" <<'EOF'
frameshot on macOS (experimental)
============================
Capture uses Qt's screen grab (allow Screen Recording for your terminal
when prompted); overlay, annotation, OCR and clipboard are fully working.
Install: pip install frameshot-<ver>-py3-none-any.whl  (then run `frameshot`)
The GNOME Shell extension and .desktop hotkey setup are Linux-only.
EOF
  sed -i '' "s/frameshot-<ver>/frameshot-${VERSION}/" "$STAGE/README.macos.txt" 2>/dev/null \
    || sed -i "s/frameshot-<ver>/frameshot-${VERSION}/" "$STAGE/README.macos.txt"
fi
mkdir -p dist
tar -czf "dist/frameshot-${VERSION}-${OS_LABEL}.tar.gz" -C "$(dirname "$STAGE")" \
  "$(basename "$STAGE")"
echo "wrote dist/frameshot-${VERSION}-${OS_LABEL}.tar.gz"
