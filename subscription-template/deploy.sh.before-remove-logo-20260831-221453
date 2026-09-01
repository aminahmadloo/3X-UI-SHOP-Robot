#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/etc/3x-ui/sub_templates/toonelvpn"
LOGO="${DEST}/logo.png"
SRC="${SRC_DIR}/index.html"
OUT="${DEST}/index.html"

mkdir -p "$DEST"

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: template not found: $SRC" >&2
  exit 1
fi

if [[ ! -f "$LOGO" ]]; then
  echo "ERROR: ToonelVPN logo not found: $LOGO" >&2
  echo "Copy the real logo to that path first." >&2
  exit 1
fi

python3 - "$SRC" "$OUT" "$LOGO" <<'PY'
import base64
import pathlib
import sys

src, out, logo = map(pathlib.Path, sys.argv[1:])
html = src.read_text(encoding="utf-8")
data = base64.b64encode(logo.read_bytes()).decode("ascii")
needle = "__TOONELVPN_LOGO_BASE64__"
if needle not in html:
    raise SystemExit("ERROR: logo placeholder is missing from index.html")
html = html.replace(needle, data)
pathlib.Path(out).write_text(html, encoding="utf-8")
PY

chmod 0644 "$OUT" "$LOGO"

echo "Template deployed: $OUT"
echo "Logo embedded from: $LOGO"
ls -lh "$OUT" "$LOGO"
