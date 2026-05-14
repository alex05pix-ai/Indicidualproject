"""Unit-тесты для модуля avito_parser (без Playwright/сети)."""

from __future__ import annotations

import pytest

from app.avito_parser import (
    AvitoParser,
    SearchParams,
    detect_rooms,
    parse_area,
    parse_floor,
    parse_price,
    parse_year,
)


# ---------- parse_price ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5 200 000 ₽", 5_200_000),
        ("5\u00a0200\u00a0000 ₽", 5_200_000),
        ("5200000 руб.", 5_200_000),
        ("12 345", 12_345),  # fallback
        ("Цена не указана", None),
        ("", None),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


# ---------- parse_area ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1-к. квартира, 42 м², 5/9 эт.", 42.0),
        ("Студия, 23,5 м²", 23.5),
        ("Загородный дом", None),
    ],
)
def test_parse_area(raw, expected):
    assert parse_area(raw) == expected


# ---------- parse_floor ----------

def test_parse_floor_basic():
    floor, total = parse_floor("Квартира на 5/9 эт.")
    assert floor == 5 and total == 9


def test_parse_floor_missing():
    assert parse_floor("без этажа") == (None, None)


# ---------- parse_year ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Год постройки: 2010", 2010),
        ("год постройки 1985", 1985),
        ("О доме — постройки 2024", 2024),
        ("Год постройки 1700", None),  # вне допустимого диапазона
        ("нет года", None),
    ],
)
def test_parse_year(raw, expected):
    assert parse_year(raw) == expected


# ---------- detect_rooms ----------

@pytest.mark.parametrize(
    "title, expected_key",
    [
        ("Студия, 25 м², 12/16 эт.", "studio"),
        ("1-к. квартира, 38 м²", "1"),
        ("2-к квартира, 56 м²", "2"),
        ("3-к. квартира, 80 м²", "3"),
        ("4-к. квартира, 110 м²", "4plus"),
        ("5-к. квартира, 140 м²", "4plus"),
        ("комната в общежитии, 12 м²", None),
    ],
)
def test_detect_rooms(title, expected_key):
    key, _raw = detect_rooms(title)
    assert key == expected_key


# ---------- AvitoParser.build_search_url ----------

def test_build_search_url_studio():
    params = SearchParams(rooms="studio", address="мкр. Северный")
    url = AvitoParser.build_search_url(params)
    assert "krasnoyarsk/kvartiry/prodam/studii" in url


def test_build_search_url_1room_with_pagination_and_price():
    params = SearchParams(rooms="1", address="ул. 9 Мая, 27", price=5_000_000)
    url = AvitoParser.build_search_url(params, page=3)
    assert "1-komnatnye" in url
    assert "p=3" in url
    assert "pmin=" in url and "pmax=" in url


def test_build_search_url_4plus_uses_4_komnatnye():
    params = SearchParams(rooms="4plus", address="Покровка")
    url = AvitoParser.build_search_url(params)
    assert "4-komnatnye" in url


# ---------- AvitoParser._parse_search_page ----------

def test_parse_search_page_filters_room_count():
    """В выдаче находим карточку с подходящими комнатами и отбрасываем чужие."""
    html = """
    <html><body>
      <div data-marker="item">
        <a data-marker="item-title" href="/krasnoyarsk/kvartiry/foo_111">
          1-к. квартира, 38 м², 5/9 эт.
        </a>
        <span data-marker="item-price">4 500 000 ₽</span>
        <div data-marker="item-address">мкр. Северный</div>
      </div>
      <div data-marker="item">
        <a data-marker="item-title" href="/krasnoyarsk/kvartiry/bar_222">
          2-к. квартира, 60 м², 3/5 эт.
        </a>
        <span data-marker="item-price">6 200 000 ₽</span>
      </div>
      <div data-marker="item">
        <a data-marker="item-title" href="/krasnoyarsk/kvartiry/baz_333">
          Студия, 23 м²
        </a>
        <span data-marker="item-price">2 800 000 ₽</span>
      </div>
    </body></html>
    """
    parser = AvitoParser.__new__(AvitoParser)  # без Playwright
    params = SearchParams(rooms="1", address="мкр. Северный")
    items = parser._parse_search_page(html, params)
    assert len(items) == 1
    item = items[0]
    assert item.rooms == "1"
    assert item.price == 4_500_000
    assert item.total_area == 38.0
    assert "Северный" in (item.address or "")
    assert item.url.startswith("https://www.avito.ru")


def test_parse_search_page_studio_filter():
    html = """
    <html><body>
      <div data-marker="item">
        <a data-marker="item-title" href="/krasnoyarsk/kvartiry/s1">Студия, 22 м²</a>
        <span data-marker="item-price">2 500 000 ₽</span>
      </div>
      <div data-marker="item">
        <a data-marker="item-title" href="/krasnoyarsk/kvartiry/s2">1-к. квартира, 30 м²</a>
        <span data-marker="item-price">3 500 000 ₽</span>
      </div>
    </body></html>
    """
    parser = AvitoParser.__new__(AvitoParser)
    items = parser._parse_search_page(html, SearchParams(rooms="studio", address="x"))
    assert [i.rooms for i in items] == ["studio"]
