# syntax=docker/dockerfile:1.6
# =============================================================================
# Avito Comparator — Dockerfile (многоэтапная сборка)
#
# Этап 1 (builder):
#   - Устанавливает зависимости в виртуальное окружение /opt/venv.
# Этап 2 (runtime):
#   - Берёт официальный образ Microsoft Playwright (с Chromium и системными deps).
#   - Копирует venv и исходники приложения.
#   - Запускает Gunicorn с eventlet-воркером (для Flask-SocketIO).
#
# Зачем mcr.microsoft.com/playwright/python:
#   В нём уже установлены все системные библиотеки, которые нужны Chromium,
#   плюс предустановлен сам браузер и `playwright`. Это избавляет нас от
#   ручной возни с apt-get install libnss3, libxkbcommon, fonts и т. д.
# =============================================================================

ARG PYTHON_VERSION=3.11
ARG PLAYWRIGHT_VERSION=v1.47.0-jammy

# ---------- Stage 1: builder ----------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./
RUN pip install --upgrade pip wheel \
 && pip install -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM mcr.microsoft.com/playwright/python:${PLAYWRIGHT_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

# Минимальный набор runtime-пакетов (psycopg2 ABI и tini как PID 1)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 \
        tini \
 && rm -rf /var/lib/apt/lists/*

# Не запускаем приложение от root
RUN groupadd --system app && useradd --system --gid app --create-home --home /home/app app

# Виртуалка с зависимостями
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Копируем код
COPY app/ ./app/
COPY .env.example ./

# Каталог для SQLite БД и потенциальных volume-данных
RUN mkdir -p /app/data \
 && chown -R app:app /app /home/app

# В базовом образе mcr.microsoft.com/playwright/python Chromium уже установлен
# в /ms-playwright (доступен всем пользователям), поэтому повторный
# `playwright install` не требуется.

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]

# Один воркер с eventlet — обязательное требование Flask-SocketIO для WebSocket
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--worker-class", "eventlet", \
     "--workers", "1", \
     "--threads", "8", \
     "--timeout", "300", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.main:app"]
