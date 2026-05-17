"""
Модуль парсинга Avito — Playwright (headless Chromium) + BeautifulSoup.
Для корректной работы нужен установленный Chromium: playwright install chromium
"""

import asyncio
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable

from bs4 import BeautifulSoup

from app.config import config

logger = logging.getLogger(__name__)


class AvitoParser:
    """Парсер объявлений Avito через Playwright (headless browser)."""

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
        """Парсит HTML страницы поисковой выдачи."""
        soup = BeautifulSoup(html, "lxml")
        listings = []

        # Ищем карточки объявлений (разные селекторы для разных версий Avito)
        items = soup.select('[data-marker="item"]')
        if not items:
            items = soup.select('[class*="iva-item"]')
        if not items:
            items = soup.select('[itemtype="http://schema.org/Product"]')

        for item in items:
            try:
                listing = {}

                # Заголовок и ссылка
                link = item.select_one('a[href*="/kvartiry/"]')
                if not link:
                    link = item.select_one('[itemprop="url"]')
                if not link:
                    link = item.select_one("a[href*='_']")
                if not link:
                    continue

                title_el = link.select_one("h3") or link.select_one('[itemprop="name"]') or link
                listing["title"] = title_el.get_text(strip=True) if title_el else ""
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
                    if not price_el:
                        price_el = item.select_one('[class*="price"]')
                    if price_el:
                        listing["price"] = self._parse_price(price_el.get_text())

                # Адрес
                addr_el = item.select_one('[data-marker="item-address"]')
                if not addr_el:
                    addr_el = item.select_one('[class*="geo-address"]')
                if not addr_el:
                    addr_el = item.select_one('[class*="address"]')
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

    async def _parse_async(self) -> List[Dict]:
        """Асинхронный парсинг через Playwright."""
        from playwright.async_api import async_playwright

        results = []

        try:
            from playwright_stealth import stealth_async
            has_stealth = True
        except ImportError:
            has_stealth = False

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

            context = await browser.new_context(
                user_agent=random.choice(config.USER_AGENTS),
                viewport=random.choice(config.VIEWPORTS),
                locale="ru-RU",
            )

            page = await context.new_page()

            if has_stealth:
                await stealth_async(page)

            for page_num in range(1, self.max_pages + 1):
                if len(results) >= self.max_analogs:
                    break

                url = self._build_search_url(page_num)
                self._report_progress(
                    page_num * 20, 100,
                    f"Загрузка страницы {page_num}..."
                )
                logger.info(f"Playwright: {url}")

                try:
                    # Случайная задержка
                    await asyncio.sleep(random.uniform(
                        config.PARSER_MIN_DELAY, config.PARSER_MAX_DELAY
                    ))

                    response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                    if response and response.status == 429:
                        logger.warning("HTTP 429, пауза 30 сек...")
                        await asyncio.sleep(30)
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                    # Ждём появления контента
                    await asyncio.sleep(random.uniform(3, 5))

                    # Проверка на капчу
                    content = await page.content()
                    if "captcha" in content.lower() or "challenge" in content.lower():
                        logger.warning("Обнаружена капча, пауза 15 сек...")
                        await asyncio.sleep(15)
                        await page.reload()
                        await asyncio.sleep(5)
                        content = await page.content()

                    # Парсим HTML
                    page_listings = self._parse_listing_page(content)
                    logger.info(f"Стр. {page_num}: {len(page_listings)} объявлений")
                    results.extend(page_listings)

                    # Задержка между страницами
                    if page_num < self.max_pages:
                        await asyncio.sleep(random.uniform(
                            config.PARSER_PAGE_DELAY_MIN, config.PARSER_PAGE_DELAY_MAX
                        ))

                except Exception as e:
                    logger.error(f"Ошибка на стр. {page_num}: {e}")
                    continue

            await browser.close()

        self._report_progress(100, 100, "Парсинг завершён!")
        return results[:self.max_analogs]

    def parse(self) -> List[Dict]:
        """Синхронный запуск парсера."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._parse_async())
        finally:
            loop.close()


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
    """Парсит одно объявление по URL через Playwright."""

    async def _parse():
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import stealth_async
            has_stealth = True
        except ImportError:
            has_stealth = False

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=random.choice(config.USER_AGENTS),
                locale="ru-RU",
            )
            page = await context.new_page()
            if has_stealth:
                await stealth_async(page)

            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            details = {"url": url}

            # Заголовок
            h1 = soup.select_one("h1")
            if h1:
                title = h1.get_text(strip=True)
                details["title"] = title
                parser = AvitoParser(rooms="1")
                details["rooms"] = parser._extract_rooms_from_title(title)
                details.update(parser._extract_area_from_title(title))
                details.update(parser._extract_floor_from_title(title))

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

            await browser.close()
            return details if details.get("price") else None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_parse())
    except Exception as e:
        logger.error(f"Ошибка парсинга {url}: {e}")
        return None
    finally:
        loop.close()
