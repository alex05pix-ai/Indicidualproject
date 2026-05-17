"""
Качественный парсер Avito через Playwright.
Открывает видимый браузер, ждёт прохождения капчи,
затем заходит в КАЖДОЕ объявление для получения полных данных.
"""
import asyncio
import logging
import random
import re
from typing import Dict, List, Optional, Callable

from bs4 import BeautifulSoup
from app.config import config

logger = logging.getLogger(__name__)

BASE_URL = "https://www.avito.ru"


def build_url(rooms: str, page: int = 1, min_price: int = None, max_price: int = None) -> str:
    """Строит URL поиска на Avito по количеству комнат."""
    rooms_map = {"studio": "studii", "1": "1-komnatnye", "2": "2-komnatnye",
                 "3": "3-komnatnye", "4+": "4-komnatnye"}
    segment = rooms_map.get(rooms, "1-komnatnye")
    url = f"{BASE_URL}/krasnoyarsk/kvartiry/prodam/{segment}"
    params = []
    if min_price:
        params.append(f"pmin={min_price}")
    if max_price:
        params.append(f"pmax={max_price}")
    if page > 1:
        params.append(f"p={page}")
    return url + ("?" + "&".join(params) if params else "")


def extract_listing_links(html: str) -> List[str]:
    """Извлекает ссылки на объявления из страницы поиска."""
    soup = BeautifulSoup(html, "lxml")
    links = []

    # Ищем все ссылки на квартиры
    for a in soup.select('[data-marker="item"] a[href*="/kvartiry/"]'):
        href = a.get("href", "")
        if href and "/kvartiry/" in href and "prodam" not in href:
            full = href if href.startswith("http") else BASE_URL + href
            if full not in links:
                links.append(full)

    # Fallback: другие селекторы
    if not links:
        for a in soup.select('a[href*="/kvartiry/"][href*="_"]'):
            href = a.get("href", "")
            if href and "/kvartiry/" in href:
                full = href if href.startswith("http") else BASE_URL + href
                if full not in links and "prodam" not in full.split("/kvartiry/")[1]:
                    links.append(full)

    return links


def parse_listing_page(html: str) -> Dict:
    """Парсит страницу конкретного объявления — извлекает ВСЕ данные."""
    soup = BeautifulSoup(html, "lxml")
    data = {}

    # Заголовок
    h1 = soup.select_one("h1")
    if h1:
        data["title"] = h1.get_text(strip=True)

    # Цена
    price_el = soup.select_one('[itemprop="price"]')
    if price_el:
        val = price_el.get("content") or price_el.get_text()
        digits = re.sub(r"[^\d]", "", str(val))
        if digits:
            data["price"] = int(digits)
    if "price" not in data:
        for el in soup.select('[class*="price"]'):
            digits = re.sub(r"[^\d]", "", el.get_text())
            if digits and len(digits) > 5:
                data["price"] = int(digits)
                break

    # Адрес
    addr_el = soup.select_one('[class*="item-address"]')
    if not addr_el:
        addr_el = soup.select_one('[data-marker="item-view/item-address"]')
    if not addr_el:
        addr_el = soup.select_one('[class*="style-item-address"]')
    if addr_el:
        # Берём только текст адреса, без "на карте"
        addr_text = addr_el.get_text(strip=True).replace("На карте", "").strip()
        data["address"] = addr_text

    # Характеристики — ищем в параметрах объявления
    params_items = soup.select('[class*="params-paramsList"] li')
    if not params_items:
        params_items = soup.select('[data-marker="item-params"] li')
    if not params_items:
        # Ищем через другие варианты вёрстки
        params_items = soup.select('[class*="item-params"] li')

    for li in params_items:
        text = li.get_text(strip=True).lower()

        # Количество комнат
        if "комнат" in text or "студия" in text:
            if "студия" in text:
                data["rooms"] = "studio"
            else:
                m = re.search(r"(\d+)", text)
                if m:
                    data["rooms"] = m.group(1)

        # Общая площадь
        elif "общая" in text:
            m = re.search(r"(\d+[.,]?\d*)", text)
            if m:
                data["total_area"] = float(m.group(1).replace(",", "."))

        # Этаж
        elif "этаж" in text and "этажей" not in text and "этажность" not in text:
            m = re.search(r"(\d+)", text)
            if m:
                data["floor"] = int(m.group(1))

        # Этажность
        elif "этажей" in text or "этажность" in text:
            m = re.search(r"(\d+)", text)
            if m:
                data["total_floors"] = int(m.group(1))

        # Год постройки
        elif "год" in text and "постройки" in text:
            m = re.search(r"(\d{4})", text)
            if m:
                data["year_built"] = int(m.group(1))

    # Если не нашли площадь в параметрах — ищем в заголовке
    if "total_area" not in data and "title" in data:
        m = re.search(r"(\d+[.,]?\d*)\s*м", data["title"])
        if m:
            data["total_area"] = float(m.group(1).replace(",", "."))

    # Если не нашли комнаты — из заголовка
    if "rooms" not in data and "title" in data:
        title = data["title"].lower()
        if "студия" in title:
            data["rooms"] = "studio"
        else:
            m = re.search(r"(\d+)[- ]?к", title)
            if m:
                data["rooms"] = m.group(1)

    # Если не нашли этаж — из заголовка (формат X/Y эт.)
    if "floor" not in data and "title" in data:
        m = re.search(r"(\d+)/(\d+)\s*эт", data["title"])
        if m:
            data["floor"] = int(m.group(1))
            data["total_floors"] = int(m.group(2))

    return data


