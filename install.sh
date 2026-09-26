#!/usr/bin/env bash
#
# Автоустановка Telegram VPN Shop (бот + Mini App + веб-магазин + админка) на чистый
# сервер Ubuntu/Debian: системные зависимости, .env через интерактивные вопросы,
# systemd-сервисы для бота и веб-приложения, nginx как reverse proxy и Let's Encrypt
# сертификат через certbot.
#
# Использование:
#   git clone <ваш форк этого репозитория>
#   cd <папка проекта>
#   sudo bash install.sh
#
# Скрипт можно запускать повторно (например, чтобы поменять ответы и перегенерировать
# .env/сервисы/nginx) — он не создаёт дублирующихся системных сущностей.
set -euo pipefail

# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------
C_RESET="\033[0m"; C_BOLD="\033[1m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"; C_RED="\033[31m"; C_BLUE="\033[34m"

info()  { echo -e "${C_BLUE}==>${C_RESET} $*"; }
ok()    { echo -e "${C_GREEN}✔${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}⚠${C_RESET} $*"; }
err()   { echo -e "${C_RED}✘ $*${C_RESET}" >&2; }
die()   { err "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Проверки окружения
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  die "Запустите скрипт от root (sudo bash install.sh)"
fi

if ! command -v apt-get >/dev/null 2>&1; then
  die "Скрипт поддерживает только Debian/Ubuntu (нужен apt-get). Для других систем настройте сервисы вручную по README."
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
cd "$PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/requirements.txt" ] || [ ! -d "$PROJECT_DIR/webapp" ]; then
  die "Запускать install.sh нужно из корня проекта (не найден requirements.txt/webapp/)"
fi

echo -e "${C_BOLD}"
echo "======================================================================"
echo " Telegram VPN Shop — автоустановка"
echo "======================================================================"
echo -e "${C_RESET}"

# ---------------------------------------------------------------------------
# Вспомогательные функции для вопросов
# ---------------------------------------------------------------------------
ask() {
  # ask "Текст вопроса" "значение по умолчанию" -> печатает ответ в stdout
  local prompt="$1" default="${2:-}" answer
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " answer </dev/tty
    echo "${answer:-$default}"
  else
    read -r -p "$prompt: " answer </dev/tty
    echo "$answer"
  fi
}

ask_required() {
  local prompt="$1" default="${2:-}" answer
  while true; do
    answer="$(ask "$prompt" "$default")"
    if [ -n "$answer" ]; then echo "$answer"; return; fi
    err "Это поле обязательно"
  done
}

ask_secret() {
  local prompt="$1" answer
  read -r -s -p "$prompt: " answer </dev/tty
  echo >&2
  echo "$answer"
}

ask_yn() {
  # ask_yn "Вопрос" "y|n(по умолчанию)" -> "yes"/"no"
  local prompt="$1" default="${2:-n}" answer
  while true; do
    read -r -p "$prompt [$( [ "$default" = y ] && echo Y/n || echo y/N )]: " answer </dev/tty
    answer="${answer:-$default}"
    case "$answer" in
      y|Y|yes|Yes) echo yes; return ;;
      n|N|no|No) echo no; return ;;
      *) err "Ответьте y или n" ;;
    esac
  done
}

python_version_ok() {
  local py="$1"
  "$py" - <<'PY' 2>/dev/null
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
}

# ---------------------------------------------------------------------------
# 1. Системные зависимости
# ---------------------------------------------------------------------------
info "Обновляю списки пакетов и ставлю системные зависимости (python3, nginx, certbot, git, sqlite3)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-pip \
  nginx certbot python3-certbot-nginx \
  git curl sqlite3 openssl ca-certificates >/dev/null

PYTHON_BIN="$(command -v python3)"
if ! python_version_ok "$PYTHON_BIN"; then
  die "Нужен Python 3.10+, а в системе $($PYTHON_BIN --version). Обновите ОС (Ubuntu 22.04/24.04, Debian 12) и запустите заново."
