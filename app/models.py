"""
Модели базы данных для приложения Квартира-Компаратор.
Используется SQLAlchemy ORM с поддержкой SQLite и PostgreSQL.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Boolean,
    JSON,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import config


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


class SearchQuery(Base):
    """
    Модель для хранения истории поисковых запросов пользователей.
    Каждый запрос сохраняется автоматически для истории и кеширования.
    """

    __tablename__ = "search_queries"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    public_id: str = Column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    created_at: datetime = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime = Column(DateTime, nullable=True)

    # Параметры поиска пользователя
    address: str = Column(String(500), nullable=False)
    district: str = Column(String(200), nullable=True)
    rooms: str = Column(String(10), nullable=False)  # "studio", "1", "2", "3", "4+"
    total_area: Optional[float] = Column(Float, nullable=True)
    kitchen_area: Optional[float] = Column(Float, nullable=True)
    floor: Optional[int] = Column(Integer, nullable=True)
    total_floors: Optional[int] = Column(Integer, nullable=True)
    year_built: Optional[int] = Column(Integer, nullable=True)
    price: int = Column(Integer, nullable=False)

    # Фильтры
    area_tolerance: float = Column(Float, nullable=False, default=0.15)
    max_distance_km: float = Column(Float, nullable=False, default=2.0)
    search_depth: int = Column(Integer, nullable=False, default=10)

    # Координаты пользовательского адреса
    user_lat: Optional[float] = Column(Float, nullable=True)
    user_lon: Optional[float] = Column(Float, nullable=True)

    # Результаты (JSON для гибкости хранения)
    results_json: Optional[str] = Column(Text, nullable=True)
    analytics_json: Optional[str] = Column(Text, nullable=True)

    # Статус запроса
    status: str = Column(
        String(20), nullable=False, default="pending"
    )  # pending, processing, completed, error
    error_message: Optional[str] = Column(Text, nullable=True)
    analogs_count: int = Column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<SearchQuery(id={self.id}, address='{self.address}', "
            f"rooms='{self.rooms}', status='{self.status}')>"
        )


class CachedGeocode(Base):
    """
    Кеш результатов геокодирования.
    Хранит координаты для адресов, чтобы не обращаться к Nominatim повторно.
    """

    __tablename__ = "cached_geocodes"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    address: str = Column(String(500), unique=True, nullable=False, index=True)
    latitude: Optional[float] = Column(Float, nullable=True)
    longitude: Optional[float] = Column(Float, nullable=True)
    resolved: bool = Column(Boolean, nullable=False, default=False)
    created_at: datetime = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<CachedGeocode(address='{self.address}', "
            f"lat={self.latitude}, lon={self.longitude})>"
        )


class CachedListing(Base):
    """
    Кеш объявлений с Avito.
    Хранит распарсенные данные объявлений для снижения нагрузки.
    """

    __tablename__ = "cached_listings"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    avito_url: str = Column(String(1000), unique=True, nullable=False, index=True)
    created_at: datetime = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Данные объявления
    title: str = Column(String(500), nullable=True)
    rooms: Optional[str] = Column(String(10), nullable=True)
    address: Optional[str] = Column(String(500), nullable=True)
    price: Optional[int] = Column(Integer, nullable=True)
    total_area: Optional[float] = Column(Float, nullable=True)
    kitchen_area: Optional[float] = Column(Float, nullable=True)
    living_area: Optional[float] = Column(Float, nullable=True)
    floor: Optional[int] = Column(Integer, nullable=True)
    total_floors: Optional[int] = Column(Integer, nullable=True)
    house_type: Optional[str] = Column(String(100), nullable=True)
    year_built: Optional[int] = Column(Integer, nullable=True)

    # Координаты
    latitude: Optional[float] = Column(Float, nullable=True)
    longitude: Optional[float] = Column(Float, nullable=True)

    def to_dict(self) -> dict:
        """Конвертация в словарь для JSON-сериализации."""
        return {
            "title": self.title,
            "rooms": self.rooms,
            "address": self.address,
            "price": self.price,
            "total_area": self.total_area,
            "kitchen_area": self.kitchen_area,
            "living_area": self.living_area,
            "floor": self.floor,
            "total_floors": self.total_floors,
            "house_type": self.house_type,
            "year_built": self.year_built,
            "url": self.avito_url,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

    def __repr__(self) -> str:
        return f"<CachedListing(url='{self.avito_url[:50]}...', price={self.price})>"


# === Инициализация БД ===

def get_engine():
    """Создаёт и возвращает engine SQLAlchemy."""
    return create_engine(
        config.DATABASE_URL,
        echo=config.DEBUG,
        pool_pre_ping=True,
    )


def get_session_factory():
    """Возвращает фабрику сессий."""
    engine = get_engine()
    return sessionmaker(bind=engine)


def init_db() -> None:
    """
    Инициализирует базу данных — создаёт все таблицы.
    Вызывать при старте приложения.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)


def get_db_session() -> Session:
    """
    Создаёт и возвращает новую сессию БД.
    Используйте как контекстный менеджер или закрывайте вручную.
    """
    SessionFactory = get_session_factory()
    return SessionFactory()
