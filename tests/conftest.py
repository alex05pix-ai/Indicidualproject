"""Общие фикстуры pytest.

Перед импортом приложения подменяем переменные окружения, чтобы тесты
работали с in-memory SQLite и без обращения к сети/Avito.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Гарантируем, что корень проекта находится в sys.path для абсолютных импортов.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Безопасные дефолты для тестов.
os.environ.setdefault("APP_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("APP_HEADLESS", "true")
os.environ.setdefault("APP_LOG_LEVEL", "WARNING")
# Авторизация в тестах отключена.
os.environ.pop("APP_PASSWORD", None)


@pytest.fixture()
def app():
    """Создаёт fresh Flask-приложение и инициализирует БД in-memory."""
    from app.main import create_app  # импорт после правки env

    flask_app, _socketio = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with flask_app.app_context():
        from app.models import db, init_db
        init_db(flask_app)
        yield flask_app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()
