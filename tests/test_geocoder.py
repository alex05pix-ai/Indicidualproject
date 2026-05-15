"""
Тесты модуля геокодирования.
"""

import pytest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.geocoder import GeocoderService
from app.config import config


class TestGeocoderService:
    """Тесты для GeocoderService."""

    def setup_method(self):
        """Подготовка к каждому тесту."""
        self.geocoder = GeocoderService()

    def test_calculate_distance_same_point(self):
        """Расстояние между одной и той же точкой должно быть 0."""
        point = (56.0153, 92.8932)
        distance = self.geocoder.calculate_distance(point, point)
        assert distance == 0.0

    def test_calculate_distance_known_points(self):
        """Расстояние между двумя известными точками Красноярска."""
        # Центр -> Советский район (~3 км)
        center = (56.0101, 92.8714)
        sovetsky = (56.0341, 92.8598)
        distance = self.geocoder.calculate_distance(center, sovetsky)
        assert 2.0 < distance < 4.0

    def test_calculate_distance_invalid_input(self):
        """Ошибка при невалидных координатах возвращает inf."""
        distance = self.geocoder.calculate_distance((None, None), (56.0, 92.0))
        assert distance == float("inf")

    def test_is_within_radius_true(self):
        """Точки в пределах радиуса."""
        point1 = (56.0153, 92.8932)
        point2 = (56.0160, 92.8940)  # Очень близко
        assert self.geocoder.is_within_radius(point1, point2, max_distance_km=1.0)

    def test_is_within_radius_false(self):
        """Точки за пределами радиуса."""
        point1 = (56.0153, 92.8932)
        point2 = (56.1000, 92.5000)  # Далеко
        assert not self.geocoder.is_within_radius(point1, point2, max_distance_km=2.0)

    def test_geocode_district_known(self):
        """Геокодирование известного района из конфига."""
        coords = self.geocoder.geocode_district("Советский")
        assert coords is not None
        assert coords == (56.0341, 92.8598)

    def test_geocode_district_microdistrict(self):
        """Геокодирование микрорайона из конфига."""
        coords = self.geocoder.geocode_district("Взлётка")
        assert coords is not None
        assert coords == (56.0401, 92.8891)

    def test_geocode_district_unknown(self):
        """Неизвестный район — попытка геокодировать через API."""
        with patch.object(self.geocoder, 'geocode', return_value=None):
            coords = self.geocoder.geocode_district("НесуществующийРайон123")
            assert coords is None

    def test_get_district_for_microdistrict(self):
        """Определение района по микрорайону."""
        district = self.geocoder.get_district_for_microdistrict("Северный")
        assert district == "Советский"

    def test_get_district_for_microdistrict_unknown(self):
        """Неизвестный микрорайон возвращает None."""
        district = self.geocoder.get_district_for_microdistrict("Неизвестный")
        assert district is None

    def test_resolve_user_location_with_district_fallback(self):
        """Fallback на район если адрес не геокодирован."""
        with patch.object(self.geocoder, 'geocode', return_value=None):
            coords = self.geocoder.resolve_user_location(
                "несуществующий адрес 999",
                district="Советский"
            )
            assert coords == (56.0341, 92.8598)

    def test_resolve_user_location_city_fallback(self):
        """Fallback на центр города если ничего не найдено."""
        with patch.object(self.geocoder, 'geocode', return_value=None):
            coords = self.geocoder.resolve_user_location(
                "несуществующий адрес",
                district=None
            )
            assert coords == (config.CITY_LAT, config.CITY_LON)

    def test_simplify_address(self):
        """Упрощение адреса — удаление номера дома."""
        simplified = self.geocoder._simplify_address(
            "ул. 9 Мая, 27", "Красноярск"
        )
        assert "27" not in simplified
        assert "Красноярск" in simplified


class TestGeocoderCache:
    """Тесты кеширования геокодирования."""

    def setup_method(self):
        self.geocoder = GeocoderService()

    @patch('app.geocoder.get_db_session')
    def test_get_from_cache_miss(self, mock_session):
        """Кеш-промах возвращает None."""
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        mock_session.return_value = session

        result = self.geocoder._get_from_cache("unknown address")
        assert result is None

    @patch('app.geocoder.get_db_session')
    def test_get_from_cache_hit(self, mock_session):
        """Кеш-попадание возвращает координаты."""
        cached = MagicMock()
        cached.resolved = True
        cached.latitude = 56.01
        cached.longitude = 92.89

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = cached
        mock_session.return_value = session

        result = self.geocoder._get_from_cache("known address")
        assert result == (56.01, 92.89)
