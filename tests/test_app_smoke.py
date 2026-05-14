"""Smoke-тесты Flask-приложения.

Не запускают реальный парсинг (не вызывают /search), только проверяют, что
страницы рендерятся, заголовки безопасности на месте, healthz отвечает 200,
и что HTTP Basic Auth включается при заданном APP_PASSWORD.
"""

from __future__ import annotations

import os

import pytest


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok"


def test_index_renders_form(client):
    res = client.get("/")
    assert res.status_code == 200
    body = res.data.decode("utf-8")
    assert "Avito Comparator" in body
    assert 'name="rooms"' in body
    assert 'name="address"' in body
    # CSRF-токен встроен в форму.
    assert 'name="csrf_token"' in body


def test_security_headers(client):
    res = client.get("/")
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in res.headers
    assert "Referrer-Policy" in res.headers


def test_history_empty(client):
    res = client.get("/history")
    assert res.status_code == 200
    assert "История" in res.data.decode("utf-8")


def test_pwa_assets(client):
    m = client.get("/manifest.json")
    assert m.status_code == 200
    assert "AvitoCmp" in m.data.decode("utf-8")

    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert sw.headers.get("Service-Worker-Allowed") == "/"


def test_search_validation_error(client):
    """Без обязательных полей должен прийти JSON 400 с понятной ошибкой."""
    res = client.post("/search", data={})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_result_404_for_unknown_share_id(client):
    assert client.get("/result/not-existing-id").status_code == 404


def test_export_404_for_unknown_share_id(client):
    assert client.get("/export/not-existing-id.csv").status_code == 404


def test_basic_auth_enabled(monkeypatch):
    """Приложение должно требовать пароль, если APP_PASSWORD задан."""
    monkeypatch.setenv("APP_PASSWORD", "s3cret")

    # Перечитываем модули с новым окружением.
    import importlib
    import app.config
    import app.main
    importlib.reload(app.config)
    importlib.reload(app.main)

    flask_app, _socketio = app.main.create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with flask_app.app_context():
        from app.models import init_db
        init_db(flask_app)

    client = flask_app.test_client()
    # Без авторизации — 401
    res = client.get("/")
    assert res.status_code == 401
    assert "Basic" in res.headers.get("WWW-Authenticate", "")

    # С правильной — 200
    import base64
    creds = base64.b64encode(b"admin:s3cret").decode()
    res2 = client.get("/", headers={"Authorization": f"Basic {creds}"})
    assert res2.status_code == 200

    # Возвращаем env обратно для последующих тестов.
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    importlib.reload(app.config)
    importlib.reload(app.main)
