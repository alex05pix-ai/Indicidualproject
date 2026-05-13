"""
Геокодирование адресов и расчёт расстояний.

Используется бесплатный провайдер Nominatim (OpenStreetMap) через
библиотеку geopy. Все ответы кешируются в SQLite (см. models.GeocodeCache),
чтобы не нарушать политику Nominatim (1 запрос/сек) и не геокодировать
один и тот же адрес повторно.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from geopy.distance import geodesic
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

import config
from models import GeocodeCache, get_session

log = logging.getLogger(__name__)

# Глобальный экземпляр геокодера. Nominatim требует уникальный user_agent.
_geocoder = Nominatim(
    user_agent=config.GEOCODER_USER_AGENT,
    timeout=config.GEOCODER_TIMEOUT_SEC,
)


def _normalize(query: str) -> str:
    """Привести адрес к каноничному виду для использования в качестве ключа."""
    return " ".join(query.lower().strip().split())


def _ensure_city(query: str) -> str:
    """Добавить «Красноярск», если он не упомянут — это сильно повышает
    качество геокодирования по микрорайонам ("Северный" -> "Северный, Красноярск").
    """
    q = query.strip()
    if config.CITY_NAME.lower() not in q.lower() and "krasnoyarsk" not in q.lower():
        q = f"{q}, {config.CITY_NAME}"
    return q


def geocode(address: str) -> Optional[tuple[float, float]]:
    """Геокодировать адрес, возвращая (lat, lon) или None.

    * Сначала ищем в кеше БД.
    * Если нет — обращаемся к Nominatim.
    * При сетевых ошибках возвращаем None и пишем в лог.
    """
    if not address or not address.strip():
        return None

    query = _ensure_city(address)
    key = _normalize(query)

    session = get_session()
    try:
        cached = (
            session.query(GeocodeCache).filter(GeocodeCache.query == key).one_or_none()
        )
        if cached is not None:
            if cached.latitude is None or cached.longitude is None:
                return None
            return (cached.latitude, cached.longitude)

        # Реальный запрос к Nominatim. Соблюдаем вежливое 1 req/sec.
        time.sleep(1.0)
        try:
            location = _geocoder.geocode(query, language="ru", addressdetails=False)
        except (GeocoderTimedOut, GeocoderServiceError) as exc:
            log.warning("Geocoder error for %r: %s", query, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — защита от падения
            log.exception("Unexpected geocoder error for %r: %s", query, exc)
            return None

        if location is None:
            # Сохраняем «отсутствие» тоже, чтобы не долбиться повторно.
            session.add(
                GeocodeCache(
                    query=key,
                    latitude=None,
                    longitude=None,
                    display_name=None,
                )
            )
            session.commit()
            return None

        session.add(
            GeocodeCache(
                query=key,
                latitude=location.latitude,
                longitude=location.longitude,
                display_name=location.address,
            )
        )
        session.commit()
        return (location.latitude, location.longitude)
    finally:
        session.close()


def distance_km(
    a: Optional[tuple[float, float]],
    b: Optional[tuple[float, float]],
) -> Optional[float]:
    """Расстояние по поверхности Земли (км) между двумя точками."""
    if a is None or b is None:
        return None
    try:
        return float(geodesic(a, b).kilometers)
    except Exception as exc:  # noqa: BLE001
        log.warning("Distance computation failed: %s", exc)
        return None
