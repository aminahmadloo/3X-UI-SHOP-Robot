#!/usr/bin/env bash
# ToonelVPN Production Installer
# Installs the current repository on a fresh Ubuntu VPS, configures Docker,
# Nginx, Let's Encrypt, .env and optional payment gateways, then health-checks it.
set -Eeuo pipefail

REPO="aminahmadloo/ToonelVpn"
REF="${TOONELVPN_REF:-main}"
PROJECT_DIR="/opt/toonelvpn"
ARCHIVE="/tmp/toonelvpn-install-$$.tar.gz"
EXTRACT_DIR="/tmp/toonelvpn-install-$$"
ENV_FILE="$PROJECT_DIR/.env"
NGINX_SITE="/etc/nginx/sites-available/toonelvpn"
NGINX_ENABLED="/etc/nginx/sites-enabled/toonelvpn"
ACME_ROOT="/var/www/toonelvpn-acme"

cleanup() {
  rm -rf "$EXTRACT_DIR" "$ARCHIVE" 2>/dev/null || true
}
trap cleanup EXIT

fail() {
  echo
  echo "❌ $*" >&2
  exit 1
}

step() { echo; echo "▶ $*"; }
ok() { echo "✅ $*"; }

require_root() {
  [[ "$(id -u)" -eq 0 ]] || fail "این Installer باید با root اجرا شود."
}

check_os() {
  [[ -f /etc/os-release ]] || fail "سیستم‌عامل قابل تشخیص نیست."
  . /etc/os-release
  [[ "$ID" == "ubuntu" ]] || fail "فقط Ubuntu پشتیبانی می‌شود. نسخه فعلی: $ID $VERSION_ID"
  case "$VERSION_ID" in
    22.04|24.04|26.04) ;;
    *) fail "نسخه Ubuntu پشتیبانی‌شده نیست: $VERSION_ID (پیشنهاد: 24.04 LTS)" ;;
  esac
  case "$(dpkg --print-architecture)" in
    amd64|arm64) ;;
    *) fail "معماری پشتیبانی‌شده نیست: $(dpkg --print-architecture)" ;;
  esac
}

prompt_required() {
  local var="$1" label="$2" value
  while :; do
    read -r -p "$label: " value
    [[ -n "$value" ]] && { printf -v "$var" '%s' "$value"; return; }
    echo "این مقدار الزامی است."
  done
}

prompt_secret_required() {
  local var="$1" label="$2" value
  while :; do
    read -r -s -p "$label: " value
    echo
    [[ -n "$value" ]] && { printf -v "$var" '%s' "$value"; return; }
    echo "این مقدار الزامی است."
  done
}

prompt_optional() {
  local var="$1" label="$2" default="${3:-}" value
  if [[ -n "$default" ]]; then
    read -r -p "$label [$default]: " value
    value="${value:-$default}"
  else
    read -r -p "$label [Enter = رد کردن]: " value
  fi
  printf -v "$var" '%s' "$value"
}

prompt_secret_optional() {
  local var="$1" label="$2" value
  read -r -s -p "$label [Enter = رد کردن]: " value
  echo
  printf -v "$var" '%s' "$value"
}

prompt_yes_no() {
  local var="$1" label="$2" default="${3:-N}" value
  read -r -p "$label [y/N]: " value
  value="${value:-$default}"
  case "${value,,}" in
    y|yes) printf -v "$var" '%s' "true" ;;
    *) printf -v "$var" '%s' "false" ;;
  esac
}

validate_domain() {
  [[ "$BOT_DOMAIN" != *"/"* ]] || fail "BOT_DOMAIN فقط باید hostname باشد، بدون http:// یا /."
  [[ "$BOT_DOMAIN" == *.* ]] || fail "BOT_DOMAIN معتبر به نظر نمی‌رسد."
}

check_ports() {
  local busy
  for port in 80 443; do
    busy="$(ss -ltnH "( sport = :$port )" 2>/dev/null || true)"
    if [[ -n "$busy" ]]; then
      echo "⚠️ پورت $port در حال حاضر در حال استفاده است:"
      echo "$busy"
      fail "برای نصب تمیز، پورت $port باید آزاد باشد."
    fi
  done
}

check_dns() {
  step "بررسی DNS دامنه"
  local ips
  ips="$(getent ahostsv4 "$BOT_DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u || true)"
  [[ -n "$ips" ]] || fail "دامنه $BOT_DOMAIN به IP resolve نمی‌شود. ابتدا DNS را به IP همین سرور وصل کنید."
  echo "Resolved IP(s): $ips"
  ok "DNS قابل resolve است."
}

