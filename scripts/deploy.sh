#!/usr/bin/env bash
# =============================================================================
# Avito Comparator — интерактивный скрипт деплоя.
#
# Поддерживаемые цели:
#   1) Локальный запуск (docker compose up)
#   2) VPS (docker compose up -d + проверка nginx)
#   3) Render.com (открыть инструкцию + push в репозиторий)
#   4) Fly.io (flyctl launch + deploy)
#
# Использование:
#   ./scripts/deploy.sh             # интерактивный режим
#   ./scripts/deploy.sh local       # сразу локальный режим
#   ./scripts/deploy.sh vps
#   ./scripts/deploy.sh render
#   ./scripts/deploy.sh fly
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# ---------- Цвета ----------
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
  C_BLU=$'\033[34m'; C_BLD=$'\033[1m'; C_END=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_BLU=""; C_BLD=""; C_END=""
fi
log()  { printf "%s[deploy]%s %s\n" "$C_BLU" "$C_END" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$C_YEL" "$C_END" "$*"; }
err()  { printf "%s[error]%s %s\n" "$C_RED" "$C_END" "$*" >&2; }
ok()   { printf "%s[ok]%s %s\n" "$C_GRN" "$C_END" "$*"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Не найдена команда '$1'. Установите её и повторите."; exit 1; }
}

ensure_env_file() {
  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      log "Создаю .env из .env.example…"
      cp .env.example .env
      warn "Отредактируйте .env (особенно APP_SECRET_KEY и APP_PASSWORD)."
    else
      warn ".env не найден и .env.example отсутствует — продолжаем с дефолтами."
    fi
  fi
}

deploy_local() {
  log "Локальный запуск (docker compose up --build)…"
  require_cmd docker
  ensure_env_file
  docker compose up --build
}

deploy_vps() {
  log "Деплой на VPS (docker compose up -d --build)…"
  require_cmd docker
  ensure_env_file

  if [[ -n "${DOMAIN_NAME:-}" ]]; then
    log "Используется домен: $DOMAIN_NAME"
  else
    warn "Переменная DOMAIN_NAME не задана. nginx запустится для любого Host."
  fi

  docker compose pull || true
  docker compose up -d --build
  log "Ожидаю готовность health-check…"
  for i in {1..30}; do
    if curl -fsS -o /dev/null "http://127.0.0.1/healthz"; then
      ok "Сервис отвечает на /healthz."
      break
    fi
    sleep 2
  done

  cat <<EOF

${C_BLD}Дальнейшие шаги:${C_END}
  1) Убедитесь, что DNS A-запись $DOMAIN_NAME указывает на IP сервера.
  2) Получите сертификат Let's Encrypt:
       docker compose run --rm certbot certonly --webroot -w /var/www/certbot \\
         -d "$DOMAIN_NAME" --email "\${LETSENCRYPT_EMAIL:-you@example.com}" \\
         --agree-tos --no-eff-email
  3) Раскомментируйте HTTPS-блок в nginx/nginx.conf и:
       docker compose restart nginx
  4) Проверьте: https://$DOMAIN_NAME/

${C_BLD}Логи приложения:${C_END} docker compose logs -f app
EOF
}

deploy_render() {
  log "Деплой на Render.com — через Blueprint (render.yaml уже в репозитории)."
  require_cmd git

  cat <<EOF

${C_BLD}Шаги:${C_END}
  1) Запушьте репозиторий на GitHub/GitLab (если ещё не запушен):
       git push origin HEAD

  2) Откройте https://dashboard.render.com → New + → Blueprint
  3) Подключите свой репозиторий — Render найдёт render.yaml и предложит создать сервис.
  4) В разделе Environment задайте:
        - APP_PASSWORD     (для HTTP Basic Auth, иначе сайт открыт)
        - DOMAIN_NAME      (опционально, если есть свой домен)
  5) Нажмите Deploy. Через ~5 минут сайт будет на https://<service>.onrender.com

${C_YEL}ВАЖНО:${C_END} на бесплатном тарифе Render «засыпает» после 15 минут простоя.
Первый запрос после простоя будет долгим (~30 сек).
EOF

  read -rp "Запушить текущую ветку в origin сейчас? [y/N] " ans
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    git push origin HEAD
    ok "Запушено. Откройте Render dashboard и подтвердите деплой."
  fi
}

deploy_fly() {
  log "Деплой на Fly.io…"
  require_cmd flyctl

  if ! flyctl auth whoami >/dev/null 2>&1; then
    log "Нужна авторизация Fly:"
    flyctl auth login
  fi

  if ! flyctl status >/dev/null 2>&1; then
    log "Создаю приложение (flyctl launch --no-deploy)…"
    flyctl launch --no-deploy --copy-config --dockerfile docker/Dockerfile
  fi

  log "Создаю volume для SQLite (если ещё не создан)…"
  flyctl volumes list 2>/dev/null | grep -q avito_data || \
    flyctl volumes create avito_data --size 1 --region "${FLY_REGION:-fra}"

  log "Устанавливаю секреты…"
  if [[ -z "${APP_SECRET_KEY:-}" ]]; then
    APP_SECRET_KEY="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64 || true)"
  fi
  flyctl secrets set "APP_SECRET_KEY=$APP_SECRET_KEY"
  if [[ -n "${APP_PASSWORD:-}" ]]; then
    flyctl secrets set "APP_PASSWORD=$APP_PASSWORD"
  else
    warn "APP_PASSWORD не задан — приложение будет доступно всем."
  fi

  log "Деплой (flyctl deploy)…"
  flyctl deploy

  ok "Готово. Откройте https://$(flyctl info --json 2>/dev/null | grep -o '\"Hostname\":\"[^\"]*' | cut -d'\"' -f4)/"
}

# ---------- Main ----------
target="${1:-}"
if [[ -z "$target" ]]; then
  cat <<EOF
${C_BLD}Avito Comparator — выбор цели деплоя${C_END}

  1) Local        — docker compose up (для разработки)
  2) VPS          — docker compose -d (любой сервер с Docker)
  3) Render.com   — Blueprint deploy (free tier)
  4) Fly.io       — flyctl deploy (free tier)
  q) Выход
EOF
  read -rp "Выберите [1-4/q]: " choice
  case "$choice" in
    1) target=local ;;
    2) target=vps ;;
    3) target=render ;;
    4) target=fly ;;
    q|Q) exit 0 ;;
    *) err "Неверный выбор."; exit 1 ;;
  esac
fi

case "$target" in
  local)  deploy_local ;;
  vps)    deploy_vps ;;
  render) deploy_render ;;
  fly)    deploy_fly ;;
  *) err "Неизвестная цель: $target"; exit 1 ;;
esac
