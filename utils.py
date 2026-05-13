"""
Вспомогательные функции: аналитика по выборке аналогов, формирование
структуры данных для шаблона results.html, экспорт в CSV.
"""
from __future__ import annotations

import csv
import io
import logging
import statistics
from typing import Any, Iterable, Optional

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Аналитика
# ---------------------------------------------------------------------------
def _safe_div(a: float, b: float) -> Optional[float]:
    if not b:
        return None
    return a / b


def analyze(
    target: dict[str, Any],
    listings: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Подсчитать ключевые метрики и подготовить структуру для рендеринга.

    Args:
        target: словарь параметров введённой пользователем квартиры
                (обязательно содержит rooms; цена/площадь — опционально).
        listings: итерируемый объект словарей-аналогов
                  (как Listing.to_dict()).

    Returns:
        Словарь со следующими ключами:
            target, listings_sorted, strict, soft, stats, warnings,
            histogram (распределение цен/м²).
    """
    listings_list = list(listings)

    strict = [l for l in listings_list if not l.get("rooms_mismatch")]
    soft = [l for l in listings_list if l.get("rooms_mismatch")]

    # цены за квадрат — только по строгим, у которых есть и цена и площадь
    pps_strict: list[float] = [
        l["price_per_sqm"] for l in strict
        if l.get("price_per_sqm") and l.get("price") and l.get("total_area")
    ]
    prices_strict: list[float] = [l["price"] for l in strict if l.get("price")]
    years_strict: list[int] = [l["build_year"] for l in strict if l.get("build_year")]

    avg_pps = statistics.mean(pps_strict) if pps_strict else None
    median_pps = statistics.median(pps_strict) if pps_strict else None
    median_price = statistics.median(prices_strict) if prices_strict else None
    avg_year = round(statistics.mean(years_strict)) if years_strict else None

    # Цена за метр у введённой квартиры
    target_pps: Optional[float] = None
    if target.get("price") and target.get("total_area"):
        target_pps = _safe_div(float(target["price"]), float(target["total_area"]))

    # Отклонение цены пользователя от среднего по аналогам, %
    deviation_pct: Optional[float] = None
    if target_pps and avg_pps:
        deviation_pct = (target_pps - avg_pps) / avg_pps * 100.0

    # Отклонение года постройки
    year_diff: Optional[int] = None
    if target.get("build_year") and avg_year:
        year_diff = int(target["build_year"]) - avg_year

    warnings: list[str] = []
    if len(strict) < config.MIN_STRICT_MATCHES:
        warnings.append(
            f"Найдено только {len(strict)} строгих аналогов "
            f"(минимально желательно {config.MIN_STRICT_MATCHES}). "
            "Достоверность сравнения снижена."
        )

    if deviation_pct is not None and deviation_pct >= config.PRICE_DEVIATION_WARN * 100:
        warnings.append(
            f"Цена за квадратный метр у вашей квартиры на "
            f"{deviation_pct:.1f}% выше средней по аналогам. "
            "Возможно, цена завышена."
        )
    elif (
        deviation_pct is not None
        and deviation_pct <= -config.PRICE_DEVIATION_WARN * 100
    ):
        warnings.append(
            f"Цена за квадратный метр у вашей квартиры на "
            f"{abs(deviation_pct):.1f}% ниже средней по аналогам. "
            "Возможно, это удачное предложение — либо есть скрытые недостатки."
        )

    if year_diff is not None and abs(year_diff) > config.YEAR_DEVIATION_WARN:
        direction = "новее" if year_diff > 0 else "старше"
        warnings.append(
            f"Год постройки дома значительно {direction} аналогов "
            f"(разница {abs(year_diff)} лет). Это может объяснять разницу в цене."
        )
        # Эвристика: 1% за год (середина диапазона 0.5–1.5%)
        adj_pct = year_diff * 1.0
        warnings.append(
            f"Грубая поправка на возраст дома: ожидаемая цена должна быть "
            f"примерно на {adj_pct:+.1f}% относительно среднего."
        )

    # Сортируем по возрастанию цены за квадрат
    def sort_key(l: dict[str, Any]) -> float:
        v = l.get("price_per_sqm")
        return float(v) if v else float("inf")

    listings_sorted = sorted(listings_list, key=sort_key)

    # Гистограмма по цене за метр (для строгих)
    histogram = _build_histogram(pps_strict, bins=8)

    stats = {
        "count_total": len(listings_list),
        "count_strict": len(strict),
        "count_soft": len(soft),
        "avg_pps": avg_pps,
        "median_pps": median_pps,
        "median_price": median_price,
        "avg_year": avg_year,
        "target_pps": target_pps,
        "deviation_pct": deviation_pct,
        "year_diff": year_diff,
    }

    return {
        "target": target,
        "listings_sorted": listings_sorted,
        "strict": strict,
        "soft": soft,
        "stats": stats,
        "warnings": warnings,
        "histogram": histogram,
    }


def _build_histogram(values: list[float], bins: int = 8) -> dict[str, list[float]]:
    """Простая гистограмма (равные корзины) для Chart.js."""
    if not values:
        return {"labels": [], "counts": []}
    lo, hi = min(values), max(values)
    if lo == hi:
        return {"labels": [f"{lo:.0f}"], "counts": [len(values)]}
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / step), bins - 1)
        counts[idx] += 1
    labels = [
        f"{lo + i * step:.0f}–{lo + (i + 1) * step:.0f}" for i in range(bins)
    ]
    return {"labels": labels, "counts": counts}


# ---------------------------------------------------------------------------
# Экспорт CSV
# ---------------------------------------------------------------------------
def listings_to_csv(listings: Iterable[dict[str, Any]]) -> str:
    """Сериализовать список аналогов в CSV (utf-8 with BOM для Excel)."""
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Комнат", "Адрес", "Цена, ₽", "Площадь, м²", "Цена за м², ₽/м²",
            "Этаж", "Этажность", "Год постройки", "Расстояние, км",
            "Отклонение по комнатам", "Ссылка",
        ]
    )
    for l in listings:
        writer.writerow(
            [
                l.get("rooms") or "",
                l.get("address") or "",
                _fmt(l.get("price")),
                _fmt(l.get("total_area")),
                _fmt(l.get("price_per_sqm")),
                l.get("floor") or "",
                l.get("floors_total") or "",
                l.get("build_year") or "",
                _fmt(l.get("distance_km")),
                "да" if l.get("rooms_mismatch") else "",
                l.get("url") or "",
            ]
        )
    return buf.getvalue()


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


# ---------------------------------------------------------------------------
# Утилиты для шаблонов
# ---------------------------------------------------------------------------
def fmt_money(v: Optional[float]) -> str:
    """Отформатировать цену для отображения."""
    if v is None:
        return "—"
    return f"{int(v):,}".replace(",", " ") + " ₽"


def fmt_number(v: Optional[float], digits: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"
