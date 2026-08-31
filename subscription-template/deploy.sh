#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/etc/3x-ui/sub_templates/toonelvpn"
SRC="${SRC_DIR}/index.html"
OUT="${DEST}/index.html"

mkdir -p "$DEST"

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: template not found: $SRC" >&2
  exit 1
fi

cp "$SRC" "$OUT"

chmod 0644 "$OUT"

echo "Template deployed: $OUT"
ls -lh "$OUT"