fi
ok "Python: $($PYTHON_BIN --version)"

# ---------------------------------------------------------------------------
# 2. Интерактивные вопросы
# ---------------------------------------------------------------------------
ENV_FILE="$PROJECT_DIR/.env"
REUSE_ENV=no
if [ -f "$ENV_FILE" ]; then
  REUSE_ENV="$(ask_yn "Найден существующий .env — использовать его без вопросов (просто переустановить сервисы/nginx)?" n)"
fi

if [ "$REUSE_ENV" = "no" ]; then
  echo
  info "Основные настройки"
  DOMAIN="$(ask_required "Домен сайта (например, vpn.example.com, DNS A-запись должна уже указывать на этот сервер)")"
  LE_EMAIL="$(ask_required "Email для Let's Encrypt (уведомления об истечении сертификата)")"
  BOT_TOKEN="$(ask_required "Токен Telegram-бота (от @BotFather)")"

  echo
  info "Веб-админка (/admin)"
  ADMIN_USERNAME="$(ask "Логин администратора" "admin")"
  ADMIN_PASSWORD="$(ask_secret "Пароль администратора (не будет отображаться)")"
  if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-16)"
    warn "Пароль не введён — сгенерирован случайный: $ADMIN_PASSWORD (сохраните его!)"
  fi
  SECRET_KEY="$(openssl rand -hex 32)"

  echo
  info "Первая панель 3x-ui (можно пропустить и добавить позже через /admin -> Серверы)"
  SETUP_PANEL="$(ask_yn "Настроить панель 3x-ui сейчас?" y)"
  XUI_BASE_URL=""; XUI_API_TOKEN=""; XUI_INBOUND_IDS="1"; XUI_SUB_BASE_URL=""
  if [ "$SETUP_PANEL" = "yes" ]; then
    XUI_BASE_URL="$(ask_required "Base URL панели (например, https://panel.example.com:2053)")"
    XUI_API_TOKEN="$(ask_required "API-токен панели (Settings -> Security -> API Token)")"
    XUI_INBOUND_IDS="$(ask "ID инбаундов через запятую" "1")"
    XUI_SUB_BASE_URL="$(ask_required "Base URL Subscription-сервиса панели (например, https://panel.example.com:2096/sub)")"
  fi

  echo
  info "Оплата картой через ЮKassa (можно пропустить и включить позже через .env)"
  SETUP_YOOKASSA="$(ask_yn "Настроить ЮKassa сейчас?" n)"
  YOOKASSA_SHOP_ID=""; YOOKASSA_SECRET_KEY=""
  if [ "$SETUP_YOOKASSA" = "yes" ]; then
    YOOKASSA_SHOP_ID="$(ask_required "YooKassa shopId")"
    YOOKASSA_SECRET_KEY="$(ask_required "YooKassa secretKey")"
  fi

  echo
  info "Обязательная подписка на канал (можно пропустить)"
  SETUP_CHANNEL="$(ask_yn "Требовать подписку на канал перед использованием бота/сайта?" n)"
  REQUIRED_CHANNEL_ID=""; REQUIRED_CHANNEL_URL=""
  if [ "$SETUP_CHANNEL" = "yes" ]; then
    REQUIRED_CHANNEL_ID="$(ask_required "ID или @username канала (бот должен быть в нём участником/админом)")"
    REQUIRED_CHANNEL_URL="$(ask_required "Ссылка-приглашение на канал (https://t.me/...)")"
  fi

  echo
  BOT_USERNAME="$(ask "Username бота без @ (для ссылки 'Открыть в Telegram' на сайте, необязательно)" "")"
  SHOP_BOT_URL=""
  [ -n "$BOT_USERNAME" ] && SHOP_BOT_URL="https://t.me/${BOT_USERNAME}"

  WEBAPP_URL="https://${DOMAIN}"

  info "Записываю .env"
  cat > "$ENV_FILE" << EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=
WEBAPP_URL=${WEBAPP_URL}
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8000

ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
SECRET_KEY=${SECRET_KEY}

XUI_BASE_URL=${XUI_BASE_URL}
XUI_API_TOKEN=${XUI_API_TOKEN}
XUI_INBOUND_IDS=${XUI_INBOUND_IDS}
XUI_SUB_BASE_URL=${XUI_SUB_BASE_URL}
XUI_EXTERNAL_SUBSCRIPTIONS=[]
XUI_CLIENT_FLOW=xtls-rprx-vision

DATABASE_URL=sqlite+aiosqlite:///${PROJECT_DIR}/vpnshop.db

YOOKASSA_SHOP_ID=${YOOKASSA_SHOP_ID}
YOOKASSA_SECRET_KEY=${YOOKASSA_SECRET_KEY}
YOOKASSA_RETURN_URL=
CRYPTOBOT_TOKEN=

NOTIFY_DAYS_BEFORE=3,1
NOTIFY_CHECK_INTERVAL_MINUTES=60

TRIAL_ENABLED=true
TRIAL_DAYS=1
TRIAL_DATA_LIMIT_GB=0

REQUIRED_CHANNEL_ID=${REQUIRED_CHANNEL_ID}
REQUIRED_CHANNEL_URL=${REQUIRED_CHANNEL_URL}

APP_LINK_IOS=https://www.happ.su/main/ru
APP_LINK_ANDROID=https://www.happ.su/main/ru
APP_LINK_MACOS=https://www.happ.su/main/ru
APP_LINK_WINDOWS=https://github.com/2dust/v2rayN/releases/download/7.24.9/v2rayN-windows-64.zip
APP_LINK_LINUX=https://github.com/2dust/v2rayN/releases

SHOP_ENABLED=true
SHOP_TITLE=VPN Shop
SHOP_BOT_URL=${SHOP_BOT_URL}
EOF
  chmod 600 "$ENV_FILE"
  ok ".env записан"
else
  # Переиспользуем существующий .env — достаём из него DOMAIN и email для certbot
  info "Использую существующий .env"
  WEBAPP_URL="$(grep -E '^WEBAPP_URL=' "$ENV_FILE" | cut -d= -f2-)"
  DOMAIN="${WEBAPP_URL#https://}"
  DOMAIN="${DOMAIN#http://}"
  LE_EMAIL="$(ask_required "Email для Let's Encrypt" )"
  [ -z "$DOMAIN" ] && die "Не удалось определить домен из WEBAPP_URL в .env — впишите его туда вручную и перезапустите"
fi

WEBAPP_PORT="$(grep -E '^WEBAPP_PORT=' "$ENV_FILE" | cut -d= -f2-)"
WEBAPP_PORT="${WEBAPP_PORT:-8000}"

# ---------------------------------------------------------------------------
# 3. Системный пользователь для сервисов
# ---------------------------------------------------------------------------
SERVICE_USER="vpnshop"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  info "Создаю системного пользователя '$SERVICE_USER'"
  useradd --system --home "$PROJECT_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
else
  ok "Пользователь '$SERVICE_USER' уже существует"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# 4. Python venv + зависимости
# ---------------------------------------------------------------------------
info "Создаю виртуальное окружение и ставлю зависимости (может занять минуту)…"
sudo -u "$SERVICE_USER" "$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
sudo -u "$SERVICE_USER" "$PROJECT_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$SERVICE_USER" "$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q
ok "Зависимости установлены"

# ---------------------------------------------------------------------------
# 5. systemd
# ---------------------------------------------------------------------------
info "Создаю systemd-сервисы"

cat > /etc/systemd/system/vpnshop-bot.service << EOF
[Unit]
Description=VPN Shop — Telegram bot
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${PROJECT_DIR}/.venv/bin/python -m bot.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/vpnshop-web.service << EOF
[Unit]
Description=VPN Shop — web (Mini App + shop + admin API)
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn webapp.main:app --host 127.0.0.1 --port ${WEBAPP_PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now vpnshop-bot.service vpnshop-web.service
ok "Сервисы vpnshop-bot и vpnshop-web запущены"

# ---------------------------------------------------------------------------
# 6. nginx
# ---------------------------------------------------------------------------
info "Настраиваю nginx для домена ${DOMAIN}"

NGINX_SITE="/etc/nginx/sites-available/vpnshop"
cat > "$NGINX_SITE" << EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${WEBAPP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/vpnshop
[ -f /etc/nginx/sites-enabled/default ] && rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx
ok "nginx настроен и перезапущен (пока без HTTPS)"

# ---------------------------------------------------------------------------
# 7. Let's Encrypt
# ---------------------------------------------------------------------------
echo
info "Проверяю, что домен ${DOMAIN} резолвится на этот сервер, перед выпуском сертификата…"
SERVER_IP="$(curl -fsS4 https://api.ipify.org || true)"
DOMAIN_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -n1 || true)"

if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
  warn "DNS-запись домена ($DOMAIN_IP) пока не совпадает с IP этого сервера ($SERVER_IP)."
  warn "Сертификат Let's Encrypt сейчас, скорее всего, не выпустится."
  PROCEED_LE="$(ask_yn "Всё равно попробовать выпустить сертификат?" n)"
else
  PROCEED_LE=yes
fi

if [ "$PROCEED_LE" = "yes" ]; then
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$LE_EMAIL" --redirect; then
    ok "HTTPS-сертификат выпущен и подключён, certbot настроил автопродление (systemd timer certbot.timer)"
  else
    warn "certbot не смог выпустить сертификат. Убедитесь, что DNS указывает на сервер и порт 80 доступен снаружи,"
    warn "затем запустите вручную: certbot --nginx -d ${DOMAIN} --agree-tos -m ${LE_EMAIL} --redirect"
  fi
else
  warn "Пропускаю выпуск сертификата. Когда DNS будет готов, выполните:"
  warn "  certbot --nginx -d ${DOMAIN} --agree-tos -m ${LE_EMAIL} --redirect"
fi

# ---------------------------------------------------------------------------
# 8. (опционально) ufw
# ---------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  info "Обнаружен активный ufw — открываю порты 80/443"
  ufw allow 80/tcp >/dev/null || true
  ufw allow 443/tcp >/dev/null || true
fi

# ---------------------------------------------------------------------------
# Готово
# ---------------------------------------------------------------------------
echo
echo -e "${C_BOLD}${C_GREEN}======================================================================"
echo " Установка завершена"
echo -e "======================================================================${C_RESET}"
echo
echo "Сайт (веб-магазин, без Telegram): https://${DOMAIN}/"
echo "Mini App (для BotFather -> Menu Button / Mini App URL): https://${DOMAIN}/tgapp"
echo "Админка: https://${DOMAIN}/admin"
if [ "$REUSE_ENV" = "no" ]; then
  echo "  Логин: ${ADMIN_USERNAME}"
  echo "  Пароль: ${ADMIN_PASSWORD}"
fi
echo
echo "Дальнейшие шаги:"
echo "  1. В @BotFather пропишите Mini App / Menu Button URL: https://${DOMAIN}/tgapp"
echo "  2. Если включали ЮKassa — впишите в её личном кабинете webhook URL:"
echo "     https://${DOMAIN}/api/yookassa/webhook (события payment.succeeded, payment.canceled)"
echo "  3. Если панель 3x-ui не настраивали сейчас — добавьте её в админке: /admin -> Серверы"
echo "  4. Если включали обязательную подписку на канал — добавьте бота в канал участником/админом"
echo
echo "Полезные команды:"
echo "  journalctl -u vpnshop-bot -f     # логи бота"
echo "  journalctl -u vpnshop-web -f     # логи веб-сервера"
echo "  systemctl restart vpnshop-bot vpnshop-web"
echo "  sudo bash $PROJECT_DIR/install.sh   # перезапустить установку (спросит, использовать ли текущий .env)"
echo
