"""
Модуль конфигурации приложения.
Загружает настройки из переменных окружения с префиксом APP_.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Загружаем .env файл если он существует
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Config:
    """Основная конфигурация приложения."""

    # === Основные настройки ===
    SECRET_KEY: str = os.getenv("APP_SECRET_KEY", "change-me-in-production-please")
    DEBUG: bool = os.getenv("APP_DEBUG", "false").lower() in ("true", "1", "yes")
    HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", os.getenv("APP_PORT", "5000")))

    # === Домен и доступ ===
    DOMAIN_NAME: Optional[str] = os.getenv("DOMAIN_NAME", None)
    APP_PASSWORD: Optional[str] = os.getenv("APP_PASSWORD", None)

    # === База данных ===
    DATABASE_URL: str = os.getenv(
        "APP_DATABASE_URL",
        f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'app.db'}"
    )

    # === Город и геокодирование ===
    CITY: str = os.getenv("APP_CITY", "Красноярск")
    CITY_LAT: float = float(os.getenv("APP_CITY_LAT", "56.0153"))
    CITY_LON: float = float(os.getenv("APP_CITY_LON", "92.8932"))
    NOMINATIM_USER_AGENT: str = os.getenv(
        "APP_NOMINATIM_USER_AGENT", "kvartira-comparator/1.0"
    )
    GEOCODE_CACHE_TTL: int = int(os.getenv("APP_GEOCODE_CACHE_TTL", "86400"))  # 24 часа

    # === Парсер Avito ===
    PARSER_MIN_DELAY: float = float(os.getenv("APP_PARSER_MIN_DELAY", "2.0"))
    PARSER_MAX_DELAY: float = float(os.getenv("APP_PARSER_MAX_DELAY", "5.0"))
    PARSER_PAGE_DELAY_MIN: float = float(os.getenv("APP_PARSER_PAGE_DELAY_MIN", "10.0"))
    PARSER_PAGE_DELAY_MAX: float = float(os.getenv("APP_PARSER_PAGE_DELAY_MAX", "20.0"))
    PARSER_MAX_PAGES: int = int(os.getenv("APP_PARSER_MAX_PAGES", "5"))
    PARSER_MAX_ANALOGS: int = int(os.getenv("APP_PARSER_MAX_ANALOGS", "20"))
    PARSER_TIMEOUT: int = int(os.getenv("APP_PARSER_TIMEOUT", "60000"))  # мс
    PARSER_COOKIES_FILE: Optional[str] = os.getenv("APP_PARSER_COOKIES_FILE", None)

    # === Фильтры по умолчанию ===
    DEFAULT_AREA_TOLERANCE: float = float(os.getenv("APP_DEFAULT_AREA_TOLERANCE", "0.15"))
    DEFAULT_MAX_DISTANCE_KM: float = float(os.getenv("APP_DEFAULT_MAX_DISTANCE_KM", "2.0"))
    DEFAULT_SEARCH_DEPTH: int = int(os.getenv("APP_DEFAULT_SEARCH_DEPTH", "10"))

    # === Кеширование результатов ===
    CACHE_TTL: int = int(os.getenv("APP_CACHE_TTL", "3600"))  # 1 час
    SHARE_LINK_TTL: int = int(os.getenv("APP_SHARE_LINK_TTL", "86400"))  # 24 часа

    # === Логирование ===
    LOG_LEVEL: str = os.getenv("APP_LOG_LEVEL", "INFO")
    LOG_FILE: Optional[str] = os.getenv("APP_LOG_FILE", None)

    # === Районы Красноярска ===
    DISTRICTS: dict = {
        "Советский": {"lat": 56.0341, "lon": 92.8598},
        "Центральный": {"lat": 56.0101, "lon": 92.8714},
        "Октябрьский": {"lat": 56.0183, "lon": 92.9156},
        "Железнодорожный": {"lat": 56.0044, "lon": 92.8285},
        "Свердловский": {"lat": 56.0269, "lon": 92.9532},
        "Кировский": {"lat": 55.9871, "lon": 92.9714},
        "Ленинский": {"lat": 55.9912, "lon": 92.8102},
    }

    MICRODISTRICTS: dict = {
        "Северный": {"lat": 56.0612, "lon": 92.9125, "district": "Советский"},
        "Взлётка": {"lat": 56.0401, "lon": 92.8891, "district": "Советский"},
        "Покровка": {"lat": 56.0523, "lon": 92.8512, "district": "Центральный"},
        "Зелёная Роща": {"lat": 56.0289, "lon": 92.8345, "district": "Советский"},
        "Академгородок": {"lat": 56.0456, "lon": 92.9678, "district": "Октябрьский"},
        "Солнечный": {"lat": 56.0678, "lon": 92.9234, "district": "Советский"},
        "Пашенный": {"lat": 55.9756, "lon": 92.7845, "district": "Ленинский"},
        "Черёмушки": {"lat": 55.9923, "lon": 92.8567, "district": "Кировский"},
        "Первомайский": {"lat": 56.0312, "lon": 92.9345, "district": "Свердловский"},
        "Ветлужанка": {"lat": 56.0534, "lon": 92.8123, "district": "Октябрьский"},
    }

    # === User-Agent ротация ===
    USER_AGENTS: list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    ]

    VIEWPORTS: list = [
        {"width": 1920, "height": 1080},
        {"width": 1366, "height": 768},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 720},
    ]


config = Config()
