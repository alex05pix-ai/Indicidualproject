"""Тесты для geocoder с замоканным Nominatim — без сети."""

from __future__ import annotations

import pytest

from app.geocoder import GeoPoint, Geocoder


class _FakeLocation:
    def __init__(self, lat, lon, address=""):
        self.latitude = lat
        self.longitude = lon
        self.address = address


def test_distance_km_known_value():
    a = GeoPoint(56.0153, 92.8932)  # Красноярск (центр)
    b = GeoPoint(56.0500, 92.9300)  # ~5 км к северо-востоку
    d = Geocoder.distance_km(a, b)
    assert 3.0 < d < 7.0


def test_geocode_uses_cache_first(app, monkeypatch):
    """Если в БД есть запись — геокодер не делает сетевых вызовов."""
    from app.models import GeocodeCache, db

    with app.app_context():
        db.session.add(
            GeocodeCache(
                address="ул. 9 мая, 27, красноярск",
                latitude=56.05,
                longitude=92.95,
                display_name="cached",
            )
        )
        db.session.commit()

        gc = Geocoder()
        # Если cache hit, .geocode провайдера НЕ должен вызываться.
        called = {"n": 0}

        def _should_not_be_called(*args, **kwargs):
            called["n"] += 1
            return None

        monkeypatch.setattr(gc._client, "geocode", _should_not_be_called)
        point = gc.geocode("ул. 9 мая, 27", city_hint="Красноярск")
        assert called["n"] == 0
        assert point is not None
        assert point.latitude == pytest.approx(56.05)
        assert point.longitude == pytest.approx(92.95)


def test_geocode_calls_nominatim_and_writes_cache(app, monkeypatch):
    from app.models import GeocodeCache

    with app.app_context():
        gc = Geocoder()
        monkeypatch.setattr(
            gc._client,
            "geocode",
            lambda q, **kwargs: _FakeLocation(56.10, 92.90, q),
        )
        point = gc.geocode("ул. Партизана Железняка, 12", city_hint="Красноярск")
        assert point is not None
        assert point.latitude == pytest.approx(56.10)
        # Запись должна быть закеширована.
        cached = GeocodeCache.query.filter(
            GeocodeCache.address.like("%партизана%")
        ).first()
        assert cached is not None


def test_geocode_returns_none_when_not_found(app, monkeypatch):
    with app.app_context():
        gc = Geocoder()
        monkeypatch.setattr(gc._client, "geocode", lambda q, **kwargs: None)
        assert gc.geocode("неведомый адрес 12345", city_hint="Красноярск") is None


def test_geocode_handles_provider_error(app, monkeypatch):
    from geopy.exc import GeocoderTimedOut

    with app.app_context():
        gc = Geocoder()

        def _raise(*args, **kwargs):
            raise GeocoderTimedOut("upstream timeout")

        monkeypatch.setattr(gc._client, "geocode", _raise)
        # Не должно выбрасывать, должно вернуть None.
        assert gc.geocode("любой адрес", city_hint="Красноярск") is None
