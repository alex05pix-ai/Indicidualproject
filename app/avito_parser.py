"""
Модуль парсинга Avito — упрощённая версия на requests + BeautifulSoup.
Без Playwright/Chromium для лёгкого деплоя.
"""

import logging
import random
import re
import time
from typing import Dict, List, Optional, Callable

import requests
from bs4 import BeautifulSoup

from app.config import config

logger = logging.getLogger(__name__)


class AvitoParser:
    """
    Парсер объявлений Avito на requests + BeautifulSoup.
    """

    BASE_URL = "https://www.avito.ru"
    CITY_SLUG = "krasnoyarsk"

    ROOMS_URL_MAP = {
        "studio": "studii",
        "1": "1-komnatnye",
        "2": "2-komnatnye",
        "3": "3-komnatnye",
        "4+": "4-komnatnye",
    }

    def __init__(
        self,
        rooms: str,
        district: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        min_area: Optional[float] = None,
        max_area: Optional[float] = None,
        max_analogs: int = None,
        max_pages: int = None,
        progress_callback: Optional[Callable] = None,
    ) -> None:
        self.rooms = rooms
        self.district = district
        self.min_price = min_price
        self.max_price = max_price
        self.min_area = min_area
        self.max_area = max_area
        self.max_analogs = max_analogs or config.PARSER_MAX_ANALOGS
        self.max_pages = max_pages or config.PARSER_MAX_PAGES
        self.progress_callback = progress_callback
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })

    def _build_search_url(self, page: int = 1) -> str:
        """Формирует URL поиска."""
        rooms_segment = self.ROOMS_URL_MAP.get(self.rooms, "1-komnatnye")
        url = f"{self.BASE_URL}/{self.CITY_SLUG}/kvartiry/prodam/{rooms_segment}"
        params = []
        if self.min_price:
            params.append(f"pmin={self.min_price}")
        if self.max_price:
            params.append(f"pmax={self.max_price}")
        if page > 1:
            params.append(f"p={page}")
        if params:
            url += "?" + "&".join(params)
        return url

    def _report_progress(self, current: int, total: int, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(current, total, message)

    def _random_delay(self) -> None:
        """Случайная задержка между запросами."""
        delay = random.uniform(config.PARSER_MIN_DELAY, config.PARSER_MAX_DELAY)
        time.sleep(delay)

    def _extract_rooms_from_title(self, title: str) -> Optional[str]:
        title_lower = title.lower()
        if "студия" in title_lower or "студию" in title_lower:
            return "studio"
        match = re.search(r"(\d+)[- ]?к(?:омн|\.)?", title_lower)
        if match:
            return match.group(1)
        return None

    def _extract_area_from_title(self, title: str) -> Dict:
        result = {}
        areas_match = re.search(
            r"(\d+[.,]?\d*)\s*/\s*(\d+[.,]?\d*)\s*/\s*(\d+[.,]?\d*)", title
        )
        if areas_match:
            result["total_area"] = float(areas_match.group(1).replace(",", "."))
            result["living_area"] = float(areas_match.group(2).replace(",", "."))
            result["kitchen_area"] = float(areas_match.group(3).replace(",", "."))
        else:
            area_match = re.search(r"(\d+[.,]?\d*)\s*м", title)
            if area_match:
                result["total_area"] = float(area_match.group(1).replace(",", "."))
        return result

    def _extract_floor_from_title(self, title: str) -> Dict:
        result = {}
        match = re.search(r"(\d+)/(\d+)\s*(?:эт|этаж)", title)
        if match:
            result["floor"] = int(match.group(1))
            result["total_floors"] = int(match.group(2))
        return result

    def _parse_price(self, price_str: str) -> Optional[int]:
        if not price_str:
            return None
        digits = re.sub(r"[^\d]", "", price_str)
        return int(digits) if digits else None

    def _parse_listing_page(self, html: str) -> List[Dict]:
        """Парсит страницу поисковой выдачи."""
        soup = BeautifulSoup(html, "lxml")
        listings = []

        # Ищем карточки
        items = soup.select('[data-marker="item"]')
        if not items:
            items = soup.select('[class*="iva-item"]')

        for item in items:
            try:
                listing = {}

                # Заголовок и ссылка
                link = item.select_one("a[href*='/kvartiry/']")
                if not link:
                    link = item.select_one("a[itemprop='url']")
                if not link:
                    continue

                listing["title"] = link.get_text(strip=True)
                href = link.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE_URL + href
                listing["url"] = href

                # Цена
                price_el = item.select_one('[itemprop="price"]')
                if price_el:
                    listing["price"] = self._parse_price(
                        price_el.get("content") or price_el.get_text()
                    )
                else:
                    price_el = item.select_one('[data-marker="item-price"]')
                    if price_el:
                        listing["price"] = self._parse_price(price_el.get_text())

                # Адрес
                addr_el = item.select_one('[data-marker="item-address"]')
                if not addr_el:
                    addr_el = item.select_one('[class*="geo-address"]')
                if addr_el:
                    listing["address"] = addr_el.get_text(strip=True)

                # Из заголовка
                title = listing.get("title", "")
                listing["rooms"] = self._extract_rooms_from_title(title)
                listing.update(self._extract_area_from_title(title))
                listing.update(self._extract_floor_from_title(title))

                if listing.get("price"):
                    listings.append(listing)

            except Exception as e:
                logger.debug(f"Ошибка парсинга карточки: {e}")
                continue

        return listings

    def parse(self) -> List[Dict]:
        """Основной метод — собирает объявления."""
        results = []

        for page_num in range(1, self.max_pages + 1):
            if len(results) >= self.max_analogs:
                break

            url = self._build_search_url(page_num)
            self._report_progress(
                page_num * 20, 100,
                f"Загрузка страницы {page_num}..."
            )
            logger.info(f"Запрос: {url}")

            try:
                self._random_delay()
                resp = self._session.get(url, timeout=30)

                if resp.status_code == 429:
                    logger.warning("HTTP 429 — пауза 30 сек")
                    time.sleep(30)
                    resp = self._session.get(url, timeout=30)

                if resp.status_code != 200:
                    logger.error(f"HTTP {resp.status_code} для {url}")
                    continue

                page_listings = self._parse_listing_page(resp.text)
                logger.info(f"Стр. {page_num}: {len(page_listings)} объявлений")
                results.extend(page_listings)

            except requests.RequestException as e:
                logger.error(f"Ошибка запроса: {e}")
                continue

        self._report_progress(100, 100, "Парсинг завершён!")
        return results[: self.max_analogs]


def run_parser(
    rooms: str,
    district: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    max_analogs: int = None,
    max_pages: int = None,
    progress_callback: Optional[Callable] = None,
) -> List[Dict]:
    """Синхронная обёртка для запуска парсера."""
    parser = AvitoParser(
        rooms=rooms,
        district=district,
        min_price=min_price,
        max_price=max_price,
        min_area=min_area,
        max_area=max_area,
        max_analogs=max_analogs,
        max_pages=max_pages,
        progress_callback=progress_callback,
    )
    return parser.parse()


def run_parse_single(url: str) -> Optional[Dict]:
    """Парсит одно объявление по URL."""
    try:
        headers = {
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        details = {"url": url}

        # Заголовок
        h1 = soup.select_one("h1")
        if h1:
            title = h1.get_text(strip=True)
            details["title"] = title
            rooms = AvitoParser(rooms="1")._extract_rooms_from_title(title)
            if rooms:
                details["rooms"] = rooms
            details.update(AvitoParser(rooms="1")._extract_area_from_title(title))
            details.update(AvitoParser(rooms="1")._extract_floor_from_title(title))

        # Цена
        price_el = soup.select_one('[itemprop="price"]')
        if price_el:
            val = price_el.get("content") or price_el.get_text()
            digits = re.sub(r"[^\d]", "", str(val))
            if digits:
                details["price"] = int(digits)

        # Адрес
        addr_el = soup.select_one('[class*="item-address"]')
        if not addr_el:
            addr_el = soup.select_one('[data-marker="item-view/item-address"]')
        if addr_el:
            details["address"] = addr_el.get_text(strip=True)

        return details if details.get("price") else None

    except Exception as e:
        logger.error(f"Ошибка парсинга {url}: {e}")
        return None
