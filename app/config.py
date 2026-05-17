"""Конфигурация приложения из переменных окружения."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

class Config:
    SECRET_KEY = os.getenv("APP_SECRET_KEY", "dev-secret-key")
    DEBUG = os.getenv("APP_DEBUG", "false").lower() in ("true", "1")
    HOST = os.getenv("APP_HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", os.getenv("APP_PORT", "5000")))
    PASSWORD = os.getenv("APP_PASSWORD", None)
    DATABASE = str(Path(__file__).parent.parent / "data" / "app.db")
    CITY = "Красноярск"

    # Районы Красноярска с координатами
    DISTRICTS = {
        "Советский": (56.0341, 92.8598),
        "Центральный": (56.0101, 92.8714),
        "Октябрьский": (56.0183, 92.9156),
        "Железнодорожный": (56.0044, 92.8285),
        "Свердловский": (56.0269, 92.9532),
        "Кировский": (55.9871, 92.9714),
        "Ленинский": (55.9912, 92.8102),
    }

    MICRODISTRICTS = {
        "Северный": "Советский",
        "Взлётка": "Советский",
        "Покровка": "Центральный",
        "Зелёная Роща": "Советский",
        "Академгородок": "Октябрьский",
        "Солнечный": "Советский",
        "Пашенный": "Ленинский",
        "Черёмушки": "Кировский",
        "Первомайский": "Свердловский",
        "Ветлужанка": "Октябрьский",
        "Копылова": "Октябрьский",
        "Студгородок": "Октябрьский",
        "Николаевка": "Железнодорожный",
        "Предмостная площадь": "Свердловский",
        "ГорДК": "Центральный",
        "Цирк": "Центральный",
        "Торговый квартал": "Центральный",
        "Мичурина": "Ленинский",
        "Сопка": "Октябрьский",
        "Каменный квартал": "Советский",
    }

    # Парсер
    PARSER_DELAY_MIN = float(os.getenv("APP_PARSER_DELAY_MIN", "3"))
    PARSER_DELAY_MAX = float(os.getenv("APP_PARSER_DELAY_MAX", "6"))
    PARSER_MAX_ITEMS = int(os.getenv("APP_PARSER_MAX_ITEMS", "15"))

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]

config = Config()
