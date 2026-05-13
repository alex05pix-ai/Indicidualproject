"""
SQLAlchemy-модели для SQLite.

Используются для:
  * Истории поисковых запросов пользователя.
  * Кеша геокодирования (один и тот же адрес не геокодируем дважды).
  * Шеринга результата по уникальной ссылке (24 часа).
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""


class SearchHistory(Base):
    """История запросов пользователя.

    Хранит «снимок» введённой в форму квартиры и сериализованный
    результат сравнения (json), чтобы можно было пересмотреть его
    позднее, не запуская парсинг снова.
    """

    __tablename__ = "search_history"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, index=True)

    address: str = Column(String(255), nullable=False)
    district: Optional[str] = Column(String(100), nullable=True)
    rooms: str = Column(String(16), nullable=False)
    total_area: Optional[float] = Column(Float, nullable=True)
    kitchen_area: Optional[float] = Column(Float, nullable=True)
    floor: Optional[int] = Column(Integer, nullable=True)
    floors_total: Optional[int] = Column(Integer, nullable=True)
    build_year: Optional[int] = Column(Integer, nullable=True)
    price: Optional[float] = Column(Float, nullable=True)

    distance_km: float = Column(Float, default=config.DEFAULT_DISTANCE_KM)
    area_tolerance: float = Column(Float, default=config.DEFAULT_AREA_TOLERANCE)
    depth: int = Column(Integer, default=config.DEFAULT_RESULTS)

    # Сериализованные аналоги и аналитика (json)
    result_json: str = Column(Text, nullable=True)

    def short_summary(self) -> str:
        """Короткая строка для списка истории."""
        return f"{self.rooms}-комн, {self.address} ({self.created_at:%d.%m.%Y %H:%M})"


class GeocodeCache(Base):
    """Кеш геокодирования. Ключ — нормализованная строка запроса."""

    __tablename__ = "geocode_cache"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    query: str = Column(String(255), unique=True, nullable=False, index=True)
    latitude: Optional[float] = Column(Float, nullable=True)
    longitude: Optional[float] = Column(Float, nullable=True)
    display_name: Optional[str] = Column(String(512), nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)


class SharedResult(Base):
    """Шеринг результата сравнения по уникальной короткой ссылке."""

    __tablename__ = "shared_result"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    token: str = Column(String(32), unique=True, nullable=False, index=True)
    payload_json: str = Column(Text, nullable=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    expires_at: datetime = Column(DateTime, nullable=False)

    @classmethod
    def create(cls, payload: dict[str, Any]) -> "SharedResult":
        """Создать новый объект шеринга со сроком жизни SHARE_TTL_HOURS."""
        return cls(
            token=secrets.token_urlsafe(12),
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            expires_at=datetime.utcnow()
            + timedelta(hours=config.SHARE_TTL_HOURS),
        )

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


# ---------------------------------------------------------------------------
# Инициализация engine / session
# ---------------------------------------------------------------------------
_engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False}
    if config.DATABASE_URL.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Создать все таблицы, если их ещё нет."""
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    """Фабрика сессий (caller отвечает за close)."""
    return SessionLocal()
