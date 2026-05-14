"""Парсер объявлений о продаже квартир на Avito.

Связка ``playwright`` (headless Chromium) + ``BeautifulSoup`` + ``asyncio``.

Особенности:
- Жёсткая фильтрация по количеству комнат (студия / 1 / 2 / 3 / 4+).
- Антибан-меры: stealth, рандомные задержки, ротация User-Agent/Viewport.
- Поддержка загрузки cookies-файла для подмены сессии.
- Колбэк ``progress_cb`` для real-time прогресс-бара (Flask-SocketIO).
- Все исключения логируются, парсер не падает целиком из-за одной карточки.

ВАЖНО: использование парсера должно соответствовать пользовательскому
соглашению Avito и применяться в образовательных целях.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .config import settings

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Константы / типы
# -----------------------------------------------------------------------------

AVITO_BASE = "https://www.avito.ru"

# Реалистичные User-Agent современных десктопных Chrome для ротации
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

VIEWPORTS: list[dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]

# Маппинг ключа количества комнат -> URL-сегмент Avito
ROOMS_TO_PATH: dict[str, str] = {
    "studio": "studii",
    "1": "1-komnatnye",
    "2": "2-komnatnye",
    "3": "3-komnatnye",
    "4plus": "4-komnatnye",  # на Avito нет общего фильтра 4+, берём 4-комнатные
}


ProgressCallback = Callable[[int, str], Any]
"""Колбэк прогресса: (percent: 0..100, message: str) -> None."""


# -----------------------------------------------------------------------------
# Datamodel
# -----------------------------------------------------------------------------


@dataclass
class SearchParams:
    """Параметры поиска аналогов."""

    rooms: str  # studio | 1 | 2 | 3 | 4plus
    address: str
    district: Optional[str] = None
    total_area: Optional[float] = None
    area_tolerance: float = 0.15  # ±15% по умолчанию
    price: Optional[float] = None
    radius_km: float = 2.0
    depth: int = 20  # сколько аналогов нужно (макс. 20)
    city: str = field(default_factory=lambda: settings.city)


@dataclass
class Listing:
    """Одно объявление с Avito."""

    url: str
    title: str
    price: Optional[float] = None
    rooms: Optional[str] = None  # совпадает с ключами ROOMS_TO_PATH
    rooms_raw: Optional[str] = None  # как было в карточке
    address: Optional[str] = None
    district: Optional[str] = None
    total_area: Optional[float] = None
    kitchen_area: Optional[float] = None
    living_area: Optional[float] = None
    floor: Optional[int] = None
    floors_total: Optional[int] = None
    house_type: Optional[str] = None
    year_built: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None
    rooms_mismatch: bool = False  # отметка «отклонение по комнатам»

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def price_per_m2(self) -> Optional[float]:
        if self.price and self.total_area and self.total_area > 0:
            return round(self.price / self.total_area, 2)
        return None


# -----------------------------------------------------------------------------
# Утилиты разбора текста
# -----------------------------------------------------------------------------


_PRICE_RE = re.compile(r"(\d[\d\s\u00a0]*)\s*(?:₽|руб)", re.IGNORECASE)
_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*м²", re.IGNORECASE)
_FLOOR_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*эт", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?:год\s+постройки|постройки)[:\s]*?(\d{4})", re.IGNORECASE)
_ROOMS_TITLE_RE = re.compile(r"(\d+)-к(?:омнатная)?", re.IGNORECASE)
_STUDIO_RE = re.compile(r"студи", re.IGNORECASE)


def parse_price(text: str) -> Optional[float]:
    """Извлекает цену из строки вида ``5 200 000 ₽``."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        # fallback — просто длинное число
        digits = re.sub(r"[^\d]", "", text)
        if digits and len(digits) >= 5:
            try:
                return float(digits)
            except ValueError:
                return None
        return None
    raw = re.sub(r"[^\d]", "", m.group(1))
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def parse_area(text: str) -> Optional[float]:
    """Извлекает площадь в м² из строки."""
    if not text:
        return None
    m = _AREA_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_floor(text: str) -> tuple[Optional[int], Optional[int]]:
    """Извлекает этаж/этажность из строки вида ``5/9 эт``."""
    if not text:
        return None, None
    m = _FLOOR_RE.search(text)
    if not m:
        return None, None
    try:
        return int(m.group(1)), int(m.group(2))
    except ValueError:
        return None, None


