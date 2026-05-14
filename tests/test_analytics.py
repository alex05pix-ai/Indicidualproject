"""Тесты сравнительной аналитики."""

from __future__ import annotations

from app.analytics import UserApartment, analyze, _build_histogram


def _listing(price, area, rooms="2", year=None, mismatch=False):
    return {
        "price": price,
        "total_area": area,
        "rooms": rooms,
        "rooms_raw": rooms,
        "year_built": year,
        "rooms_mismatch": mismatch,
    }


def test_analyze_basic_metrics():
    user = UserApartment(
        address="тест",
        rooms="2",
        price=6_000_000,
        total_area=60.0,
        year_built=2010,
    )
    listings = [
        _listing(5_400_000, 54),  # 100k/м²
        _listing(6_000_000, 60),  # 100k/м²
        _listing(6_600_000, 60),  # 110k/м²
        _listing(5_200_000, 50),  # 104k/м²
        _listing(7_000_000, 70),  # 100k/м²
    ]
    result = analyze(user, listings)
    assert result.strict_count == 5
    assert result.avg_price_per_m2 is not None
    assert result.median_price_per_m2 is not None
    # Цена пользователя (100k) близка к средней — отклонение должно быть мало.
    assert abs(result.deviation_pct or 0) < 5


def test_analyze_warns_on_overprice():
    user = UserApartment(address="x", rooms="2", price=8_400_000, total_area=60.0)
    listings = [_listing(6_000_000, 60) for _ in range(5)]  # 100k/м² у всех
    result = analyze(user, listings)
    assert result.deviation_pct is not None and result.deviation_pct > 30
    assert any("завышена" in w.lower() for w in result.warnings)


def test_analyze_warns_when_too_few_listings():
    user = UserApartment(address="x", rooms="2", price=6_000_000, total_area=60.0)
    listings = [_listing(6_000_000, 60), _listing(6_200_000, 62)]
    result = analyze(user, listings)
    assert result.strict_count == 2
    assert any("точным совпадением" in w for w in result.warnings)


def test_analyze_excludes_rooms_mismatch_from_avg():
    user = UserApartment(address="x", rooms="2", price=6_000_000, total_area=60.0)
    listings = [
        _listing(6_000_000, 60),                          # 100k
        _listing(6_200_000, 62),                          # 100k
        _listing(20_000_000, 40, mismatch=True),          # выброс — 500k, не должен учитываться
    ]
    result = analyze(user, listings)
    assert result.strict_count == 2
    assert result.soft_count == 1
    assert result.avg_price_per_m2 < 200_000  # выброс не вошёл


def test_analyze_year_warning():
    user = UserApartment(
        address="x", rooms="2", price=6_000_000, total_area=60.0, year_built=2024
    )
    listings = [_listing(6_000_000, 60, year=1990) for _ in range(5)]
    result = analyze(user, listings)
    assert any("Год постройки" in w for w in result.warnings)


def test_build_histogram_handles_empty_and_uniform():
    assert _build_histogram([]) == []
    h = _build_histogram([100.0, 100.0, 100.0])
    assert len(h) == 1 and h[0]["count"] == 3
    h2 = _build_histogram(list(range(8)))
    assert sum(b["count"] for b in h2) == 8
