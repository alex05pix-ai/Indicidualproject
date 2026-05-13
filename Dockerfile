# ---------------------------------------------------------------------------
# Образ с Python 3.11 + Chromium от Playwright (всё уже предустановлено).
# Использование:
#     docker build -t krsk-flat-comparator .
#     docker run -p 5000:5000 krsk-flat-comparator
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Сначала зависимости — лучше для кеширования слоёв.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Затем код приложения.
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