def parse_year(text: str) -> Optional[int]:
    """Извлекает год постройки дома."""
    if not text:
        return None
    m = _YEAR_RE.search(text)
    if not m:
        return None
    try:
        year = int(m.group(1))
    except ValueError:
        return None
    if 1800 <= year <= 2100:
        return year
    return None


def detect_rooms(title: str, description: str = "") -> tuple[Optional[str], Optional[str]]:
    """Определяет количество комнат по заголовку/описанию.

    Returns:
        (rooms_key, raw_text) — ключ из ROOMS_TO_PATH и человекочитаемая строка.
    """
    haystack = f"{title} {description}".strip()
    if not haystack:
        return None, None

    if _STUDIO_RE.search(haystack):
        return "studio", "Студия"

    m = _ROOMS_TITLE_RE.search(haystack)
    if not m:
        return None, None

    n = int(m.group(1))
    if n <= 0:
        return None, None
    if n >= 4:
        return "4plus", f"{n}-комнатная"
    return str(n), f"{n}-комнатная"


# -----------------------------------------------------------------------------
# Основной парсер
# -----------------------------------------------------------------------------


class AvitoParser:
    """Парсер объявлений Avito по продаже квартир.

    Использовать как async-context manager::

        async with AvitoParser() as parser:
            listings = await parser.search(SearchParams(...))
    """

    def __init__(
        self,
        *,
        headless: Optional[bool] = None,
        cookies_file: Optional[str] = None,
        progress_cb: Optional[ProgressCallback] = None,
        max_pages: Optional[int] = None,
    ):
        self.headless = settings.headless if headless is None else headless
        self.cookies_file = cookies_file or settings.cookies_file
        self.progress_cb = progress_cb
        self.max_pages = max_pages or settings.max_pages

        self._playwright = None
        self._browser = None
        self._context = None

    # ---------------- context manager ----------------

    async def __aenter__(self) -> "AvitoParser":
        # Импортируем здесь, чтобы не падать при отсутствии playwright во время unit-тестов
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        ua = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)

        try:
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to launch Chromium: %s", e)
            await self._safe_stop_playwright()
            raise

        self._context = await self._browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale="ru-RU",
            timezone_id="Asia/Krasnoyarsk",
        )

        # Маскировка автоматизации (упрощённый stealth — без зависимости от пакета)
        await self._context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
            """
        )

        # Если задан файл с куками — загружаем
        if self.cookies_file:
            await self._load_cookies(self.cookies_file)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._safe_close_context()
        await self._safe_close_browser()
        await self._safe_stop_playwright()

    async def _safe_close_context(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as e:  # noqa: BLE001
                logger.debug("context.close() failed: %s", e)
            self._context = None

    async def _safe_close_browser(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as e:  # noqa: BLE001
                logger.debug("browser.close() failed: %s", e)
            self._browser = None

    async def _safe_stop_playwright(self) -> None:
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as e:  # noqa: BLE001
                logger.debug("playwright.stop() failed: %s", e)
            self._playwright = None

    async def _load_cookies(self, path: str) -> None:
        cookies_path = Path(path)
        if not cookies_path.exists():
            logger.warning("Cookies file not found: %s", path)
            return
        try:
            data = json.loads(cookies_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                await self._context.add_cookies(data)
                logger.info("Loaded %d cookies from %s", len(data), path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load cookies from %s: %s", path, e)

    # ---------------- progress & sleep ----------------

    def _emit(self, percent: int, message: str) -> None:
        if not self.progress_cb:
            return
        try:
            res = self.progress_cb(percent, message)
            if asyncio.iscoroutine(res):
                # Если колбэк async — планируем выполнение, не блокируем парсер
                asyncio.ensure_future(res)
        except Exception as e:  # noqa: BLE001
            logger.debug("progress_cb failed: %s", e)

    @staticmethod
    async def _human_sleep(min_s: float, max_s: float) -> None:
        await asyncio.sleep(random.uniform(min_s, max_s))

    # ---------------- URL builder ----------------

    @staticmethod
    def build_search_url(params: SearchParams, page: int = 1) -> str:
        """Формирует URL поисковой выдачи Avito по параметрам."""
        path_segment = ROOMS_TO_PATH.get(params.rooms, "1-komnatnye")
        url = f"{AVITO_BASE}/{params.city}/kvartiry/prodam/{path_segment}"

        query: dict[str, Any] = {}
        if page and page > 1:
            query["p"] = page
        # Цена — если задана, ставим разумные границы (±30%)
        if params.price and params.price > 0:
            query["pmin"] = int(params.price * 0.7)
            query["pmax"] = int(params.price * 1.3)
        # Микрорайон/район в строке поиска
        if params.district:
            query["q"] = params.district

        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    # ---------------- High-level API ----------------

    async def search(self, params: SearchParams) -> list[Listing]:
        """Главный метод парсера: возвращает список объявлений-аналогов.

        Не выполняет геофильтрацию по координатам — это делается выше
        (в сервисном слое), потому что геокодер живёт в Flask-контексте.
        """
        if self._context is None:
            raise RuntimeError("AvitoParser must be used as async context manager")

        self._emit(5, "Открываю поисковую выдачу Avito…")
        listings_index: list[Listing] = []
        seen_urls: set[str] = set()

        max_listings = min(params.depth, settings.max_listings)

        # 1) Идём по страницам выдачи и собираем preview-листинги
        for page_num in range(1, self.max_pages + 1):
            url = self.build_search_url(params, page=page_num)
            logger.info("Fetching search page %d: %s", page_num, url)
            self._emit(5 + page_num * 5, f"Страница выдачи {page_num}…")

            try:
                html = await self._fetch_page(url)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to fetch search page %d: %s", page_num, e)
                continue

            new_items = self._parse_search_page(html, params)
            for item in new_items:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                listings_index.append(item)

            logger.info("Page %d: collected %d previews (total %d)", page_num, len(new_items), len(listings_index))

            if len(listings_index) >= max_listings * 2:
                break

            await self._human_sleep(settings.page_delay_min, settings.page_delay_max)

        # 2) Открываем карточки кандидатов, чтобы получить точные данные
        self._emit(40, f"Найдено {len(listings_index)} кандидатов, уточняю карточки…")
        result: list[Listing] = []
        candidates = listings_index[: max_listings * 2]

        for idx, listing in enumerate(candidates, start=1):
            try:
                await self._enrich_listing(listing)
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to enrich %s: %s", listing.url, e)

            # Финальная проверка количества комнат
            if listing.rooms is None:
                listing.rooms_mismatch = True
            elif listing.rooms != params.rooms:
                listing.rooms_mismatch = True

            result.append(listing)

            percent = 40 + int(50 * idx / max(1, len(candidates)))
            self._emit(percent, f"Обработано {idx}/{len(candidates)} карточек…")

            if len([r for r in result if not r.rooms_mismatch]) >= max_listings:
                break

            await self._human_sleep(settings.delay_min, settings.delay_max)

        self._emit(95, "Анализирую данные…")
        return result

    # ---------------- Page operations ----------------

    async def _fetch_page(self, url: str, *, retries: int = 3) -> str:
        """Скачивает HTML страницы с retry и обработкой 429/блокировок."""
        last_error: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            page = await self._context.new_page()
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=settings.page_timeout_ms,
                )
                if response is None:
                    raise RuntimeError("No response")
                status = response.status

                if status == 429 or status >= 500:
                    logger.warning("HTTP %s for %s, attempt %d", status, url, attempt)
                    await page.close()
                    await asyncio.sleep(min(60, 5 * attempt))
                    continue

                # Небольшая задержка для дорисовки JS
                await asyncio.sleep(random.uniform(1.5, 3.5))
                content = await page.content()

                # Признак капчи / блокировки
                if any(s in content.lower() for s in ("доступ ограничен", "captcha", "firewall")):
                    logger.warning("Anti-bot wall on %s, attempt %d", url, attempt)
                    await page.close()
                    await asyncio.sleep(min(60, 10 * attempt))
                    continue

                await page.close()
                return content
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.debug("Fetch attempt %d failed for %s: %s", attempt, url, e)
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(min(30, 3 * attempt))

        raise RuntimeError(f"Failed to fetch {url}: {last_error}")

    # ---------------- HTML parsing ----------------

    def _parse_search_page(self, html: str, params: SearchParams) -> list[Listing]:
        """Извлекает список превью-объявлений со страницы выдачи.

        Avito часто меняет вёрстку, поэтому мы используем устойчивые маркеры:
        ``data-marker="item"`` для карточки и атрибут ``data-marker="item-title"``.
        """
        soup = BeautifulSoup(html, "lxml")
        items = soup.find_all(attrs={"data-marker": "item"})

        result: list[Listing] = []
        for node in items:
            title_node = node.find(attrs={"data-marker": "item-title"})
            if not title_node:
                continue
            title = title_node.get_text(" ", strip=True)
            href = title_node.get("href", "")
            url = urljoin(AVITO_BASE, href) if href else ""

            rooms_key, rooms_raw = detect_rooms(title)

            # Жёсткий фильтр по комнатам ещё на этапе сбора
            if rooms_key is None:
                continue
            if rooms_key != params.rooms:
                continue

            price_node = node.find(attrs={"data-marker": "item-price"})
            price_text = price_node.get_text(" ", strip=True) if price_node else ""
            price = parse_price(price_text)

            address_node = (
                node.find(attrs={"data-marker": "item-address"})
                or node.find("div", class_=re.compile("geo", re.I))
            )
            address = address_node.get_text(" ", strip=True) if address_node else None

            total_area = parse_area(title)

            listing = Listing(
                url=url,
                title=title,
                price=price,
                rooms=rooms_key,
                rooms_raw=rooms_raw,
                address=address,
                total_area=total_area,
            )
            if listing.url:
                result.append(listing)

        return result

    async def _enrich_listing(self, listing: Listing) -> None:
        """Открывает карточку объявления и дополняет данные."""
        if not listing.url:
            return

        try:
            html = await self._fetch_page(listing.url, retries=2)
        except Exception as e:  # noqa: BLE001
            logger.debug("Cannot open card %s: %s", listing.url, e)
            return

        soup = BeautifulSoup(html, "lxml")

        # Адрес — ищем по data-marker
        addr_node = soup.find(attrs={"itemprop": "address"}) or soup.find(
            attrs={"data-marker": "item-address"}
        )
        if addr_node:
            listing.address = addr_node.get_text(" ", strip=True) or listing.address

        # Заголовок и описание
        title_node = soup.find(attrs={"data-marker": "item-view/title-info"}) or soup.find("h1")
        if title_node:
            listing.title = title_node.get_text(" ", strip=True) or listing.title

        # Блок параметров — обычно <ul> со списком "Параметр: значение"
        params_text = ""
        params_blocks = soup.find_all(attrs={"data-marker": "item-view/item-params"})
        for block in params_blocks:
            params_text += " " + block.get_text(" ", strip=True)

        # Полный текст карточки на крайний случай
        full_text = params_text or soup.get_text(" ", strip=True)

        if listing.total_area is None:
            listing.total_area = parse_area(full_text)

        # Кухня и жилая площадь — ищем по ключам
        m_kitchen = re.search(r"кухн[а-я]*[^0-9]{0,10}(\d+(?:[.,]\d+)?)", full_text, re.IGNORECASE)
        if m_kitchen:
            try:
                listing.kitchen_area = float(m_kitchen.group(1).replace(",", "."))
            except ValueError:
                pass
        m_living = re.search(r"жил[а-я]*[^0-9]{0,10}(\d+(?:[.,]\d+)?)", full_text, re.IGNORECASE)
        if m_living:
            try:
                listing.living_area = float(m_living.group(1).replace(",", "."))
            except ValueError:
                pass

        floor, floors_total = parse_floor(full_text)
        listing.floor = listing.floor or floor
        listing.floors_total = listing.floors_total or floors_total

        listing.year_built = listing.year_built or parse_year(full_text)

        # Тип дома (кирпичный / панельный / монолитный …)
        m_house = re.search(
            r"(кирпич\w*|панел\w*|монолит\w*|блочн\w*|деревянн\w*)",
            full_text,
            re.IGNORECASE,
        )
        if m_house:
            listing.house_type = m_house.group(1).capitalize()

        # Перепроверяем количество комнат по полному тексту
        rooms_key, rooms_raw = detect_rooms(listing.title or "", full_text)
        if rooms_key:
            listing.rooms = rooms_key
            listing.rooms_raw = rooms_raw or listing.rooms_raw

        # Цена, если на превью не разобрали
        if listing.price is None:
            price_node = soup.find(attrs={"data-marker": "item-view/item-price"}) or soup.find(
                attrs={"itemprop": "price"}
            )
            if price_node:
                listing.price = parse_price(price_node.get_text(" ", strip=True)) or parse_price(
                    str(price_node.get("content", ""))
                )


# -----------------------------------------------------------------------------
# Удобная обёртка для синхронного кода (Flask-роуты в worker-потоке)
# -----------------------------------------------------------------------------


def run_search(
    params: SearchParams,
    progress_cb: Optional[ProgressCallback] = None,
) -> list[Listing]:
    """Синхронная обёртка над ``AvitoParser.search`` для вызова из Flask-потока."""

    async def _runner() -> list[Listing]:
        async with AvitoParser(progress_cb=progress_cb) as parser:
            return await parser.search(params)

    return asyncio.run(_runner())