install_base_packages() {
  step "نصب وابستگی‌های سیستم"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg nginx snapd tar openssl
  systemctl enable --now nginx
  systemctl enable --now snapd.socket || true
  ok "وابستگی‌های سیستم نصب شدند."
}

install_docker() {
  step "نصب Docker Engine و Compose Plugin"
  if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  systemctl enable --now docker
  docker version >/dev/null
  docker compose version >/dev/null
  ok "Docker آماده است."
}

download_repo() {
  step "دریافت نسخه $REF از GitHub"
  [[ -n "${GH_TOKEN:-}" ]] || fail "این Repository خصوصی است. GH_TOKEN با دسترسی Contents: Read لازم است."
  rm -rf "$EXTRACT_DIR" "$ARCHIVE"
  mkdir -p "$EXTRACT_DIR"
  curl -fsSL -L     -H "Accept: application/vnd.github+json"     -H "Authorization: Bearer $GH_TOKEN"     -H "X-GitHub-Api-Version: 2026-03-10"     "https://api.github.com/repos/$REPO/tarball/$REF"     -o "$ARCHIVE"
  tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR"
  local root
  root="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n1)"
  [[ -d "$root" ]] || fail "Archive GitHub معتبر نیست."
  [[ -f "$root/docker-compose.yml" ]] || fail "docker-compose.yml در نسخه دریافت‌شده پیدا نشد."
  rm -rf "$PROJECT_DIR"
  mkdir -p "$PROJECT_DIR"
  cp -a "$root/." "$PROJECT_DIR/"
  ok "کد ToonelVPN دریافت شد."
}

collect_configuration() {
  step "مرحله ۱/۳ — اطلاعات کاملاً ضروری"
  echo "این موارد بدون آنها ربات بالا نمی‌آید."
  prompt_secret_required BOT_TOKEN "Telegram Bot Token"
  prompt_required BOT_DOMAIN "دامنه ربات (مثلاً bot.example.com)"
  prompt_required BOT_DEV_ID "Telegram Developer ID"
  prompt_required BOT_SUPPORT_ID "Telegram Support ID"
  prompt_required XUI_USERNAME "3X-UI Username"
  prompt_secret_required XUI_PASSWORD "3X-UI Password"
  prompt_required LETSENCRYPT_EMAIL "Email برای Let's Encrypt"
  validate_domain

  step "مرحله ۲/۳ — تنظیمات مفید (اختیاری)"
  prompt_optional BOT_ADMINS "Admin IDs، با کاما جدا شوند" "$BOT_DEV_ID"
  prompt_optional SHOP_CARD_NUMBER "شماره کارت شارژ دستی" ""
  prompt_optional SHOP_EMAIL "ایمیل فروشگاه" "support@$BOT_DOMAIN"
  prompt_optional SHOP_CURRENCY "واحد پول" "IRT"
  prompt_optional XUI_TOKEN "3X-UI Token" ""
  prompt_optional XUI_SUBSCRIPTION_PORT "Subscription Port" "2096"
  prompt_optional XUI_SUBSCRIPTION_PATH "Subscription Path" "/user/"
  prompt_yes_no SHOP_TRIAL_ENABLED "فعال بودن Trial" "Y"

  step "مرحله ۳/۳ — درگاه‌ها (اختیاری؛ Enter = رد کردن)"
  echo "هر درگاه را بعداً هم می‌توان از .env تنظیم کرد."
  prompt_secret_optional ZARINPAL_MERCHANT_ID "ZarinPal Merchant ID"
  prompt_optional ZARINPAL_PAYMENT_BASE_URL "ZarinPal Payment Base URL" "https://payment.$BOT_DOMAIN"

  prompt_secret_optional ABAN_GATEWAY_TOKEN "AbanGateway Token"
  if [[ -n "$ABAN_GATEWAY_TOKEN" ]]; then
    prompt_secret_required ABAN_GATEWAY_WEBHOOK_SECRET "AbanGateway Webhook Secret"
  else
    ABAN_GATEWAY_WEBHOOK_SECRET=""
  fi

  prompt_secret_optional BLUPAL_API_KEY "BluPal API Key"
  prompt_secret_optional WINAPAY_MERCHANT_ID "Winapay Merchant ID"

  prompt_secret_optional OPENAI_API_KEY "OpenAI API Key"
  prompt_yes_no FULL_BACKUP_STORAGE_ENABLED "فعال‌سازی Full Backup Storage (B2)" "N"

  if [[ "$FULL_BACKUP_STORAGE_ENABLED" == "true" ]]; then
    prompt_optional FULL_BACKUP_STORAGE_ENDPOINT "B2 S3 Endpoint" "https://s3.us-west-004.backblazeb2.com"
    prompt_required FULL_BACKUP_STORAGE_BUCKET "B2 Bucket"
    prompt_secret_required FULL_BACKUP_STORAGE_ACCESS_KEY_ID "B2 Access Key ID"
    prompt_secret_required FULL_BACKUP_STORAGE_SECRET_ACCESS_KEY "B2 Secret Access Key"
    prompt_optional FULL_BACKUP_STORAGE_REGION "B2 Region" "us-west-004"
  fi
}

