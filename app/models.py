"""Модели и работа с БД (SQLite)."""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from app.config import config


def get_db():
    """Подключение к SQLite."""
    Path(config.DATABASE).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создание таблиц."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS searches (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            address TEXT NOT NULL,
            district TEXT,
            rooms TEXT NOT NULL,
            price INTEGER NOT NULL,
            total_area REAL,
            floor INTEGER,
            year_built INTEGER,
            results_json TEXT,
            analytics_json TEXT,
            status TEXT DEFAULT 'pending'
        );
    """)
    conn.commit()
    conn.close()


def save_search(data: dict) -> str:
    """Сохраняет поисковый запрос."""
    search_id = str(uuid.uuid4())[:8]
    conn = get_db()
    conn.execute(
        """INSERT INTO searches (id, created_at, address, district, rooms, price, total_area, floor, year_built, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (search_id, datetime.now().isoformat(), data["address"], data.get("district"),
         data["rooms"], data["price"], data.get("total_area"), data.get("floor"), data.get("year_built"))
    )
    conn.commit()
    conn.close()
    return search_id


def update_search_results(search_id: str, results: list, analytics: dict):
    """Обновляет результаты поиска."""
    conn = get_db()
    conn.execute(
        "UPDATE searches SET results_json=?, analytics_json=?, status='completed' WHERE id=?",
        (json.dumps(results, ensure_ascii=False), json.dumps(analytics, ensure_ascii=False), search_id)
    )
    conn.commit()
    conn.close()


def update_search_error(search_id: str, error: str):
    """Обновляет статус ошибки."""
    conn = get_db()
    conn.execute("UPDATE searches SET status='error', analytics_json=? WHERE id=?",
                 (json.dumps({"error": error}, ensure_ascii=False), search_id))
    conn.commit()
    conn.close()


def get_search(search_id: str) -> dict:
    """Получает результаты поиска."""
    conn = get_db()
    row = conn.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    result["results"] = json.loads(result["results_json"]) if result["results_json"] else []
    result["analytics"] = json.loads(result["analytics_json"]) if result["analytics_json"] else {}
    return result


def get_history(limit=10) -> list:
    """Последние поиски."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, created_at, address, rooms, price, status FROM searches ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
