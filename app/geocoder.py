"""Геокодирование адресов и расчёт расстояний.

Используется ``geopy.Nominatim`` (OpenStreetMap). Все запросы кешируются в БД,
чтобы не упираться в лимит Nominatim (1 RPS) и не делать одинаковых запросов.

Сетевые ошибки обрабатываются с retry/backoff.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from geopy.distance import geodesic
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from .config import settings
from .models import GeocodeCache, db

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeoPoint:
    """Точка на карте."""

    latitude: float
    longitude: float
    display_name: Optional[str] = None

    @property
    def coords(self) -> tuple[float, float]:
        return (self.latitude, self.longitude)


class Geocoder:
    """Обёртка над Nominatim с кешем в БД и потокобезопасным доступом."""

    _LOCK = threading.Lock()

    def __init__(self, user_agent: Optional[str] = None, timeout: Optional[int] = None):
        self.user_agent = user_agent or settings.nominatim_user_agent
        self.timeout = timeout or settings.geocode_timeout
        self._client = Nominatim(user_agent=self.user_agent, timeout=self.timeout)

    @staticmethod
    def _normalize(address: str) -> str:
        return " ".join(address.strip().lower().split())

    def geocode(self, address: str, *, city_hint: Optional[str] = None) -> Optional[GeoPoint]:
        """Геокодирует адрес. Возвращает ``None`` если не удалось.

        Args:
            address: адрес или название микрорайона.
            city_hint: опциональное название города (например, «Красноярск»).
        """
        if not address:
            return None

        query = address.strip()
        if city_hint and city_hint.lower() not in query.lower():
            query = f"{query}, {city_hint}"

        normalized = self._normalize(query)

        # Сначала проверяем кеш в БД
        try:
            cached = GeocodeCache.query.filter_by(address=normalized).first()
        except Exception as e:  # noqa: BLE001 — БД могла быть не инициализирована
            logger.debug("GeocodeCache lookup failed: %s", e)
            cached = None

        if cached:
            return GeoPoint(cached.latitude, cached.longitude, cached.display_name)

        # Запрос к Nominatim под глобальным lock-ом (Nominatim требует ~1 RPS)
        with self._LOCK:
            try:
                location = self._client.geocode(query, addressdetails=False, language="ru")
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                logger.warning("Geocoder error for %r: %s", query, e)
                return None
            except Exception as e:  # noqa: BLE001
                logger.exception("Unexpected geocoder error for %r: %s", query, e)
                return None

        if not location:
            logger.info("Address not found: %r", query)
            return None

        point = GeoPoint(
            latitude=location.latitude,
            longitude=location.longitude,
            display_name=location.address,
        )

        # Сохраняем в кеш (best-effort)
        try:
            entry = GeocodeCache(
                address=normalized,
                latitude=point.latitude,
                longitude=point.longitude,
                display_name=point.display_name,
            )
            db.session.add(entry)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug("Failed to save geocode cache: %s", e)
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass

        return point

    @staticmethod
    def distance_km(a: GeoPoint, b: GeoPoint) -> float:
        """Возвращает расстояние между двумя точками в километрах."""
        return geodesic(a.coords, b.coords).km


# Глобальный singleton-геокодер
_geocoder_instance: Optional[Geocoder] = None
_geocoder_lock = threading.Lock()


def get_geocoder() -> Geocoder:
    """Возвращает глобальный экземпляр Geocoder (lazy)."""
    global _geocoder_instance
    if _geocoder_instance is None:
        with _geocoder_lock:
            if _geocoder_instance is None:
                _geocoder_instance = Geocoder()
    return _geocoder_instance
