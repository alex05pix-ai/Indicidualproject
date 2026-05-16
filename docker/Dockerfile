# ============================================
# Dockerfile для Квартира-Компаратор
# Многоэтапная сборка для минимального размера
# ============================================

# --- Этап 1: Установка зависимостей ---
FROM python:3.11-slim as builder

WORKDIR /build

# Системные зависимости для сборки
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Этап 2: Финальный образ ---
FROM python:3.11-slim

LABEL maintainer="kvartira-comparator"
LABEL description="Apartment price comparison app for Krasnoyarsk"

WORKDIR /app

# Системные зависимости для Playwright Chromium (все нужные, без install-deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fonts-liberation \
    fonts-freefont-ttf \
    fontconfig \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libexpat1 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    libxkbcommon0 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Копируем установленные Python-пакеты
COPY --from=builder /install /usr/local

# Устанавливаем только Chromium (без install-deps — зависимости уже установлены выше)
RUN playwright install chromium

# Копируем код приложения
COPY app/ ./app/
COPY requirements.txt .
COPY .env.example .

# Создаём директорию для данных
RUN mkdir -p /app/data && chmod 777 /app/data

# Переменные окружения по умолчанию
ENV APP_HOST=0.0.0.0
ENV APP_PORT=5000
ENV APP_DEBUG=false
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Порт приложения
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:5000/ || exit 1

# Запуск через Gunicorn с eventlet для WebSocket
CMD gunicorn --worker-class eventlet --workers 1 \
     --bind 0.0.0.0:${APP_PORT:-5000} --timeout 300 \
     --access-logfile - --error-logfile - \
     app.main:app
