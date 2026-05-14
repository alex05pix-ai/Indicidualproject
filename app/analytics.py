"""Сравнительная аналитика для квартир.

Считает среднюю и медианную цену, гистограмму распределения, отклонения
введённой пользователем квартиры от выборки и формирует текстовые
предупреждения.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class UserApartment:
    """Описание квартиры пользователя для аналитики."""

    address: str
    rooms: str
    price: float
    total_area: Optional[float] = None
    year_built: Optional[int] = None

    @property
    def price_per_m2(self) -> Optional[float]:
        if self.total_area and self.total_area > 0:
            return round(self.price / self.total_area, 2)
        return None


@dataclass
class AnalyticsResult:
    """Результат аналитического сравнения."""

    listings: list[dict[str, Any]] = field(default_factory=list)
    strict_count: int = 0
    soft_count: int = 0
    avg_price_per_m2: Optional[float] = None
    median_price_per_m2: Optional[float] = None
    median_price: Optional[float] = None
    avg_year_built: Optional[float] = None
    user: dict[str, Any] = field(default_factory=dict)
    deviation_pct: Optional[float] = None  # отклонение цены/м² пользователя от средней
    histogram: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listings": self.listings,
            "strict_count": self.strict_count,
            "soft_count": self.soft_count,
            "avg_price_per_m2": self.avg_price_per_m2,
            "median_price_per_m2": self.median_price_per_m2,
            "median_price": self.median_price,
            "avg_year_built": self.avg_year_built,
            "user": self.user,
            "deviation_pct": self.deviation_pct,
            "histogram": self.histogram,
            "warnings": self.warnings,
        }


def _build_histogram(values: list[float], bins: int = 8) -> list[dict[str, Any]]:
    """Строит простую гистограмму распределения значений."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if lo == hi:
        return [{"from": lo, "to": hi, "count": len(values)}]
    step = (hi - lo) / bins
    buckets = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / step))
        buckets[idx] += 1
    return [
        {"from": round(lo + i * step, 2), "to": round(lo + (i + 1) * step, 2), "count": c}
        for i, c in enumerate(buckets)
    ]


def analyze(
    user: UserApartment,
    listings: list[dict[str, Any]],
) -> AnalyticsResult:
    """Считает сравнительную аналитику.

    Args:
        user: квартира пользователя.
        listings: список словарей-аналогов (как из ``Listing.to_dict``).
            Для каждой ожидается поле ``rooms_mismatch`` (bool).
    """
    result = AnalyticsResult()
    result.user = {
        "address": user.address,
        "rooms": user.rooms,
        "price": user.price,
        "total_area": user.total_area,
        "year_built": user.year_built,
        "price_per_m2": user.price_per_m2,
    }

    # Для каждой записи добавим вычисленную price_per_m2
    enriched: list[dict[str, Any]] = []
    for raw in listings:
        item = dict(raw)
        price = item.get("price")
        area = item.get("total_area")
        ppm = None
        if price and area and area > 0:
            ppm = round(price / area, 2)
        item["price_per_m2"] = ppm
        enriched.append(item)

    # Сортируем по price_per_m2 (нулевые в конец)
    enriched.sort(key=lambda x: (x.get("price_per_m2") is None, x.get("price_per_m2") or 0))
    result.listings = enriched

    strict = [
        x for x in enriched
        if not x.get("rooms_mismatch") and x.get("price_per_m2") is not None
    ]
    soft = [x for x in enriched if x.get("rooms_mismatch")]

    result.strict_count = len(strict)
    result.soft_count = len(soft)

    # Метрики только по строгой выборке
    ppms = [x["price_per_m2"] for x in strict if x.get("price_per_m2")]
    prices = [x["price"] for x in strict if x.get("price")]

    if ppms:
        result.avg_price_per_m2 = round(statistics.mean(ppms), 2)
        result.median_price_per_m2 = round(statistics.median(ppms), 2)
        result.histogram = _build_histogram(ppms)

    if prices:
        result.median_price = round(statistics.median(prices), 2)

    years = [x["year_built"] for x in strict if x.get("year_built")]
    if years:
        result.avg_year_built = round(statistics.mean(years), 1)

    # Отклонение цены пользователя
    if user.price_per_m2 and result.avg_price_per_m2:
        deviation = (user.price_per_m2 - result.avg_price_per_m2) / result.avg_price_per_m2 * 100
        result.deviation_pct = round(deviation, 1)

    # Предупреждения
    if result.strict_count < 5:
        result.warnings.append(
            f"Найдено только {result.strict_count} аналогов с точным совпадением комнат. "
            "Результаты могут быть неточными."
        )

    if (
        result.median_price_per_m2
        and user.price_per_m2
        and user.price_per_m2 > result.median_price_per_m2 * 1.15
    ):
        result.warnings.append(
            "Цена за м² выше медианной по аналогам более чем на 15%. Возможно, цена завышена."
        )
    if (
        result.median_price_per_m2
        and user.price_per_m2
        and user.price_per_m2 < result.median_price_per_m2 * 0.85
    ):
        result.warnings.append(
            "Цена за м² ниже медианной по аналогам более чем на 15%. Это может быть выгодное предложение или скрытые недостатки."
        )

    if user.year_built and result.avg_year_built:
        diff = user.year_built - result.avg_year_built
        if abs(diff) >= 10:
            direction = "новее" if diff > 0 else "старше"
            result.warnings.append(
                f"Год постройки дома ({user.year_built}) значительно {direction} аналогов "
                f"(средний {result.avg_year_built}). Это может объяснять разницу в цене."
            )
            # Простая эвристика: 1% за год
            expected_correction_pct = round(diff * 1.0, 1)
            result.warnings.append(
                f"С учётом разницы в годе постройки ожидаемая корректировка цены ~{expected_correction_pct:+}%."
            )

    return result