write_env() {
  step "ساخت .env با permission 600"
  install -m 600 /dev/null "$ENV_FILE"
  {
    printf 'BOT_TOKEN=%q\n' "$BOT_TOKEN"
    printf 'BOT_ADMINS=%q\n' "$BOT_ADMINS"
    printf 'BOT_DEV_ID=%q\n' "$BOT_DEV_ID"
    printf 'BOT_SUPPORT_ID=%q\n' "$BOT_SUPPORT_ID"
    printf 'BOT_DOMAIN=%q\n' "$BOT_DOMAIN"
    printf 'BOT_PORT=8080\n'
    printf 'XUI_USERNAME=%q\n' "$XUI_USERNAME"
    printf 'XUI_PASSWORD=%q\n' "$XUI_PASSWORD"
    [[ -n "$XUI_TOKEN" ]] && printf 'XUI_TOKEN=%q\n' "$XUI_TOKEN"
    printf 'XUI_SUBSCRIPTION_PORT=%q\n' "$XUI_SUBSCRIPTION_PORT"
    printf 'XUI_SUBSCRIPTION_PATH=%q\n' "$XUI_SUBSCRIPTION_PATH"
    printf 'LETSENCRYPT_EMAIL=%q\n' "$LETSENCRYPT_EMAIL"
    printf 'SHOP_TRIAL_ENABLED=%q\n' "$SHOP_TRIAL_ENABLED"
    [[ -n "$SHOP_CARD_NUMBER" ]] && printf 'SHOP_CARD_NUMBER=%q\n' "$SHOP_CARD_NUMBER"
    [[ -n "$SHOP_EMAIL" ]] && printf 'SHOP_EMAIL=%q\n' "$SHOP_EMAIL"
    [[ -n "$SHOP_CURRENCY" ]] && printf 'SHOP_CURRENCY=%q\n' "$SHOP_CURRENCY"

    if [[ -n "$ZARINPAL_MERCHANT_ID" ]]; then
      printf 'ZARINPAL_MERCHANT_ID=%q\n' "$ZARINPAL_MERCHANT_ID"
      printf 'SHOP_PAYMENT_ZARINPAL_ENABLED=true\n'
      printf 'ZARINPAL_PAYMENT_BASE_URL=%q\n' "$ZARINPAL_PAYMENT_BASE_URL"
    else
      printf 'SHOP_PAYMENT_ZARINPAL_ENABLED=false\n'
    fi

    [[ -n "$ABAN_GATEWAY_TOKEN" ]] && printf 'ABAN_GATEWAY_TOKEN=%q\n' "$ABAN_GATEWAY_TOKEN"
    [[ -n "$ABAN_GATEWAY_WEBHOOK_SECRET" ]] && printf 'ABAN_GATEWAY_WEBHOOK_SECRET=%q\n' "$ABAN_GATEWAY_WEBHOOK_SECRET"
    [[ -n "$BLUPAL_API_KEY" ]] && printf 'BLUPAL_API_KEY=%q\n' "$BLUPAL_API_KEY"
    [[ -n "$WINAPAY_MERCHANT_ID" ]] && printf 'WINAPAY_MERCHANT_ID=%q\n' "$WINAPAY_MERCHANT_ID"
    [[ -n "$OPENAI_API_KEY" ]] && printf 'OPENAI_API_KEY=%q\n' "$OPENAI_API_KEY"

    printf 'FULL_BACKUP_STORAGE_ENABLED=%q\n' "$FULL_BACKUP_STORAGE_ENABLED"
    if [[ "$FULL_BACKUP_STORAGE_ENABLED" == "true" ]]; then
      printf 'FULL_BACKUP_STORAGE_ENDPOINT=%q\n' "$FULL_BACKUP_STORAGE_ENDPOINT"
      printf 'FULL_BACKUP_STORAGE_BUCKET=%q\n' "$FULL_BACKUP_STORAGE_BUCKET"
      printf 'FULL_BACKUP_STORAGE_ACCESS_KEY_ID=%q\n' "$FULL_BACKUP_STORAGE_ACCESS_KEY_ID"
      printf 'FULL_BACKUP_STORAGE_SECRET_ACCESS_KEY=%q\n' "$FULL_BACKUP_STORAGE_SECRET_ACCESS_KEY"
      printf 'FULL_BACKUP_STORAGE_REGION=%q\n' "$FULL_BACKUP_STORAGE_REGION"
    fi
  } >"$ENV_FILE"

  chmod 600 "$ENV_FILE"
  ok ".env ساخته شد."
}

