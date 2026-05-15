#!/bin/bash
# ============================================
# Скрипт деплоя Квартира-Компаратор
# Интерактивный выбор платформы и настройка
# ============================================

set -e

echo "╔══════════════════════════════════════════╗"
echo "║   Квартира-Компаратор — Деплой          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Функции
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Проверка Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker не установлен. Установите: https://docs.docker.com/get-docker/"
    fi
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        error "Docker Compose не установлен."
    fi
    info "Docker найден: $(docker --version)"
}

# Создание .env файла
setup_env() {
    if [ ! -f .env ]; then
        info "Создаём .env из .env.example..."
        cp .env.example .env

        # Генерируем случайный SECRET_KEY
        SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
        sed -i "s/APP_SECRET_KEY=.*/APP_SECRET_KEY=$SECRET/" .env

        echo ""
        read -p "Задать пароль для доступа к приложению? (y/n): " set_pass
        if [ "$set_pass" = "y" ] || [ "$set_pass" = "Y" ]; then
            read -sp "Введите пароль: " password
            echo ""
            sed -i "s/# APP_PASSWORD=.*/APP_PASSWORD=$password/" .env
            info "Пароль установлен."
        fi

        echo ""
        read -p "Привязать домен? (оставьте пустым для пропуска): " domain
        if [ -n "$domain" ]; then
            sed -i "s/# DOMAIN_NAME=.*/DOMAIN_NAME=$domain/" .env
            info "Домен: $domain"
        fi
    else
        info ".env файл уже существует."
    fi
}

# Деплой на VPS с Docker
deploy_vps() {
    info "Деплой на VPS/сервер с Docker..."
    echo ""

    check_docker
    setup_env

    info "Собираем Docker-образы..."
    docker compose build

    info "Запускаем контейнеры..."
    docker compose up -d

    echo ""
    info "Приложение запущено!"
    echo ""
    echo "  Доступ: http://$(hostname -I | awk '{print $1}') или http://localhost"
    echo ""
    echo "  Полезные команды:"
    echo "    docker compose logs -f        — логи"
    echo "    docker compose restart        — перезапуск"
    echo "    docker compose down           — остановка"
    echo ""

    # SSL
    read -p "Настроить SSL с Let's Encrypt? (y/n): " setup_ssl
    if [ "$setup_ssl" = "y" ] || [ "$setup_ssl" = "Y" ]; then
        deploy_ssl
    fi
}

# Настройка SSL
deploy_ssl() {
    if [ -z "$domain" ]; then
        read -p "Введите доменное имя: " domain
    fi

    if [ -z "$domain" ]; then
        warn "Домен не указан, пропускаем SSL."
        return
    fi

    read -p "Email для Let's Encrypt: " email
    if [ -z "$email" ]; then
        warn "Email не указан, пропускаем SSL."
        return
    fi

    info "Получаем SSL-сертификат для $domain..."
    docker compose --profile ssl run --rm certbot certonly \
        --webroot -w /var/www/certbot \
        --email "$email" \
        -d "$domain" \
        --agree-tos --no-eff-email

    info "Перезапускаем Nginx с SSL..."
    # Раскомментируем HTTPS блок в nginx.conf
    sed -i 's/# return 301/return 301/' nginx/nginx.conf
    docker compose restart nginx

    info "SSL настроен для $domain!"
}

# Деплой на Render.com
deploy_render() {
    info "Деплой на Render.com..."
    echo ""
    echo "  Шаги для деплоя на Render:"
    echo ""
    echo "  1. Зайдите на https://render.com и войдите через GitHub"
    echo "  2. Нажмите 'New +' -> 'Blueprint'"
    echo "  3. Подключите этот репозиторий"
    echo "  4. Render автоматически найдёт render.yaml"
    echo "  5. Задайте переменные окружения:"
    echo "     - APP_PASSWORD (пароль для доступа)"
    echo "  6. Нажмите 'Apply'"
    echo ""
    echo "  Или через CLI:"
    echo "    npm install -g @render/cli"
    echo "    render blueprint apply"
    echo ""
    info "Файл render.yaml уже создан в проекте."
}

# Деплой на Fly.io
deploy_fly() {
    info "Деплой на Fly.io..."
    echo ""

    if ! command -v fly &> /dev/null; then
        echo "  Установите Fly CLI:"
        echo "    curl -L https://fly.io/install.sh | sh"
        echo ""
        read -p "Fly CLI установлен? (y/n): " fly_ready
        if [ "$fly_ready" != "y" ]; then
            error "Установите Fly CLI и повторите."
        fi
    fi

    info "Авторизация в Fly.io..."
    fly auth login

    info "Создаём приложение..."
    fly apps create kvartira-comparator 2>/dev/null || warn "Приложение уже существует"

    info "Создаём volume для данных..."
    fly volumes create kvartira_data --size 1 --region ams 2>/dev/null || warn "Volume уже существует"

    info "Задаём secrets..."
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
    fly secrets set APP_SECRET_KEY="$SECRET"

    read -sp "Пароль для приложения (Enter для пропуска): " password
    echo ""
    if [ -n "$password" ]; then
        fly secrets set APP_PASSWORD="$password"
    fi

    info "Деплоим..."
    fly deploy

    echo ""
    info "Приложение развёрнуто!"
    echo "  URL: https://kvartira-comparator.fly.dev"
    echo ""
    echo "  Полезные команды:"
    echo "    fly logs                   — логи"
    echo "    fly status                 — статус"
    echo "    fly ssh console            — SSH в контейнер"
    echo "    fly scale count 1          — масштабирование"
}

# Локальный запуск (разработка)
deploy_local() {
    info "Локальный запуск для разработки..."
    echo ""

    check_docker
    setup_env

    info "Собираем и запускаем..."
    docker compose up --build -d

    echo ""
    info "Приложение доступно по адресу:"
    echo "  http://localhost"
    echo ""
    echo "  Логи: docker compose logs -f"
    echo "  Стоп: docker compose down"
}

# === Главное меню ===
echo "Выберите платформу для деплоя:"
echo ""
echo "  1) Локальный запуск (Docker Compose)"
echo "  2) VPS/Сервер (Docker + Nginx + SSL)"
echo "  3) Render.com (бесплатный тир)"
echo "  4) Fly.io (бесплатный тир)"
echo ""
read -p "Ваш выбор [1-4]: " choice

case $choice in
    1) deploy_local ;;
    2) deploy_vps ;;
    3) deploy_render ;;
    4) deploy_fly ;;
    *) error "Неверный выбор. Укажите число от 1 до 4." ;;
esac
