#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${1:-/tmp/toonelvpn-repo}"
TARGET="/etc/3x-ui/sub_templates/toonelvpn"
SOURCE="$REPO_DIR/subscription-template/index.html"

if [[ ! -f "$SOURCE" ]]; then
  echo "ERROR: template not found: $SOURCE" >&2
  exit 1
fi

mkdir -p "$TARGET"

if [[ -f "$TARGET/index.html" ]]; then
  BACKUP="$TARGET/index.html.bak.$(date +%Y%m%d-%H%M%S)"
  cp -a "$TARGET/index.html" "$BACKUP"
  echo "Previous template backed up to: $BACKUP"
fi

install -m 0644 "$SOURCE" "$TARGET/index.html"

chown root:root "$TARGET/index.html"

printf '\nInstalled ToonelVPN subscription template:\n  %s\n' "$TARGET/index.html"
printf 'Set 3X-UI Sub Theme Directory to:\n  %s\n\n' "$TARGET/"

if systemctl is-active --quiet x-ui; then
  echo "x-ui service is running. No restart is required by the template itself."
else
  echo "WARNING: x-ui.service is not active."
fi
