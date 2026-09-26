#!/usr/bin/env bash
# Обновляет код из git и перезапускает бота и веб-сервис.
# Использование: sudo bash update.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Запустите через sudo: sudo bash update.sh" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
SERVICE_USER="vpnshop"

echo "==> git pull"
git config --global --add safe.directory "$PROJECT_DIR" >/dev/null 2>&1 || true
git pull

echo "==> обновляю зависимости (если requirements.txt менялся)"
sudo -u "$SERVICE_USER" "$PROJECT_DIR/.venv/bin/pip" install -r requirements.txt -q

echo "==> возвращаю владельца файлов ($SERVICE_USER)"
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"

echo "==> чищу кэш байткода на всякий случай"
find "$PROJECT_DIR" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "==> перезапускаю сервисы"
systemctl restart vpnshop-bot vpnshop-web

echo "==> готово. Статус:"
systemctl is-active vpnshop-bot vpnshop-web
