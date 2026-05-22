#!/usr/bin/env bash
# Copies the artifacts the static Pages viewer needs into site/models/.
# Run from the repo root.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/site/models"

rm -rf "$DEST"
mkdir -p "$DEST"

for src in "$ROOT/models/"*/; do
  name="$(basename "$src")"
  mkdir -p "$DEST/$name/renders"
  # Hidden sidecar + GLB (used by the viewer)
  for f in "$src/."*.glb "$src/."*.step.js; do
    [ -f "$f" ] && cp "$f" "$DEST/$name/"
  done
  # Preview thumbnails for the landing page
  if [ -d "$src/renders" ]; then
    cp "$src/renders/"*.png "$DEST/$name/renders/" 2>/dev/null || true
    cp "$src/renders/"*.gif "$DEST/$name/renders/" 2>/dev/null || true
  fi
done

echo "Copied:"
ls -la "$DEST"
