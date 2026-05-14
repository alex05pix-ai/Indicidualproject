"""Загрузка конфигурации из переменных окружения.

Все настройки приложения собраны в единый dataclass-like объект ``Settings``
для удобного импорта и переиспользования. Префикс переменных — ``APP_``,
кроме отдельных глобальных (``DOMAIN_NAME``, ``LETSENCRYPT_EMAIL``).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Загружаем .env из корня проекта, если он есть
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _get_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Все настройки приложения.

    Атрибуты соответствуют переменным окружения с префиксом ``APP_``.
    Объект иммутабельный — изменения должны делаться через перезапуск процесса.
    """

    # --- App ---
    secret_key: str = field(default_factory=lambda: os.getenv("APP_SECRET_KEY", "dev-secret-change-me"))
    host: str = field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _get_int("APP_PORT", 8000))
    debug: bool = field(default_factory=lambda: _get_bool("APP_DEBUG", False))
    log_level: str = field(default_factory=lambda: os.getenv("APP_LOG_LEVEL", "INFO"))

    # --- City ---
    city: str = field(default_factory=lambda: os.getenv("APP_CITY", "krasnoyarsk"))
    city_display: str = field(default_factory=lambda: os.getenv("APP_CITY_DISPLAY", "Красноярск"))

    # --- Database ---
    database_url: str = field(
        default_factory=lambda: os.getenv("APP_DATABASE_URL", "sqlite:///data/app.db")
    )

    # --- Auth ---
    password: Optional[str] = field(default_factory=lambda: os.getenv("APP_PASSWORD") or None)
    basic_auth_user: str = field(default_factory=lambda: os.getenv("APP_BASIC_AUTH_USER", "admin"))

    # --- Parser ---
    delay_min: float = field(default_factory=lambda: _get_float("APP_DELAY_MIN", 2.0))
    delay_max: float = field(default_factory=lambda: _get_float("APP_DELAY_MAX", 5.0))
    page_delay_min: float = field(default_factory=lambda: _get_float("APP_PAGE_DELAY_MIN", 10.0))
    page_delay_max: float = field(default_factory=lambda: _get_float("APP_PAGE_DELAY_MAX", 20.0))
    max_pages: int = field(default_factory=lambda: _get_int("APP_MAX_PAGES", 5))
    max_listings: int = field(default_factory=lambda: _get_int("APP_MAX_LISTINGS", 20))
    headless: bool = field(default_factory=lambda: _get_bool("APP_HEADLESS", True))
    cookies_file: Optional[str] = field(default_factory=lambda: os.getenv("APP_COOKIES_FILE") or None)
    page_timeout_ms: int = field(default_factory=lambda: _get_int("APP_PAGE_TIMEOUT_MS", 30000))

    # --- Geocoder ---
    nominatim_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "APP_NOMINATIM_USER_AGENT", "avito-comparator/1.0 (contact@example.com)"
        )
    )
    geocode_timeout: int = field(default_factory=lambda: _get_int("APP_GEOCODE_TIMEOUT", 10))

    # --- Domain ---
    domain_name: Optional[str] = field(default_factory=lambda: os.getenv("DOMAIN_NAME") or None)
    letsencrypt_email: Optional[str] = field(default_factory=lambda: os.getenv("LETSENCRYPT_EMAIL") or None)

    # --- Кэш / TTL ---
    share_ttl_hours: int = field(default_factory=lambda: _get_int("APP_SHARE_TTL_HOURS", 24))
    history_limit: int = field(default_factory=lambda: _get_int("APP_HISTORY_LIMIT", 10))

    @property
    def auth_enabled(self) -> bool:
        """Включена ли HTTP Basic Auth."""
        return bool(self.password)

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT


# Жёсткий список районов и микрорайонов Красноярска (для выпадающего списка)
DISTRICTS: list[str] = [
    "Советский",
    "Центральный",
    "Октябрьский",
    "Железнодорожный",
    "Свердловский",
    "Кировский",
    "Ленинский",
]

MICRODISTRICTS: list[str] = [
    "Северный",
    "Взлётка",
    "Покровка",
    "Зелёная Роща",
    "Академгородок",
    "Солнечный",
    "Иннокентьевский",
    "Ветлужанка",
    "Студгородок",
    "Пашенный",
    "Черёмушки",
]

# Соответствие микрорайона ближайшему административному району
MICRODISTRICT_TO_DISTRICT: dict[str, str] = {
    "Северный": "Советский",
    "Взлётка": "Советский",
    "Покровка": "Центральный",
    "Зелёная Роща": "Центральный",
    "Академгородок": "Октябрьский",
    "Солнечный": "Советский",
    "Иннокентьевский": "Советский",
    "Ветлужанка": "Октябрьский",
    "Студгородок": "Октябрьский",
    "Пашенный": "Свердловский",
    "Черёмушки": "Свердловский",
}

# Варианты количества комнат
ROOM_OPTIONS: list[tuple[str, str]] = [
    ("studio", "Студия"),
    ("1", "1"),
    ("2", "2"),
    ("3", "3"),
    ("4plus", "4+"),
]


def configure_logging(level: str) -> None:
    """Конфигурирует root-логгер для stdout (Docker-friendly)."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# Singleton-объект настроек
settings = Settings()
configure_logging(settings.log_level)
