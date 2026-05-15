"""
Модуль парсинга Avito для приложения Квартира-Компаратор.
Использует Playwright (headless Chromium) + BeautifulSoup для сбора
объявлений о продаже квартир в Красноярске.

Включает антибан-меры: stealth, случайные задержки, ротация User-Agent.
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
    """
    Асинхронный парсер объявлений Avito.
    Собирает данные о квартирах по заданным параметрам поиска.
    """

    BASE_URL = "https://www.avito.ru"
    CITY_SLUG = "krasnoyarsk"

    # Маппинг количества комнат на URL-сегмент Avito
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
        """
        Инициализация парсера.

        Args:
            rooms: Количество комнат ("studio", "1", "2", "3", "4+").
            district: Район/микрорайон для фильтрации.
            min_price: Минимальная цена (руб).
            max_price: Максимальная цена (руб).
            min_area: Минимальная площадь (кв.м).
            max_area: Максимальная площадь (кв.м).
            max_analogs: Максимальное количество аналогов.
            max_pages: Максимум страниц пагинации.
            progress_callback: Функция обратного вызова для прогресса.
        """
        self.rooms = rooms
        self.district = district
        self.min_price = min_price
        self.max_price = max_price
        self.min_area = min_area
        self.max_area = max_area
        self.max_analogs = max_analogs or config.PARSER_MAX_ANALOGS
        self.max_pages = max_pages or config.PARSER_MAX_PAGES
        self.progress_callback = progress_callback
        self._browser = None
        self._context = None

    def _build_search_url(self, page: int = 1) -> str:
        """
        Формирует URL поиска на Avito.

        Args:
            page: Номер страницы пагинации.

        Returns:
            Полный URL для поиска.
        """
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

    async def _random_delay(self, min_sec: float = None, max_sec: float = None) -> None:
        """Случайная задержка между действиями (антибан)."""
        min_s = min_sec or config.PARSER_MIN_DELAY
        max_s = max_sec or config.PARSER_MAX_DELAY
        delay = random.uniform(min_s, max_s)
        await asyncio.sleep(delay)

    async def _page_delay(self) -> None:
        """Задержка между страницами пагинации (антибан)."""
        delay = random.uniform(
            config.PARSER_PAGE_DELAY_MIN, config.PARSER_PAGE_DELAY_MAX
        )
        logger.debug(f"Задержка между страницами: {delay:.1f} сек")
        await asyncio.sleep(delay)

    def _get_random_user_agent(self) -> str:
        """Случайный User-Agent из списка."""
        return random.choice(config.USER_AGENTS)

    def _get_random_viewport(self) -> dict:
        """Случайный viewport из списка."""
        return random.choice(config.VIEWPORTS)

    async def _setup_browser(self) -> None:
        """Настраивает и запускает headless-браузер с stealth-плагином."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        viewport = self._get_random_viewport()
        user_agent = self._get_random_user_agent()

        self._context = await self._browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            locale="ru-RU",
            timezone_id="Asia/Krasnoyarsk",
        )

        # Применяем stealth
        try:
            from playwright_stealth import stealth_async
            page = await self._context.new_page()
            await stealth_async(page)
            await page.close()
        except ImportError:
            logger.warning("playwright-stealth не установлен, продолжаем без stealth")

        # Загружаем куки если есть файл
        if config.PARSER_COOKIES_FILE:
            cookies_path = Path(config.PARSER_COOKIES_FILE)
            if cookies_path.exists():
                try:
                    with open(cookies_path, "r") as f:
                        cookies = json.load(f)
                    await self._context.add_cookies(cookies)
                    logger.info("Куки загружены из файла")
                except Exception as e:
                    logger.warning(f"Ошибка загрузки куки: {e}")

    async def _close_browser(self) -> None:
        """Закрывает браузер и освобождает ресурсы."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Ошибка закрытия браузера: {e}")

    def _report_progress(self, current: int, total: int, message: str) -> None:
        """Отправляет прогресс через callback."""
        if self.progress_callback:
            self.progress_callback(current, total, message)

    async def _parse_listing_page(self, html: str) -> List[Dict]:
        """
        Парсит страницу поисковой выдачи Avito.

        Args:
            html: HTML-код страницы.

        Returns:
            Список словарей с базовой информацией об объявлениях.
        """
        soup = BeautifulSoup(html, "lxml")
        listings = []

        # Ищем карточки объявлений
        items = soup.select('[data-marker="item"]')
        if not items:
            items = soup.select(".iva-item-root")
        if not items:
            items = soup.find_all("div", {"itemtype": "http://schema.org/Product"})

        for item in items:
            try:
                listing = self._extract_listing_from_card(item)
                if listing and self._validate_rooms(listing):
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Ошибка парсинга карточки: {e}")
                continue

        return listings

    def _extract_listing_from_card(self, item) -> Optional[Dict]:
        """
        Извлекает данные из карточки объявления на странице поиска.

        Args:
            item: BeautifulSoup-элемент карточки.

        Returns:
            Словарь с данными или None при ошибке.
        """
        listing = {}

        # Заголовок и ссылка
        title_el = item.select_one('[itemprop="name"]')
        if not title_el:
            title_el = item.select_one("h3")
        if not title_el:
            title_el = item.select_one('[data-marker="item-title"]')

        if title_el:
            listing["title"] = title_el.get_text(strip=True)
            link = title_el.find_parent("a") or title_el.find("a")
            if link and link.get("href"):
                href = link["href"]
                if not href.startswith("http"):
                    href = self.BASE_URL + href
                listing["url"] = href
        else:
            # Пробуем найти ссылку другим способом
            link = item.select_one("a[href*='/kvartiry/']")
            if link:
                listing["title"] = link.get_text(strip=True)
                href = link["href"]
                if not href.startswith("http"):
                    href = self.BASE_URL + href
                listing["url"] = href
            else:
                return None

        # Цена
        price_el = item.select_one('[itemprop="price"]')
        if price_el:
            price_val = price_el.get("content") or price_el.get_text(strip=True)
            listing["price"] = self._parse_price(str(price_val))
        else:
            price_el = item.select_one('[data-marker="item-price"]')
            if price_el:
                listing["price"] = self._parse_price(price_el.get_text(strip=True))

        # Адрес
        address_el = item.select_one('[class*="geo-address"]')
        if not address_el:
            address_el = item.select_one('[data-marker="item-address"]')
        if not address_el:
            address_el = item.select_one('[class*="address"]')
        if address_el:
            listing["address"] = address_el.get_text(strip=True)

        # Извлекаем параметры из заголовка
        title = listing.get("title", "")
        listing["rooms"] = self._extract_rooms_from_title(title)
        area_data = self._extract_area_from_title(title)
        listing.update(area_data)
        floor_data = self._extract_floor_from_title(title)
        listing.update(floor_data)

        return listing

    def _validate_rooms(self, listing: Dict) -> bool:
        """
        Проверяет соответствие количества комнат в объявлении запросу.

        Args:
            listing: Данные объявления.

        Returns:
            True если количество комнат совпадает.
        """
        listing_rooms = listing.get("rooms", "")
        if not listing_rooms:
            return True  # Если не определено — пропускаем проверку

        if self.rooms == "studio":
            return listing_rooms.lower() in ("студия", "studio", "с")
        elif self.rooms == "4+":
            try:
                return int(listing_rooms) >= 4
            except (ValueError, TypeError):
                return False
        else:
            try:
                return str(listing_rooms) == self.rooms
            except (ValueError, TypeError):
                return False

    def _extract_rooms_from_title(self, title: str) -> Optional[str]:
        """Извлекает количество комнат из заголовка."""
        title_lower = title.lower()

        if "студия" in title_lower or "студию" in title_lower:
            return "studio"

        # Ищем паттерн "N-к" или "N комн" или "N-комн"
        match = re.search(r"(\d+)[- ]?к(?:омн|\.)?", title_lower)
        if match:
            return match.group(1)

        return None

    def _extract_area_from_title(self, title: str) -> Dict:
        """Извлекает площади из заголовка (формат: 65/40/10)."""
        result = {}

        # Формат "XX м²" или "XX,X м²"
        area_match = re.search(r"(\d+[.,]?\d*)\s*м[²2]?", title)
        if area_match:
            result["total_area"] = float(area_match.group(1).replace(",", "."))

        # Формат "XX/XX/XX" (общая/жилая/кухня)
        areas_match = re.search(r"(\d+[.,]?\d*)\s*/\s*(\d+[.,]?\d*)\s*/\s*(\d+[.,]?\d*)", title)
        if areas_match:
            result["total_area"] = float(areas_match.group(1).replace(",", "."))
            result["living_area"] = float(areas_match.group(2).replace(",", "."))
            result["kitchen_area"] = float(areas_match.group(3).replace(",", "."))

        return result

    def _extract_floor_from_title(self, title: str) -> Dict:
        """Извлекает этаж/этажность из заголовка (формат: X/Y эт.)."""
        result = {}
        match = re.search(r"(\d+)/(\d+)\s*(?:эт|этаж)", title)
        if match:
            result["floor"] = int(match.group(1))
            result["total_floors"] = int(match.group(2))
        return result

    def _parse_price(self, price_str: str) -> Optional[int]:
        """Парсит строку цены в число."""
        if not price_str:
            return None
        # Удаляем всё кроме цифр
        digits = re.sub(r"[^\d]", "", price_str)
        if digits:
            return int(digits)
        return None

    async def _parse_listing_detail(self, page, url: str) -> Dict:
        """
        Парсит детальную страницу объявления для получения
        точного адреса, года постройки и проверки комнат.

        Args:
            page: Объект страницы Playwright.
            url: URL объявления.

        Returns:
            Словарь с дополнительными данными.
        """
        details = {}

        try:
            await page.goto(url, wait_until="domcontentloaded",
                           timeout=config.PARSER_TIMEOUT)
            await self._random_delay(1.5, 3.0)

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Адрес из карточки
            address_el = soup.select_one('[class*="style-item-address"]')
            if not address_el:
                address_el = soup.select_one('[data-marker="item-view/item-address"]')
            if not address_el:
                address_el = soup.select_one('[class*="item-address"]')
            if address_el:
                details["address"] = address_el.get_text(strip=True)

            # Характеристики из блока параметров
            params_block = soup.select('[class*="params-paramsList"] li')
            if not params_block:
                params_block = soup.select('[data-marker="item-params"] li')
            if not params_block:
                params_block = soup.select('[class*="item-params"] li')

            for param in params_block:
                text = param.get_text(strip=True).lower()

                if "комнат" in text or "студия" in text:
                    rooms_match = re.search(r"(\d+)", text)
                    if rooms_match:
                        details["rooms"] = rooms_match.group(1)
                    elif "студия" in text:
                        details["rooms"] = "studio"

                elif "общая" in text and "площадь" in text:
                    area_match = re.search(r"(\d+[.,]?\d*)", text)
                    if area_match:
                        details["total_area"] = float(
                            area_match.group(1).replace(",", ".")
                        )

                elif "кухн" in text:
                    area_match = re.search(r"(\d+[.,]?\d*)", text)
                    if area_match:
                        details["kitchen_area"] = float(
                            area_match.group(1).replace(",", ".")
                        )

                elif "жилая" in text:
                    area_match = re.search(r"(\d+[.,]?\d*)", text)
                    if area_match:
                        details["living_area"] = float(
                            area_match.group(1).replace(",", ".")
                        )

                elif "этаж" in text and "этажей" not in text and "этажность" not in text:
                    floor_match = re.search(r"(\d+)", text)
                    if floor_match:
                        details["floor"] = int(floor_match.group(1))

                elif "этажей" in text or "этажность" in text:
                    floors_match = re.search(r"(\d+)", text)
                    if floors_match:
                        details["total_floors"] = int(floors_match.group(1))

                elif "год" in text and "постройки" in text:
                    year_match = re.search(r"(\d{4})", text)
                    if year_match:
                        details["year_built"] = int(year_match.group(1))

                elif "тип дома" in text or "тип здания" in text:
                    # Удаляем "Тип дома:" или подобное
                    house_type = re.sub(r"тип\s*(дома|здания)\s*:?\s*", "", text)
                    details["house_type"] = house_type.strip()

            # Ищем год постройки в блоке "О доме" если не нашли ранее
            if "year_built" not in details:
                house_block = soup.select('[class*="about-house"] li')
                if not house_block:
                    house_block = soup.select('[class*="house-params"] li')
                for param in house_block:
                    text = param.get_text(strip=True).lower()
                    if "год" in text:
                        year_match = re.search(r"(\d{4})", text)
                        if year_match:
                            details["year_built"] = int(year_match.group(1))
                            break

        except Exception as e:
            logger.warning(f"Ошибка парсинга детальной страницы {url}: {e}")

        return details

    async def parse(self) -> List[Dict]:
        """
        Основной метод парсинга. Собирает объявления по заданным параметрам.

        Returns:
            Список словарей с данными объявлений.
        """
        results = []
        total_steps = self.max_pages + self.max_analogs

        try:
            await self._setup_browser()
            self._report_progress(0, total_steps, "Запуск браузера...")

            page = await self._context.new_page()

            # Применяем stealth к рабочей странице
            try:
                from playwright_stealth import stealth_async
                await stealth_async(page)
            except ImportError:
                pass

            # Проходим страницы поиска
            for page_num in range(1, self.max_pages + 1):
                if len(results) >= self.max_analogs:
                    break

                url = self._build_search_url(page_num)
                logger.info(f"Парсим страницу {page_num}: {url}")
                self._report_progress(
                    page_num, total_steps,
                    f"Загрузка страницы {page_num} из {self.max_pages}..."
                )

                try:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=config.PARSER_TIMEOUT,
                    )

                    if response and response.status == 429:
                        logger.warning("Получен HTTP 429, делаем паузу 30 сек")
                        await asyncio.sleep(30)
                        response = await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=config.PARSER_TIMEOUT,
                        )
                        if response and response.status == 429:
                            raise Exception("Avito заблокировал запросы (HTTP 429)")

                    # Ждём загрузки контента
                    await self._random_delay(2.0, 4.0)

                    # Проверяем на капчу
                    content = await page.content()
                    if "captcha" in content.lower() or "blocked" in content.lower():
                        logger.warning("Обнаружена капча/блокировка")
                        await asyncio.sleep(15)
                        await page.reload()
                        await self._random_delay(3.0, 5.0)
                        content = await page.content()
                        if "captcha" in content.lower():
                            raise Exception(
                                "Avito требует прохождение капчи. "
                                "Попробуйте позже."
                            )

                    # Парсим результаты страницы
                    page_listings = await self._parse_listing_page(content)
                    logger.info(
                        f"Страница {page_num}: найдено {len(page_listings)} объявлений"
                    )

                    results.extend(page_listings)

                except Exception as e:
                    logger.error(f"Ошибка на странице {page_num}: {e}")
                    if "429" in str(e) or "капча" in str(e).lower():
                        raise
                    continue

                # Задержка между страницами
                if page_num < self.max_pages:
                    await self._page_delay()

            # Обрезаем до максимума
            results = results[: self.max_analogs]

            # Открываем детальные страницы для получения подробностей
            detail_page = await self._context.new_page()
            try:
                from playwright_stealth import stealth_async
                await stealth_async(detail_page)
            except ImportError:
                pass

            enriched_results = []
            for i, listing in enumerate(results):
                if not listing.get("url"):
                    enriched_results.append(listing)
                    continue

                self._report_progress(
                    self.max_pages + i + 1, total_steps,
                    f"Детали объявления {i+1} из {len(results)}..."
                )

                try:
                    details = await self._parse_listing_detail(
                        detail_page, listing["url"]
                    )
                    # Мержим данные (детальные имеют приоритет)
                    merged = {**listing, **{k: v for k, v in details.items() if v}}
                    enriched_results.append(merged)
                except Exception as e:
                    logger.warning(
                        f"Не удалось получить детали для {listing.get('url')}: {e}"
                    )
                    enriched_results.append(listing)

                await self._random_delay(2.0, 4.0)

            await detail_page.close()
            await page.close()

            self._report_progress(total_steps, total_steps, "Парсинг завершён!")
            return enriched_results

        except Exception as e:
            logger.error(f"Критическая ошибка парсинга: {e}")
            raise
        finally:
            await self._close_browser()

    async def parse_single_listing(self, url: str) -> Optional[Dict]:
        """
        Парсит одно конкретное объявление по URL.
        Используется для автозаполнения формы.

        Args:
            url: URL объявления на Avito.

        Returns:
            Словарь с данными объявления или None.
        """
        try:
            await self._setup_browser()
            page = await self._context.new_page()

            try:
                from playwright_stealth import stealth_async
                await stealth_async(page)
            except ImportError:
                pass

            details = await self._parse_listing_detail(page, url)

            # Получаем цену со страницы
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            price_el = soup.select_one('[itemprop="price"]')
            if price_el:
                price_val = price_el.get("content") or price_el.get_text(strip=True)
                details["price"] = self._parse_price(str(price_val))
            else:
                price_el = soup.select_one('[class*="price-value"]')
                if price_el:
                    details["price"] = self._parse_price(price_el.get_text(strip=True))

            # Заголовок
            title_el = soup.select_one("h1")
            if title_el:
                details["title"] = title_el.get_text(strip=True)
                # Извлекаем доп. данные из заголовка
                title = details["title"]
                if "rooms" not in details:
                    details["rooms"] = self._extract_rooms_from_title(title)
                area_data = self._extract_area_from_title(title)
                for k, v in area_data.items():
                    if k not in details:
                        details[k] = v
                floor_data = self._extract_floor_from_title(title)
                for k, v in floor_data.items():
                    if k not in details:
                        details[k] = v

            details["url"] = url
            await page.close()
            return details

        except Exception as e:
            logger.error(f"Ошибка парсинга объявления {url}: {e}")
            return None
        finally:
            await self._close_browser()


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
    """
    Синхронная обёртка для запуска парсера.

    Args:
        rooms: Количество комнат.
        district: Район.
        min_price: Мин. цена.
        max_price: Макс. цена.
        min_area: Мин. площадь.
        max_area: Макс. площадь.
        max_analogs: Максимум аналогов.
        max_pages: Максимум страниц.
        progress_callback: Callback прогресса.

    Returns:
        Список объявлений.
    """
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

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(parser.parse())
    finally:
        loop.close()


def run_parse_single(url: str) -> Optional[Dict]:
    """
    Синхронная обёртка для парсинга одного объявления.

    Args:
        url: URL объявления.

    Returns:
        Данные объявления или None.
    """
    parser = AvitoParser(rooms="1")  # rooms не важен для одного объявления
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(parser.parse_single_listing(url))
    finally:
        loop.close()
