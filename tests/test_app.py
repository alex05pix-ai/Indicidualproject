"""
Smoke-тесты веб-интерфейса Flask.
"""

import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app


@pytest.fixture
def client():
    """Тестовый клиент Flask."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestIndexPage:
    """Тесты главной страницы."""

    def test_index_status_code(self, client):
        """Главная страница возвращает 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_index_contains_form(self, client):
        """Главная страница содержит форму поиска."""
        response = client.get("/")
        html = response.data.decode("utf-8")
        assert "searchForm" in html
        assert "address" in html
        assert "rooms" in html
        assert "price" in html

    def test_index_contains_districts(self, client):
        """Главная страница содержит список районов."""
        response = client.get("/")
        html = response.data.decode("utf-8")
        assert "Советский" in html
        assert "Центральный" in html

    def test_index_contains_theme_toggle(self, client):
        """Главная страница содержит переключатель темы."""
        response = client.get("/")
        html = response.data.decode("utf-8")
        assert "themeToggle" in html


class TestSearchEndpoint:
    """Тесты API поиска."""

    def test_search_missing_address(self, client):
        """Ошибка при отсутствии адреса."""
        response = client.post(
            "/search",
            json={"rooms": "2", "price": "4000000"},
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "адрес" in data["error"].lower() or "error" in data

    def test_search_missing_rooms(self, client):
        """Ошибка при отсутствии комнат."""
        response = client.post(
            "/search",
            json={"address": "ул. Ленина, 1", "price": "4000000"},
        )
        assert response.status_code == 400

    def test_search_missing_price(self, client):
        """Ошибка при отсутствии цены."""
        response = client.post(
            "/search",
            json={"address": "ул. Ленина, 1", "rooms": "2"},
        )
        assert response.status_code == 400

    def test_search_invalid_price(self, client):
        """Ошибка при невалидной цене."""
        response = client.post(
            "/search",
            json={"address": "ул. Ленина, 1", "rooms": "2", "price": "abc"},
        )
        assert response.status_code == 400

    def test_search_valid_request(self, client):
        """Валидный запрос возвращает query_id."""
        response = client.post(
            "/search",
            json={
                "address": "ул. 9 Мая, 27",
                "rooms": "2",
                "price": "4500000",
                "district": "Советский",
            },
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "query_id" in data
        assert data["status"] == "processing"


class TestHistoryEndpoint:
    """Тесты API истории."""

    def test_history_returns_list(self, client):
        """История возвращает список."""
        response = client.get("/history")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)


class TestStatusEndpoint:
    """Тесты API статуса."""

    def test_status_not_found(self, client):
        """Несуществующий запрос возвращает 404."""
        response = client.get("/status/nonexistent-id")
        assert response.status_code == 404


class TestExportEndpoint:
    """Тесты экспорта."""

    def test_export_not_found(self, client):
        """Экспорт несуществующего запроса возвращает 404."""
        response = client.get("/export/nonexistent-id")
        assert response.status_code == 404


class TestAutofillEndpoint:
    """Тесты автозаполнения."""

    def test_autofill_empty_url(self, client):
        """Ошибка при пустой ссылке."""
        response = client.post("/autofill", json={"url": ""})
        assert response.status_code == 400

    def test_autofill_invalid_url(self, client):
        """Ошибка при невалидной ссылке (не Avito)."""
        response = client.post("/autofill", json={"url": "https://google.com"})
        assert response.status_code == 400


class TestSecurityHeaders:
    """Тесты заголовков безопасности."""

    def test_x_frame_options(self, client):
        """Заголовок X-Frame-Options присутствует."""
        response = client.get("/")
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"

    def test_x_content_type_options(self, client):
        """Заголовок X-Content-Type-Options присутствует."""
        response = client.get("/")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_xss_protection(self, client):
        """Заголовок X-XSS-Protection присутствует."""
        response = client.get("/")
        assert "1" in response.headers.get("X-XSS-Protection", "")
