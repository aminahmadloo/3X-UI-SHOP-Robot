#!/usr/bin/env bash
set -euo pipefail

# Downloads the two original 3X-UI EJS reference templates and applies
# ToonelVPN branding without touching the active 3x-ui service or port 2096.
# The templates are kept as reference/test assets; native 3x-ui uses Go templates.

BASE="/opt/toonelvpn-sub-templates"
AYVPN="$BASE/AyVPN"
SHAMMAY="$BASE/shammay"
BACKUP="$BASE/backups/$(date +%Y%m%d-%H%M%S)"

mkdir -p "$AYVPN" "$SHAMMAY" "$BACKUP"

backup_if_exists() {
  local f="$1"
  if [[ -f "$f" ]]; then
    cp -a "$f" "$BACKUP/$(basename "$f")"
  fi
}

install_template() {
  local name="$1"
  local url="$2"
  local dest="$3"

  backup_if_exists "$dest"
  curl -fsSL "$url" -o "$dest.tmp"

  # ToonelVPN branding. These replacements are intentionally limited to
  # visible/vendor branding and support links; no EJS logic is modified.
  perl -0pi -e 's/shammay\.ir/elfuu.ir/g; s/Shammay/ToonelVPN/g; s/shammay/ToonelVPN/g; s/Ay\s*VPN/ToonelVPN/g; s/Ay_VPN/ToonelVpn_bot/g; s/DVHOST_CLOUD/ToonelVPN/g; s/dvhost_cloud/ToonelVpn_bot/g; s/ios\.v4b\.top/elfuu\.ir/g' "$dest.tmp"

  mv "$dest.tmp" "$dest"
  chmod 0644 "$dest"
  echo "[OK] $name -> $dest"
}

install_template \
  "ToonelVPN-AyVPN" \
  "https://raw.githubusercontent.com/shammay-PC/3XUI-Subscription/master/views/templates/AyVPN/sub.ejs" \
  "$AYVPN/sub.ejs"

install_template \
  "ToonelVPN-Shammay" \
  "https://raw.githubusercontent.com/shammay-PC/3XUI-Subscription/master/views/templates/shammay/sub.ejs" \
  "$SHAMMAY/sub.ejs"

cat > "$BASE/README.txt" <<'EOF'
ToonelVPN reference subscription templates

This directory contains personalized copies of the two upstream EJS templates:
  - AyVPN -> ToonelVPN-AyVPN
  - shammay -> ToonelVPN-Shammay

They are NOT installed into /etc/3x-ui/sub_templates because native 3x-ui
expects Go html/template files there. These EJS templates are preserved here
for visual/reference testing before the final native ToonelVPN template is built.

Active 3x-ui port 2096 is intentionally untouched by this script.
EOF

echo
printf '%s\n' '===== ToonelVPN reference templates installed ====='
ls -lh "$AYVPN/sub.ejs" "$SHAMMAY/sub.ejs"
printf '%s\n' "Backup: $BACKUP"