prepare_runtime() {
  step "آماده‌سازی plans و Runtime"
  [[ -f "$PROJECT_DIR/plans.json" ]] || cp "$PROJECT_DIR/plans.example.json" "$PROJECT_DIR/plans.json"
  mkdir -p "$PROJECT_DIR/app/data" "$PROJECT_DIR/app/logs" "$PROJECT_DIR/app/locales"
  chmod 600 "$PROJECT_DIR/plans.json"
  ok "Runtime directories آماده شدند."
}

configure_nginx() {
  step "تنظیم Nginx برای $BOT_DOMAIN"
  mkdir -p "$ACME_ROOT/.well-known/acme-challenge"
  cat >"$NGINX_SITE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $BOT_DOMAIN;

    location /.well-known/acme-challenge/ {
        root $ACME_ROOT;
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF
  ln -sfn "$NGINX_SITE" "$NGINX_ENABLED"
  nginx -t
  systemctl reload nginx
  ok "Nginx روی پورت 80 آماده است."
}

install_ssl() {
  step "دریافت SSL از Let's Encrypt"
  if ! command -v certbot >/dev/null 2>&1; then
    snap install --classic certbot
    ln -sfn /snap/bin/certbot /usr/local/bin/certbot
  fi

  certbot --nginx     --non-interactive     --agree-tos     --email "$LETSENCRYPT_EMAIL"     --redirect     -d "$BOT_DOMAIN"

  certbot renew --dry-run
  ok "SSL نصب و تمدید خودکار بررسی شد."
}

start_bot() {
  step "Build و اجرای ToonelVPN"
  cd "$PROJECT_DIR"
  docker compose config >/dev/null
  docker compose build
  docker compose up -d
  ok "Containerها اجرا شدند."
}

health_check() {
  step "Health Check"
  cd "$PROJECT_DIR"

  local i
  for i in {1..30}; do
    if docker inspect -f '{{.State.Running}}' 3xui-shop-bot 2>/dev/null | grep -q true; then
      break
    fi
    sleep 2
  done

  docker compose ps
  if ! docker inspect -f '{{.State.Running}}' 3xui-shop-bot 2>/dev/null | grep -q true; then
    echo
    docker compose logs --tail=100 bot
    fail "Bot container بالا نمانده است."
  fi

  curl -fsS --max-time 10 "https://$BOT_DOMAIN/webhook" >/dev/null || {
    echo "⚠️ HTTPS endpoint check failed. آخرین لاگ Bot:"
    docker compose logs --tail=60 bot
    fail "Health check وب ناموفق بود."
  }

  ok "Bot container و HTTPS endpoint سالم هستند."
}

print_summary() {
  echo
  echo "════════════════════════════════════════════════════════════"
  echo "🎉 ToonelVPN installation completed"
  echo "════════════════════════════════════════════════════════════"
  echo "Project : $PROJECT_DIR"
  echo "Domain  : https://$BOT_DOMAIN"
  echo "Webhook : https://$BOT_DOMAIN/webhook"
  echo "Env     : $ENV_FILE"
  echo
  echo "دستورهای مفید:"
  echo "  cd $PROJECT_DIR"
  echo "  docker compose ps"
  echo "  docker compose logs -f bot"
  echo "  docker compose restart bot"
  echo
  echo "⚠️ plans.json فعلاً از plans.example.json ساخته شده؛ قیمت‌های واقعی را قبل از فروش بررسی کنید."
  echo "════════════════════════════════════════════════════════════"
}

main() {
  require_root
  check_os

  if [[ -e "$PROJECT_DIR" ]]; then
    fail "$PROJECT_DIR از قبل وجود دارد. Installer عمداً روی نصب قبلی overwrite نمی‌کند."
  fi

  step "بررسی اولیه"
  check_ports
  check_dns

  collect_configuration
  install_base_packages
  install_docker
  download_repo
  write_env
  prepare_runtime
  configure_nginx
  install_ssl
  start_bot
  health_check
  print_summary
}

main "$@"