async def run_parser_async(
    rooms: str,
    district: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    max_items: int = None,
    progress_callback: Optional[Callable] = None,
) -> List[Dict]:
    """
    Основной парсер: открывает видимый браузер, собирает ссылки,
    заходит в каждое объявление для полных данных.
    """
    from playwright.async_api import async_playwright

    max_items = max_items or config.PARSER_MAX_ITEMS
    results = []

    def report(current, total, msg):
        if progress_callback:
            progress_callback(current, total, msg)

    try:
        from playwright_stealth import stealth_async
        has_stealth = True
    except ImportError:
        has_stealth = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=random.choice(config.USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="ru-RU",
        )
        page = await context.new_page()
        if has_stealth:
            await stealth_async(page)

        # 1. Первый заход — ждём капчу
        first_url = build_url(rooms, 1, min_price, max_price)
        report(0, 100, "Открываю Avito... Если появилась капча — пройдите её.")
        logger.info(f"Открываю: {first_url}")
        await page.goto(first_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(25)  # Ждём капчу

        # 2. Собираем ссылки на объявления (макс 3 страницы)
        all_links = []
        for pg in range(1, 4):
            if len(all_links) >= max_items:
                break

            url = build_url(rooms, pg, min_price, max_price)
            report(pg * 10, 100, f"Сканирую страницу {pg}...")
            logger.info(f"Страница {pg}: {url}")

            if pg > 1:
                await asyncio.sleep(random.uniform(config.PARSER_DELAY_MIN, config.PARSER_DELAY_MAX))
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(3)

            html = await page.content()
            links = extract_listing_links(html)
            logger.info(f"Стр. {pg}: найдено {len(links)} ссылок")
            all_links.extend(links)

        all_links = all_links[:max_items]
        logger.info(f"Всего ссылок для обработки: {len(all_links)}")

        # 3. Открываем каждое объявление для полных данных
        for i, link in enumerate(all_links):
            report(30 + int(i / len(all_links) * 65), 100,
                   f"Обрабатываю {i+1} из {len(all_links)}...")
            logger.info(f"[{i+1}/{len(all_links)}] {link}")

            try:
                await asyncio.sleep(random.uniform(config.PARSER_DELAY_MIN, config.PARSER_DELAY_MAX))
                await page.goto(link, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2)

                html = await page.content()
                listing = parse_listing_page(html)
                listing["url"] = link

                # Фильтрация по району (если задан)
                if district and listing.get("address"):
                    addr_lower = listing["address"].lower()
                    district_lower = district.lower()
                    # Проверяем содержит ли адрес район/микрорайон
                    if district_lower not in addr_lower:
                        # Проверяем соответствие микрорайона
                        parent = config.MICRODISTRICTS.get(district)
                        if parent and parent.lower() not in addr_lower:
                            logger.debug(f"Пропускаю (район): {listing.get('address')}")
                            continue

                if listing.get("price"):
                    results.append(listing)
                    logger.info(f"  ✓ {listing.get('title', '')[:50]} | {listing.get('price')} ₽ | {listing.get('total_area')} м²")

            except Exception as e:
                logger.warning(f"Ошибка: {link}: {e}")
                continue

        await browser.close()

    report(100, 100, "Готово!")
    logger.info(f"Итого найдено: {len(results)} объявлений")
    return results


def run_parser(rooms, district=None, min_price=None, max_price=None,
               max_items=None, progress_callback=None) -> List[Dict]:
    """Синхронная обёртка."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            run_parser_async(rooms, district, min_price, max_price, max_items, progress_callback)
        )
    finally:
        loop.close()
