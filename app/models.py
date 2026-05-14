"""SQLAlchemy-модели приложения.

Хранятся:
- история запросов пользователей (``QueryHistory``);
- закешированные результаты сравнений для share-ссылок (``CachedResult``);
- кеш геокодирования (``GeocodeCache``).
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

# Единый объект SQLAlchemy для Flask-приложения
db = SQLAlchemy()
Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _generate_share_id() -> str:
    """Генерирует короткий URL-safe идентификатор для share-ссылки."""
    return secrets.token_urlsafe(8)


class QueryHistory(db.Model):
    """История запросов пользователя.

    Сохраняется любой успешный запрос на сравнение, чтобы пользователь
    мог увидеть последние ``APP_HISTORY_LIMIT`` сравнений.
    """

    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow, index=True)

    # Параметры исходной квартиры
    address = Column(String(512), nullable=False)
    district = Column(String(128), nullable=True)
    rooms = Column(String(16), nullable=False)  # studio | 1 | 2 | 3 | 4plus
    total_area = Column(Float, nullable=True)
    kitchen_area = Column(Float, nullable=True)
    floor = Column(Integer, nullable=True)
    floors_total = Column(Integer, nullable=True)
    year_built = Column(Integer, nullable=True)
    price = Column(Float, nullable=False)

    # Дополнительные фильтры
    radius_km = Column(Float, nullable=False, default=2.0)
    area_tolerance = Column(Float, nullable=False, default=0.15)
    depth = Column(Integer, nullable=False, default=20)

    # Сводка результата
    listings_found = Column(Integer, nullable=False, default=0)
    avg_price_per_m2 = Column(Float, nullable=True)
    median_price = Column(Float, nullable=True)

    # FK на закешированный результат (если был сохранён) — храним как share_id
    share_id = Column(String(32), nullable=True, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "address": self.address,
            "district": self.district,
            "rooms": self.rooms,
            "total_area": self.total_area,
            "price": self.price,
            "listings_found": self.listings_found,
            "avg_price_per_m2": self.avg_price_per_m2,
            "median_price": self.median_price,
            "share_id": self.share_id,
        }


class CachedResult(db.Model):
    """Закешированный результат сравнения (для share-ссылок).

    JSON с аналогами и метриками. По умолчанию TTL = 24 часа
    (управляется ``APP_SHARE_TTL_HOURS``).
    """

    __tablename__ = "cached_results"

    share_id = Column(String(32), primary_key=True, default=_generate_share_id)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    payload = Column(Text, nullable=False)  # JSON-строка

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @classmethod
    def create(cls, payload: dict[str, Any], ttl_hours: int = 24) -> "CachedResult":
        return cls(
            share_id=_generate_share_id(),
            created_at=_utcnow(),
            expires_at=_utcnow() + timedelta(hours=ttl_hours),
            payload=json.dumps(payload, ensure_ascii=False),
        )

    def get_payload(self) -> dict[str, Any]:
        try:
            return json.loads(self.payload)
        except json.JSONDecodeError:
            return {}


class GeocodeCache(db.Model):
    """Кеш геокодирования адресов.

    Без кеша мы быстро упрёмся в лимит Nominatim (1 запрос/сек.).
    Ключ — нормализованный адрес (lowercase, trim).
    """

    __tablename__ = "geocode_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(512), nullable=False, unique=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    display_name = Column(String(1024), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("idx_geocode_address", "address"),)


def init_db(flask_app) -> None:
    """Создаёт таблицы в БД при первом запуске.

    Args:
        flask_app: инициализированное Flask-приложение.
    """
    with flask_app.app_context():
        db.create_all()
