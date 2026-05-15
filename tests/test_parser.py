"""
Тесты модуля парсера Avito.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.avito_parser import AvitoParser


class TestAvitoParserURL:
    """Тесты формирования URL поиска."""

    def test_build_url_studio(self):
        """URL для студий."""
        parser = AvitoParser(rooms="studio")
        url = parser._build_search_url(page=1)
        assert "studii" in url
        assert "krasnoyarsk" in url

    def test_build_url_1_room(self):
        """URL для 1-комнатных."""
        parser = AvitoParser(rooms="1")
        url = parser._build_search_url(page=1)
        assert "1-komnatnye" in url

    def test_build_url_2_rooms(self):
        """URL для 2-комнатных."""
        parser = AvitoParser(rooms="2")
        url = parser._build_search_url(page=1)
        assert "2-komnatnye" in url

    def test_build_url_3_rooms(self):
        """URL для 3-комнатных."""
        parser = AvitoParser(rooms="3")
        url = parser._build_search_url(page=1)
        assert "3-komnatnye" in url

    def test_build_url_4_plus(self):
        """URL для 4+ комнатных."""
        parser = AvitoParser(rooms="4+")
        url = parser._build_search_url(page=1)
        assert "4-komnatnye" in url

    def test_build_url_with_price(self):
        """URL с ценовым фильтром."""
        parser = AvitoParser(rooms="2", min_price=2000000, max_price=5000000)
        url = parser._build_search_url(page=1)
        assert "pmin=2000000" in url
        assert "pmax=5000000" in url

    def test_build_url_pagination(self):
        """URL с пагинацией."""
        parser = AvitoParser(rooms="1")
        url = parser._build_search_url(page=3)
        assert "p=3" in url

    def test_build_url_page_1_no_param(self):
        """Первая страница не добавляет параметр p."""
        parser = AvitoParser(rooms="1")
        url = parser._build_search_url(page=1)
        assert "p=" not in url


class TestAvitoParserExtraction:
    """Тесты извлечения данных из заголовков."""

    def setup_method(self):
        self.parser = AvitoParser(rooms="2")

    def test_extract_rooms_from_title_1k(self):
        """Извлечение 1 комнаты из заголовка."""
        assert self.parser._extract_rooms_from_title("1-к. квартира, 35 м²") == "1"

    def test_extract_rooms_from_title_2k(self):
        """Извлечение 2 комнат из заголовка."""
        assert self.parser._extract_rooms_from_title("2-к. квартира, 65 м²") == "2"

    def test_extract_rooms_from_title_studio(self):
        """Извлечение студии из заголовка."""
        assert self.parser._extract_rooms_from_title("Студия, 28 м²") == "studio"

    def test_extract_rooms_from_title_none(self):
        """Нет информации о комнатах в заголовке."""
        assert self.parser._extract_rooms_from_title("Квартира в центре") is None

    def test_extract_area_from_title_simple(self):
        """Извлечение площади из заголовка."""
        result = self.parser._extract_area_from_title("2-к. квартира, 65 м²")
        assert result.get("total_area") == 65.0

    def test_extract_area_from_title_full(self):
        """Извлечение всех площадей (общая/жилая/кухня)."""
        result = self.parser._extract_area_from_title("2-к. кв, 65/40/10 м²")
        assert result.get("total_area") == 65.0
        assert result.get("living_area") == 40.0
        assert result.get("kitchen_area") == 10.0

    def test_extract_floor_from_title(self):
        """Извлечение этажа."""
        result = self.parser._extract_floor_from_title("2-к. кв, 5/10 эт.")
        assert result.get("floor") == 5
        assert result.get("total_floors") == 10

    def test_extract_floor_from_title_missing(self):
        """Нет информации об этаже."""
        result = self.parser._extract_floor_from_title("Квартира в центре")
        assert result == {}

    def test_parse_price_simple(self):
        """Парсинг простой цены."""
        assert self.parser._parse_price("4500000") == 4500000

    def test_parse_price_with_spaces(self):
        """Парсинг цены с пробелами."""
        assert self.parser._parse_price("4 500 000 ₽") == 4500000

    def test_parse_price_with_currency(self):
        """Парсинг цены с символом валюты."""
        assert self.parser._parse_price("4 500 000 руб.") == 4500000

    def test_parse_price_none(self):
        """Пустая строка цены."""
        assert self.parser._parse_price("") is None
        assert self.parser._parse_price(None) is None


class TestAvitoParserValidation:
    """Тесты валидации комнат."""

    def test_validate_rooms_exact_match(self):
        """Точное совпадение количества комнат."""
        parser = AvitoParser(rooms="2")
        assert parser._validate_rooms({"rooms": "2"})

    def test_validate_rooms_mismatch(self):
        """Несовпадение количества комнат."""
        parser = AvitoParser(rooms="2")
        assert not parser._validate_rooms({"rooms": "3"})

    def test_validate_rooms_studio(self):
        """Валидация студии."""
        parser = AvitoParser(rooms="studio")
        assert parser._validate_rooms({"rooms": "студия"})
        assert parser._validate_rooms({"rooms": "studio"})
        assert not parser._validate_rooms({"rooms": "1"})

    def test_validate_rooms_4_plus(self):
        """Валидация 4+ комнат."""
        parser = AvitoParser(rooms="4+")
        assert parser._validate_rooms({"rooms": "4"})
        assert parser._validate_rooms({"rooms": "5"})
        assert not parser._validate_rooms({"rooms": "3"})

    def test_validate_rooms_empty(self):
        """Пустое значение — пропускаем (True)."""
        parser = AvitoParser(rooms="2")
        assert parser._validate_rooms({"rooms": ""})
        assert parser._validate_rooms({"rooms": None})
        assert parser._validate_rooms({})
