"""
Конфигурация приложения.

Все настраиваемые параметры (задержки парсинга, лимиты, список районов
Красноярска, путь к БД и т.п.) собраны в этом модуле, чтобы их было
удобно менять без правки бизнес-логики.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Final


# ---------------------------------------------------------------------------
# Базовые пути проекта
# ---------------------------------------------------------------------------
BASE_DIR: Final[Path] = Path(__file__).resolve().parent
LOG_FILE: Final[Path] = BASE_DIR / "app.log"
DATABASE_PATH: Final[Path] = BASE_DIR / "data.sqlite3"
DATABASE_URL: Final[str] = os.getenv(
    "DATABASE_URL", f"sqlite:///{DATABASE_PATH.as_posix()}"
)
COOKIES_FILE: Final[Path] = BASE_DIR / "avito_cookies.json"  # опционально


# ---------------------------------------------------------------------------
# Город и геокодинг
# ---------------------------------------------------------------------------
CITY_NAME: Final[str] = "Красноярск"
CITY_SLUG_AVITO: Final[str] = "krasnoyarsk"
GEOCODER_USER_AGENT: Final[str] = "krsk-flat-comparator/1.0 (educational)"
GEOCODER_TIMEOUT_SEC: Final[int] = 10


# Список районов и популярных микрорайонов Красноярска.
# Используется для выпадающего списка на форме и для маппинга
# микрорайон -> район (для уточнения поиска).
DISTRICTS: Final[list[str]] = [
    "Советский",
    "Центральный",
    "Октябрьский",
    "Железнодорожный",
    "Свердловский",
    "Кировский",
    "Ленинский",
]

MICRO_DISTRICTS: Final[list[str]] = [
    "Северный",
    "Взлётка",
    "Покровка",
    "Зелёная Роща",
    "Академгородок",
    "Солнечный",
    "Ветлужанка",
    "Студгородок",
    "Пашенный",
    "Черёмушки",
    "Энергетиков",
    "Николаевка",
]

# Карта микрорайон -> ближайший крупный район (используется для уточнения
# поискового URL Avito).
MICRO_TO_DISTRICT: Final[dict[str, str]] = {
    "Северный": "Советский",
    "Взлётка": "Советский",
    "Покровка": "Центральный",
    "Зелёная Роща": "Центральный",
    "Академгородок": "Октябрьский",
    "Солнечный": "Советский",
    "Ветлужанка": "Октябрьский",
    "Студгородок": "Октябрьский",
    "Пашенный": "Свердловский",
    "Черёмушки": "Свердловский",
    "Энергетиков": "Ленинский",
    "Николаевка": "Центральный",
}


# ---------------------------------------------------------------------------
# Параметры парсинга Avito
# ---------------------------------------------------------------------------
AVITO_BASE_URL: Final[str] = "https://www.avito.ru"

# Карта room_count -> сегмент URL Avito.
ROOM_URL_SEGMENT: Final[dict[str, str]] = {
    "studio": "studii",
    "1": "1-komnatnye",
    "2": "2-komnatnye",
    "3": "3-komnatnye",
    "4+": "4-komnatnye",
}

# Лимиты обхода
MAX_PAGES: Final[int] = 5            # сколько страниц поиска максимум листаем
MAX_RESULTS_HARD_CAP: Final[int] = 20  # абсолютный максимум результатов
DEFAULT_RESULTS: Final[int] = 10      # по умолчанию

# Случайные задержки (секунды)
DELAY_ACTION_MIN: Final[float] = 2.0
DELAY_ACTION_MAX: Final[float] = 5.0
DELAY_PAGE_MIN: Final[float] = 10.0
DELAY_PAGE_MAX: Final[float] = 20.0

# Сетевые таймауты Playwright (мс)
NAV_TIMEOUT_MS: Final[int] = 45_000

# Ротация User-Agent / viewport
USER_AGENTS: Final[list[str]] = [
    # Современные десктопные браузеры (Win/Mac/Linux)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
]

VIEWPORTS: Final[list[dict[str, int]]] = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]


# ---------------------------------------------------------------------------
# Параметры аналитики и фильтрации
# ---------------------------------------------------------------------------
DEFAULT_DISTANCE_KM: Final[float] = 2.0
DISTANCE_STEP_KM: Final[float] = 0.5
DEFAULT_AREA_TOLERANCE: Final[float] = 0.15  # +/- 15%

# Порог "цена существенно выше" (15%) — для предупреждений
PRICE_DEVIATION_WARN: Final[float] = 0.15

# Порог отклонения года постройки (10 лет)
YEAR_DEVIATION_WARN: Final[int] = 10

# Минимально допустимое число строгих совпадений по комнатам
MIN_STRICT_MATCHES: Final[int] = 5

# Сколько часов хранится результат, доступный по shared-ссылке
SHARE_TTL_HOURS: Final[int] = 24


# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
SECRET_KEY: Final[str] = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
DEBUG: Final[bool] = os.getenv("FLASK_DEBUG", "0") == "1"
HOST: Final[str] = os.getenv("HOST", "0.0.0.0")
PORT: Final[int] = int(os.getenv("PORT", "5000"))
