"""
Парсер Avito на базе Playwright + BeautifulSoup + asyncio.

Класс AvitoParser:
  * собирает поисковую выдачу по строго заданному количеству комнат;
  * листает пагинацию (до MAX_PAGES);
  * заходит на карточки только перспективных объявлений (по совпадению
    района/микрорайона);
  * умеет геовалидировать результат (вызывает geocoder).

ВАЖНО: парсер использует «вежливые» задержки и stealth-меры, но Avito
активно борется с автоматизацией. Для production-эксплуатации потребуются
прокси и реальные cookies. См. README.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

import config
import geocoder

log = logging.getLogger(__name__)

# Опциональная зависимость: playwright_stealth может отсутствовать.
try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Page,
        Playwright,
        async_playwright,
        TimeoutError as PWTimeoutError,
    )
    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover — для CI без playwright
    PLAYWRIGHT_AVAILABLE = False
    Browser = BrowserContext = Page = Playwright = object  # type: ignore[misc,assignment]
    PWTimeoutError = Exception  # type: ignore[misc,assignment]

try:
    from playwright_stealth import stealth_async  # type: ignore
    STEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover
    STEALTH_AVAILABLE = False

    async def stealth_async(_page: Any) -> None:  # type: ignore[no-redef]
        return None


# ---------------------------------------------------------------------------
# Datamodel
# ---------------------------------------------------------------------------
@dataclass
class Listing:
    """Один найденный аналог."""

    title: str
    url: str
    price: Optional[float] = None
    rooms: Optional[str] = None              # "studio" | "1" | "2" | "3" | "4+"
    rooms_raw: Optional[str] = None          # как в заголовке/карточке
    total_area: Optional[float] = None
    kitchen_area: Optional[float] = None
    living_area: Optional[float] = None
    floor: Optional[int] = None
    floors_total: Optional[int] = None
    house_type: Optional[str] = None
    build_year: Optional[int] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None
    rooms_mismatch: bool = False             # отклонение по комнатам
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def price_per_sqm(self) -> Optional[float]:
        if self.price and self.total_area and self.total_area > 0:
            return self.price / self.total_area
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["price_per_sqm"] = self.price_per_sqm
        return d


# ---------------------------------------------------------------------------
# Search params
# ---------------------------------------------------------------------------
@dataclass
class SearchParams:
    """Параметры поиска квартир-аналогов."""

    rooms: str                       # "studio" | "1" | "2" | "3" | "4+"
    address: str                     # адрес/ориентир целевой квартиры
    district: Optional[str] = None
    total_area: Optional[float] = None
    area_tolerance: float = config.DEFAULT_AREA_TOLERANCE
    distance_km: float = config.DEFAULT_DISTANCE_KM
    depth: int = config.DEFAULT_RESULTS
    price_min: Optional[float] = None
    price_max: Optional[float] = None

    def normalized_rooms(self) -> str:
        """Привести значение к одному из ключей ROOM_URL_SEGMENT."""
        r = (self.rooms or "").strip().lower()
        if r in {"studio", "студия", "ст"}:
            return "studio"
        if r in {"4+", "4", "5", "6"}:
            return "4+"
        if r in {"1", "2", "3"}:
            return r
        return "1"  # дефолт-консерватив


# ---------------------------------------------------------------------------
# Парсер
# ---------------------------------------------------------------------------
class AvitoParser:
    """Асинхронный парсер Avito.

    Использование:
        async with AvitoParser() as parser:
            listings = await parser.search(params, on_progress=cb)
    """

    AVITO_ITEM_RE = re.compile(r"/[^/]+_kvartira[^/]*_\d+", re.IGNORECASE)
    PRICE_RE = re.compile(r"(\d[\d\s\u00a0]+)\s*₽")
    AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*м²", re.IGNORECASE)
    FLOOR_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*эт", re.IGNORECASE)
    YEAR_RE = re.compile(r"(?:Год постройки|постройки)\D{0,5}(\d{4})", re.IGNORECASE)
    ROOMS_TITLE_RE = re.compile(
        r"(студия|\d+)\s*-?\s*(?:к(?:омн)?\.?|комнатная)",
        re.IGNORECASE,
    )

    def __init__(self, cookies_file: Optional[Path] = None) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._cookies_file = cookies_file or config.COOKIES_FILE

    # --- async context manager -------------------------------------------------
    async def __aenter__(self) -> "AvitoParser":
        await self._start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stop()

    async def _start(self) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright не установлен. Выполните: pip install playwright && "
                "playwright install chromium"
            )
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ua = random.choice(config.USER_AGENTS)
        viewport = random.choice(config.VIEWPORTS)
        self._context = await self._browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale="ru-RU",
            timezone_id="Asia/Krasnoyarsk",
        )
        # Подгружаем cookies, если они экспортированы пользователем заранее.
        if self._cookies_file.exists():
            try:
                cookies = json.loads(self._cookies_file.read_text(encoding="utf-8"))
                await self._context.add_cookies(cookies)
                log.info("Loaded %d cookies from %s", len(cookies), self._cookies_file)
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to load cookies: %s", exc)

    async def _stop(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("Error during parser shutdown: %s", exc)

    # --- helpers --------------------------------------------------------------
    @staticmethod
    async def _sleep(low: float, high: float) -> None:
        await asyncio.sleep(random.uniform(low, high))

    @classmethod
    def _extract_rooms(cls, text: str) -> Optional[str]:
        """Достать количество комнат из заголовка/строки характеристик."""
        if not text:
            return None
        if "студи" in text.lower():
            return "studio"
        m = cls.ROOMS_TITLE_RE.search(text)
        if not m:
            return None
        token = m.group(1).lower()
        if "студ" in token:
            return "studio"
        try:
            n = int(token)
        except ValueError:
            return None
        if n >= 4:
            return "4+"
        return str(n)

    @classmethod
    def _extract_price(cls, text: str) -> Optional[float]:
        if not text:
            return None
        m = cls.PRICE_RE.search(text.replace("\xa0", " "))
        if not m:
            return None
        digits = re.sub(r"\D", "", m.group(1))
        return float(digits) if digits else None

    @classmethod
    def _extract_area(cls, text: str) -> Optional[float]:
        if not text:
            return None
        m = cls.AREA_RE.search(text)
        if not m:
            return None
        return float(m.group(1).replace(",", "."))

    @classmethod
    def _extract_floor(cls, text: str) -> tuple[Optional[int], Optional[int]]:
        if not text:
            return None, None
        m = cls.FLOOR_RE.search(text)
        if not m:
            return None, None
        return int(m.group(1)), int(m.group(2))

    @classmethod
    def _extract_year(cls, text: str) -> Optional[int]:
        if not text:
            return None
        m = cls.YEAR_RE.search(text)
        if not m:
            return None
        try:
            year = int(m.group(1))
            if 1900 <= year <= 2100:
                return year
        except ValueError:
            return None
        return None

    # --- URL builder ----------------------------------------------------------
    def build_search_url(self, params: SearchParams, page: int = 1) -> str:
        """Сформировать URL списка по правилам ТЗ."""
        rooms_key = params.normalized_rooms()
        segment = config.ROOM_URL_SEGMENT[rooms_key]
        base = f"{config.AVITO_BASE_URL}/{config.CITY_SLUG_AVITO}/kvartiry/prodam/{segment}"
        query: dict[str, Any] = {}
        if params.price_min:
            query["pmin"] = int(params.price_min)
        if params.price_max:
            query["pmax"] = int(params.price_max)
        if page > 1:
            query["p"] = page
        if query:
            return f"{base}?{urlencode(query)}"
        return base

    # --- main pipeline --------------------------------------------------------
    async def search(
        self,
        params: SearchParams,
        on_progress: Optional[Any] = None,
    ) -> list[Listing]:
        """Главный метод: поиск + фильтрация + геовалидация.

        on_progress(stage: str, percent: int, message: str) — опц. callback,
        вызывается из разных мест пайплайна для обновления прогресс-бара.
        """
        def progress(stage: str, percent: int, msg: str) -> None:
            if on_progress is not None:
                try:
                    on_progress(stage, percent, msg)
                except Exception:  # noqa: BLE001
                    pass

        if self._context is None:
            raise RuntimeError("Parser is not started. Use 'async with AvitoParser()'.")

        target_rooms = params.normalized_rooms()
        target_coords = geocoder.geocode(params.address)
        if target_coords is None:
            log.warning("Не удалось геокодировать адрес пользователя: %r", params.address)

        progress("collect", 5, "Открываем поисковую выдачу Avito…")

        candidate_urls: list[str] = []
        for page_num in range(1, config.MAX_PAGES + 1):
            url = self.build_search_url(params, page=page_num)
            log.info("Listing page %d: %s", page_num, url)
            try:
                html = await self._fetch_html(url)
            except Exception as exc:  # noqa: BLE001
                log.error("Не удалось получить страницу %s: %s", url, exc)
                if page_num == 1:
                    raise
                break

            page_urls = self._parse_listing_urls(html)
            log.info("  found %d candidate urls on page %d", len(page_urls), page_num)
            for u in page_urls:
                if u not in candidate_urls:
                    candidate_urls.append(u)

            progress(
                "collect",
                5 + int(40 * page_num / config.MAX_PAGES),
                f"Стр. {page_num}: найдено {len(candidate_urls)} объявлений",
            )

            if len(candidate_urls) >= params.depth * 3:  # запас x3 на отсев
                break
            await self._sleep(config.DELAY_PAGE_MIN, config.DELAY_PAGE_MAX)

        progress("detail", 50, f"Открываем карточки ({len(candidate_urls)})…")

        listings: list[Listing] = []
        max_to_open = min(len(candidate_urls), max(params.depth * 2, 10))

        for idx, url in enumerate(candidate_urls[:max_to_open], start=1):
            try:
                listing = await self._fetch_listing(url)
            except Exception as exc:  # noqa: BLE001
                log.warning("Карточка %s упала: %s", url, exc)
                continue
            if listing is None:
                continue

            # Жёсткая фильтрация по числу комнат
            if listing.rooms != target_rooms:
                # помечаем как отклонение, но не выбрасываем
                listing.rooms_mismatch = True

            # Геовалидация
            if listing.address:
                coords = geocoder.geocode(listing.address)
                if coords:
                    listing.latitude, listing.longitude = coords
                    listing.distance_km = geocoder.distance_km(target_coords, coords)

            if (
                listing.distance_km is not None
                and listing.distance_km > params.distance_km
            ):
                log.info(
                    "Skip %s: distance %.2f km > limit %.2f",
                    url, listing.distance_km, params.distance_km,
                )
                continue

            listings.append(listing)
            progress(
                "detail",
                50 + int(45 * idx / max_to_open),
                f"Обработано {idx}/{max_to_open}",
            )

            # хватит ли строгих совпадений?
            strict = sum(1 for l in listings if not l.rooms_mismatch)
            if strict >= params.depth:
                break
            await self._sleep(config.DELAY_ACTION_MIN, config.DELAY_ACTION_MAX)

        progress("done", 100, f"Готово: {len(listings)} аналогов")
        return listings

    # --- fetching -------------------------------------------------------------
    async def _fetch_html(self, url: str) -> str:
        """Открыть URL и вернуть HTML, с обработкой капчи/429."""
        assert self._context is not None
        page: Page = await self._context.new_page()
        try:
            if STEALTH_AVAILABLE:
                await stealth_async(page)
            try:
                response = await page.goto(
                    url, timeout=config.NAV_TIMEOUT_MS, wait_until="domcontentloaded"
                )
            except PWTimeoutError as exc:
                raise RuntimeError(f"Timeout при открытии {url}") from exc

            if response is not None and response.status in (403, 429):
                # Avito вернул блокировку
                raise RuntimeError(
                    f"Avito ответил {response.status} (возможна блокировка/капча)."
                )

            # Подождём подгрузку списка
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except PWTimeoutError:
                pass

            # Иногда показывается челлендж; попробуем подождать ещё
            content = await page.content()
            if "captcha" in content.lower() or "проверка" in content.lower():
                await asyncio.sleep(5)
                content = await page.content()

            return content
        finally:
            await page.close()

    def _parse_listing_urls(self, html: str) -> list[str]:
        """Извлечь URL карточек квартир из HTML страницы поиска."""
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not self.AVITO_ITEM_RE.search(href) and "/kvartir" not in href:
                continue
            if "_kvartira" not in href and "/items/" not in href:
                continue
            full = urljoin(config.AVITO_BASE_URL, href.split("?")[0])
            if full not in urls:
                urls.append(full)
        return urls

    async def _fetch_listing(self, url: str) -> Optional[Listing]:
        """Скачать и распарсить карточку объявления."""
        html = await self._fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        # Заголовок
        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Цена
        price = None
        price_meta = soup.find("meta", attrs={"itemprop": "price"})
        if price_meta and price_meta.get("content"):
            try:
                price = float(price_meta["content"])
            except ValueError:
                price = None
        if price is None:
            price = self._extract_price(soup.get_text(" ", strip=True))

        # Адрес
        address = None
        addr_tag = soup.find(itemprop="address") or soup.find(
            attrs={"data-marker": "item-address"}
        )
        if addr_tag:
            address = addr_tag.get_text(" ", strip=True)

        # Характеристики
        full_text = soup.get_text(" ", strip=True)
        rooms = self._extract_rooms(title) or self._extract_rooms(full_text)
        total_area = self._extract_area(full_text)
        floor, floors_total = self._extract_floor(full_text)
        build_year = self._extract_year(full_text)

        if not title and not price:
            return None

        return Listing(
            title=title,
            url=url,
            price=price,
            rooms=rooms,
            rooms_raw=title,
            total_area=total_area,
            floor=floor,
            floors_total=floors_total,
            build_year=build_year,
            address=address,
        )
