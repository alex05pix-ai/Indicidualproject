"""
Модуль геокодирования для приложения Квартира-Компаратор.
Использует Nominatim (OpenStreetMap) через geopy для:
- Преобразования адресов в координаты (широта, долгота)
- Расчёта расстояний между точками
- Кеширования результатов в БД
"""

import logging
import time
from typing import Optional, Tuple

from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from geopy.exc import (
    GeocoderTimedOut,
    GeocoderServiceError,
    GeocoderUnavailable,
)

from app.config import config
from app.models import CachedGeocode, get_db_session

logger = logging.getLogger(__name__)


class GeocoderService:
    """
    Сервис геокодирования с кешированием.
    Преобразует адреса Красноярска в координаты и вычисляет расстояния.
    """

    def __init__(self) -> None:
        """Инициализация геокодера Nominatim."""
        self._geolocator = Nominatim(
            user_agent=config.NOMINATIM_USER_AGENT,
            timeout=10,
        )
        self._last_request_time: float = 0.0
        # Nominatim требует минимум 1 секунду между запросами
        self._min_delay: float = 1.1

    def _rate_limit(self) -> None:
        """Ограничение частоты запросов к Nominatim (1 запрос/сек)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed)
        self._last_request_time = time.time()

    def _get_from_cache(self, address: str) -> Optional[Tuple[float, float]]:
        """
        Проверяет кеш геокодирования в БД.

        Args:
            address: Адрес для поиска в кеше.

        Returns:
            Кортеж (широта, долгота) или None, если адреса нет в кеше.
        """
        try:
            session = get_db_session()
            cached = (
                session.query(CachedGeocode)
                .filter(CachedGeocode.address == address)
                .first()
            )
            session.close()

            if cached and cached.resolved:
                logger.debug(f"Кеш-попадание для адреса: {address}")
                return (cached.latitude, cached.longitude)
            elif cached and not cached.resolved:
                logger.debug(f"Адрес в кеше, но не разрешён: {address}")
                return None
        except Exception as e:
            logger.warning(f"Ошибка чтения кеша геокодирования: {e}")
        return None

    def _save_to_cache(
        self, address: str, lat: Optional[float], lon: Optional[float], resolved: bool
    ) -> None:
        """
        Сохраняет результат геокодирования в кеш БД.

        Args:
            address: Исходный адрес.
            lat: Широта (может быть None при неудаче).
            lon: Долгота (может быть None при неудаче).
            resolved: True если адрес успешно геокодирован.
        """
        try:
            session = get_db_session()
            existing = (
                session.query(CachedGeocode)
                .filter(CachedGeocode.address == address)
                .first()
            )
            if existing:
                existing.latitude = lat
                existing.longitude = lon
                existing.resolved = resolved
            else:
                cached = CachedGeocode(
                    address=address,
                    latitude=lat,
                    longitude=lon,
                    resolved=resolved,
                )
                session.add(cached)
            session.commit()
            session.close()
        except Exception as e:
            logger.warning(f"Ошибка сохранения в кеш геокодирования: {e}")

    def geocode(self, address: str, city: str = None) -> Optional[Tuple[float, float]]:
        """
        Геокодирует адрес — преобразует в координаты (широта, долгота).

        Args:
            address: Адрес или ориентир (например, "ул. 9 Мая, 27").
            city: Город для уточнения (по умолчанию из конфига).

        Returns:
            Кортеж (latitude, longitude) или None при неудаче.
        """
        if city is None:
            city = config.CITY

        # Формируем полный адрес для запроса
        full_address = f"{address}, {city}, Россия"

        # Проверяем кеш
        cached = self._get_from_cache(full_address)
        if cached is not None:
            return cached

        # Выполняем геокодирование
        try:
            self._rate_limit()
            location = self._geolocator.geocode(
                full_address,
                exactly_one=True,
                language="ru",
            )

            if location:
                lat, lon = location.latitude, location.longitude
                logger.info(
                    f"Геокодирован адрес: '{full_address}' -> ({lat}, {lon})"
                )
                self._save_to_cache(full_address, lat, lon, resolved=True)
                return (lat, lon)
            else:
                # Пробуем без номера дома (только улицу)
                simplified = self._simplify_address(address, city)
                if simplified != full_address:
                    self._rate_limit()
                    location = self._geolocator.geocode(
                        simplified,
                        exactly_one=True,
                        language="ru",
                    )
                    if location:
                        lat, lon = location.latitude, location.longitude
                        logger.info(
                            f"Геокодирован упрощённый адрес: '{simplified}' -> ({lat}, {lon})"
                        )
                        self._save_to_cache(full_address, lat, lon, resolved=True)
                        return (lat, lon)

                logger.warning(f"Не удалось геокодировать адрес: '{full_address}'")
                self._save_to_cache(full_address, None, None, resolved=False)
                return None

        except GeocoderTimedOut:
            logger.error(f"Таймаут геокодирования для: '{full_address}'")
            return None
        except GeocoderServiceError as e:
            logger.error(f"Ошибка сервиса геокодирования: {e}")
            return None
        except GeocoderUnavailable as e:
            logger.error(f"Сервис геокодирования недоступен: {e}")
            return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка геокодирования: {e}")
            return None

    def _simplify_address(self, address: str, city: str) -> str:
        """
        Упрощает адрес, убирая номер дома/корпуса.

        Args:
            address: Исходный адрес.
            city: Город.

        Returns:
            Упрощённый адрес для повторной попытки.
        """
        import re
        # Убираем номер дома (цифры в конце после запятой)
        simplified = re.sub(r",?\s*\d+[а-яА-Я]?(/\d+)?$", "", address.strip())
        return f"{simplified}, {city}, Россия"

    def geocode_district(self, district_name: str) -> Optional[Tuple[float, float]]:
        """
        Возвращает координаты района/микрорайона Красноярска из предопределённого списка.

        Args:
            district_name: Название района или микрорайона.

        Returns:
            Кортеж (latitude, longitude) или None если не найдено.
        """
        # Проверяем микрорайоны
        if district_name in config.MICRODISTRICTS:
            info = config.MICRODISTRICTS[district_name]
            return (info["lat"], info["lon"])

        # Проверяем районы
        if district_name in config.DISTRICTS:
            info = config.DISTRICTS[district_name]
            return (info["lat"], info["lon"])

        # Пробуем геокодировать как обычный адрес
        logger.info(f"Район '{district_name}' не в списке, пробуем геокодировать")
        return self.geocode(f"{district_name} район")

    def calculate_distance(
        self,
        point1: Tuple[float, float],
        point2: Tuple[float, float],
    ) -> float:
        """
        Вычисляет расстояние между двумя точками в километрах.

        Args:
            point1: Кортеж (широта, долгота) первой точки.
            point2: Кортеж (широта, долгота) второй точки.

        Returns:
            Расстояние в километрах.
        """
        try:
            distance = geodesic(point1, point2).kilometers
            return round(distance, 3)
        except Exception as e:
            logger.error(f"Ошибка вычисления расстояния: {e}")
            return float("inf")

    def is_within_radius(
        self,
        point1: Tuple[float, float],
        point2: Tuple[float, float],
        max_distance_km: float = None,
    ) -> bool:
        """
        Проверяет, находится ли точка в пределах допустимого радиуса.

        Args:
            point1: Координаты целевого объекта.
            point2: Координаты аналога.
            max_distance_km: Максимальное расстояние (км). По умолчанию из конфига.

        Returns:
            True если точки в пределах радиуса.
        """
        if max_distance_km is None:
            max_distance_km = config.DEFAULT_MAX_DISTANCE_KM

        distance = self.calculate_distance(point1, point2)
        return distance <= max_distance_km

    def resolve_user_location(
        self, address: str, district: Optional[str] = None
    ) -> Optional[Tuple[float, float]]:
        """
        Определяет координаты пользователя по адресу и/или району.
        Стратегия: сначала пробуем полный адрес, затем район, потом центр города.

        Args:
            address: Адрес квартиры пользователя.
            district: Район/микрорайон (опционально).

        Returns:
            Кортеж (latitude, longitude) или координаты центра города как fallback.
        """
        # Попытка 1: полный адрес
        coords = self.geocode(address)
        if coords:
            return coords

        # Попытка 2: район/микрорайон
        if district:
            coords = self.geocode_district(district)
            if coords:
                logger.info(
                    f"Используем координаты района '{district}' вместо адреса"
                )
                return coords

        # Fallback: центр города
        logger.warning(
            f"Не удалось определить координаты для '{address}', "
            f"используем центр города"
        )
        return (config.CITY_LAT, config.CITY_LON)

    def get_district_for_microdistrict(self, microdistrict: str) -> Optional[str]:
        """
        Определяет район по микрорайону.

        Args:
            microdistrict: Название микрорайона.

        Returns:
            Название района или None.
        """
        if microdistrict in config.MICRODISTRICTS:
            return config.MICRODISTRICTS[microdistrict].get("district")
        return None


# Глобальный экземпляр сервиса (singleton)
geocoder_service = GeocoderService()
