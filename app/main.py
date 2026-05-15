"""
Главный модуль Flask-приложения Квартира-Компаратор.
Содержит маршруты, SocketIO-события и логику сравнения квартир.
"""

import json
import logging
import os
import statistics
import uuid
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from threading import Thread
from typing import Optional

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    Response,
    send_from_directory,
    make_response,
)
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash, generate_password_hash

from app.config import config
from app.models import SearchQuery, init_db, get_db_session
from app.geocoder import geocoder_service
from app.avito_parser import run_parser, run_parse_single

# === Настройка логирования ===
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
if config.LOG_FILE:
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(file_handler)

logger = logging.getLogger(__name__)

# === Инициализация приложения ===
app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Создаём директорию для данных
data_dir = Path(__file__).parent.parent / "data"
data_dir.mkdir(exist_ok=True)

# Инициализация БД
init_db()


# === Middleware: безопасность ===
@app.after_request
def add_security_headers(response: Response) -> Response:
    """Добавляет заголовки безопасности ко всем ответам."""
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not config.DEBUG:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# === Аутентификация (HTTP Basic Auth) ===
def check_auth(password: str) -> bool:
    """Проверяет пароль для Basic Auth."""
    if not config.APP_PASSWORD:
        return True
    return password == config.APP_PASSWORD


def authenticate():
    """Отправляет 401 ответ для запроса аутентификации."""
    return Response(
        "Требуется авторизация. Введите пароль.",
        401,
        {"WWW-Authenticate": 'Basic realm="Kvartira Comparator"'},
    )


def requires_auth(f):
    """Декоратор для защиты маршрутов паролем."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not config.APP_PASSWORD:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


# === Маршруты ===

@app.route("/")
@requires_auth
def index():
    """Главная страница с формой ввода параметров."""
    districts = list(config.DISTRICTS.keys())
    microdistricts = list(config.MICRODISTRICTS.keys())
    return render_template(
        "index.html",
        districts=districts,
        microdistricts=microdistricts,
        default_distance=config.DEFAULT_MAX_DISTANCE_KM,
        default_tolerance=config.DEFAULT_AREA_TOLERANCE,
        default_depth=config.DEFAULT_SEARCH_DEPTH,
    )


@app.route("/search", methods=["POST"])
@requires_auth
def search():
    """Запускает поиск аналогов и возвращает ID запроса."""
    try:
        data = request.get_json() or request.form.to_dict()

        # Валидация обязательных полей
        address = data.get("address", "").strip()
        rooms = data.get("rooms", "").strip()
        price = data.get("price", "")

        if not address:
            return jsonify({"error": "Укажите адрес квартиры"}), 400
        if not rooms:
            return jsonify({"error": "Укажите количество комнат"}), 400
        if not price:
            return jsonify({"error": "Укажите цену"}), 400

        try:
            price = int(str(price).replace(" ", "").replace(",", ""))
        except (ValueError, TypeError):
            return jsonify({"error": "Некорректная цена"}), 400

        # Извлекаем параметры
        district = data.get("district", "").strip() or None
        total_area = _parse_float(data.get("total_area"))
        kitchen_area = _parse_float(data.get("kitchen_area"))
        floor = _parse_int(data.get("floor"))
        total_floors = _parse_int(data.get("total_floors"))
        year_built = _parse_int(data.get("year_built"))
        area_tolerance = _parse_float(data.get("area_tolerance")) or config.DEFAULT_AREA_TOLERANCE
        max_distance = _parse_float(data.get("max_distance")) or config.DEFAULT_MAX_DISTANCE_KM
        search_depth = _parse_int(data.get("search_depth")) or config.DEFAULT_SEARCH_DEPTH

        # Создаём запись в БД
        session = get_db_session()
        query = SearchQuery(
            address=address,
            district=district,
            rooms=rooms,
            total_area=total_area,
            kitchen_area=kitchen_area,
            floor=floor,
            total_floors=total_floors,
            year_built=year_built,
            price=price,
            area_tolerance=area_tolerance,
            max_distance_km=max_distance,
            search_depth=min(search_depth, 20),
            status="pending",
        )
        session.add(query)
        session.commit()
        query_id = query.public_id
        session.close()

        # Запускаем парсинг в фоновом потоке
        thread = Thread(
            target=_run_search_task,
            args=(query_id, address, district, rooms, price, total_area,
                  area_tolerance, max_distance, search_depth),
            daemon=True,
        )
        thread.start()

        return jsonify({"query_id": query_id, "status": "processing"})

    except Exception as e:
        logger.error(f"Ошибка запуска поиска: {e}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500


@app.route("/results/<query_id>")
@requires_auth
def results(query_id: str):
    """Страница результатов сравнения."""
    session = get_db_session()
    query = session.query(SearchQuery).filter_by(public_id=query_id).first()
    session.close()

    if not query:
        return render_template("index.html", error="Запрос не найден"), 404

    if query.status == "pending" or query.status == "processing":
        return render_template("results.html", query=query, loading=True)

    # Десериализуем результаты
    results_data = json.loads(query.results_json) if query.results_json else []
    analytics = json.loads(query.analytics_json) if query.analytics_json else {}

    districts = list(config.DISTRICTS.keys())
    microdistricts = list(config.MICRODISTRICTS.keys())

    return render_template(
        "results.html",
        query=query,
        results=results_data,
        analytics=analytics,
        loading=False,
        districts=districts,
        microdistricts=microdistricts,
    )


@app.route("/shared/<query_id>")
def shared_results(query_id: str):
    """Публичная страница результатов (доступна без авторизации 24 часа)."""
    session = get_db_session()
    query = session.query(SearchQuery).filter_by(public_id=query_id).first()
    session.close()

    if not query:
        return "Результат не найден", 404

    # Проверяем срок жизни
    if query.expires_at and datetime.now(timezone.utc) > query.expires_at:
        return "Срок действия ссылки истёк", 410

    results_data = json.loads(query.results_json) if query.results_json else []
    analytics = json.loads(query.analytics_json) if query.analytics_json else {}

    return render_template(
        "results.html",
        query=query,
        results=results_data,
        analytics=analytics,
        loading=False,
        shared=True,
    )


@app.route("/status/<query_id>")
@requires_auth
def check_status(query_id: str):
    """Проверка статуса запроса (API для polling)."""
    session = get_db_session()
    query = session.query(SearchQuery).filter_by(public_id=query_id).first()
    session.close()

    if not query:
        return jsonify({"error": "Запрос не найден"}), 404

    return jsonify({
        "status": query.status,
        "analogs_count": query.analogs_count,
        "error_message": query.error_message,
    })


@app.route("/history")
@requires_auth
def history():
    """Возвращает последние 10 запросов."""
    session = get_db_session()
    queries = (
        session.query(SearchQuery)
        .filter(SearchQuery.status == "completed")
        .order_by(SearchQuery.created_at.desc())
        .limit(10)
        .all()
    )
    history_data = [
        {
            "id": q.public_id,
            "address": q.address,
            "rooms": q.rooms,
            "price": q.price,
            "analogs_count": q.analogs_count,
            "created_at": q.created_at.isoformat() if q.created_at else None,
        }
        for q in queries
    ]
    session.close()
    return jsonify(history_data)


@app.route("/export/<query_id>")
@requires_auth
def export_csv(query_id: str):
    """Экспорт результатов в CSV."""
    session = get_db_session()
    query = session.query(SearchQuery).filter_by(public_id=query_id).first()
    session.close()

    if not query or not query.results_json:
        return "Данные не найдены", 404

    results_data = json.loads(query.results_json)

    # Генерируем CSV
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Комнаты", "Адрес", "Цена (руб)", "Площадь (м²)",
        "Цена/м²", "Этаж", "Этажность", "Год постройки",
        "Ссылка", "Примечание"
    ])

    for item in results_data:
        price_per_m2 = ""
        if item.get("price") and item.get("total_area"):
            price_per_m2 = round(item["price"] / item["total_area"])

        writer.writerow([
            item.get("rooms", ""),
            item.get("address", ""),
            item.get("price", ""),
            item.get("total_area", ""),
            price_per_m2,
            item.get("floor", ""),
            item.get("total_floors", ""),
            item.get("year_built", ""),
            item.get("url", ""),
            item.get("note", ""),
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=analogs_{query_id[:8]}.csv"
    )
    return response


@app.route("/autofill", methods=["POST"])
@requires_auth
def autofill():
    """Автозаполнение формы из ссылки на Avito."""
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url or "avito.ru" not in url:
        return jsonify({"error": "Укажите корректную ссылку на Avito"}), 400

    try:
        result = run_parse_single(url)
        if result:
            return jsonify(result)
        return jsonify({"error": "Не удалось получить данные из объявления"}), 404
    except Exception as e:
        logger.error(f"Ошибка автозаполнения: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/static/manifest.json")
def manifest():
    """PWA manifest."""
    return send_from_directory(app.static_folder, "manifest.json")


@app.route("/sw.js")
def service_worker():
    """Service Worker для PWA."""
    return send_from_directory(app.static_folder, "sw.js")


# === SocketIO события ===

@socketio.on("connect")
def handle_connect():
    """Клиент подключился через WebSocket."""
    logger.debug("WebSocket клиент подключён")


@socketio.on("subscribe")
def handle_subscribe(data):
    """Подписка на обновления статуса запроса."""
    query_id = data.get("query_id")
    if query_id:
        logger.debug(f"Клиент подписался на {query_id}")


# === Фоновая задача парсинга ===

def _run_search_task(
    query_id: str,
    address: str,
    district: Optional[str],
    rooms: str,
    price: int,
    total_area: Optional[float],
    area_tolerance: float,
    max_distance: float,
    search_depth: int,
) -> None:
    """
    Фоновая задача: парсит Avito, проводит гео-валидацию и аналитику.

    Args:
        query_id: ID запроса в БД.
        address: Адрес пользователя.
        district: Район.
        rooms: Количество комнат.
        price: Цена квартиры пользователя.
        total_area: Площадь квартиры.
        area_tolerance: Допуск по площади.
        max_distance: Макс. расстояние (км).
        search_depth: Количество аналогов.
    """
    session = get_db_session()

    try:
        # Обновляем статус
        query = session.query(SearchQuery).filter_by(public_id=query_id).first()
        if not query:
            return
        query.status = "processing"
        session.commit()

        # Прогресс через SocketIO
        def progress_cb(current, total, message):
            socketio.emit("progress", {
                "query_id": query_id,
                "current": current,
                "total": total,
                "message": message,
            })

        # 1. Геокодируем адрес пользователя
        progress_cb(0, 100, "Определяем координаты адреса...")
        user_coords = geocoder_service.resolve_user_location(address, district)
        if user_coords:
            query.user_lat, query.user_lon = user_coords
            session.commit()

        # 2. Рассчитываем диапазон цен для фильтрации
        min_price = int(price * 0.5) if price else None
        max_price = int(price * 1.8) if price else None

        # Диапазон площади
        min_area = None
        max_area = None
        if total_area:
            min_area = total_area * (1 - area_tolerance)
            max_area = total_area * (1 + area_tolerance)

        # 3. Запускаем парсер
        progress_cb(5, 100, "Запуск парсера Avito...")
        raw_results = run_parser(
            rooms=rooms,
            district=district,
            min_price=min_price,
            max_price=max_price,
            min_area=min_area,
            max_area=max_area,
            max_analogs=search_depth,
            progress_callback=progress_cb,
        )

        # 4. Гео-валидация
        progress_cb(80, 100, "Гео-валидация результатов...")
        validated_results = []

        for listing in raw_results:
            listing_address = listing.get("address", "")
            if not listing_address and district:
                listing_address = district

            if listing_address and user_coords:
                listing_coords = geocoder_service.geocode(listing_address)
                if listing_coords:
                    listing["latitude"] = listing_coords[0]
                    listing["longitude"] = listing_coords[1]
                    distance = geocoder_service.calculate_distance(
                        user_coords, listing_coords
                    )
                    listing["distance_km"] = distance

                    if distance <= max_distance:
                        validated_results.append(listing)
                    else:
                        logger.debug(
                            f"Объявление отброшено: расстояние {distance:.1f} км > {max_distance} км"
                        )
                else:
                    # Если не можем геокодировать — добавляем с пометкой
                    listing["distance_km"] = None
                    validated_results.append(listing)
            else:
                listing["distance_km"] = None
                validated_results.append(listing)

        # 5. Фильтрация по комнатам (строгая)
        strict_results = []
        relaxed_results = []

        for item in validated_results:
            if _rooms_match(item.get("rooms"), rooms):
                strict_results.append(item)
            else:
                item["note"] = "Отклонение по кол-ву комнат"
                relaxed_results.append(item)

        # Если мало строгих — добавляем расширенные
        final_results = strict_results.copy()
        if len(strict_results) < 5:
            final_results.extend(relaxed_results[:5 - len(strict_results)])

        # 6. Аналитика
        progress_cb(90, 100, "Расчёт аналитики...")
        analytics = _compute_analytics(final_results, strict_results, price, total_area, query.year_built)

        # 7. Сохраняем результаты
        query.results_json = json.dumps(final_results, ensure_ascii=False)
        query.analytics_json = json.dumps(analytics, ensure_ascii=False)
        query.analogs_count = len(final_results)
        query.status = "completed"
        query.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=config.SHARE_LINK_TTL
        )
        session.commit()

        progress_cb(100, 100, "Готово!")
        socketio.emit("completed", {"query_id": query_id, "status": "completed"})

    except Exception as e:
        logger.error(f"Ошибка фоновой задачи для {query_id}: {e}")
        query = session.query(SearchQuery).filter_by(public_id=query_id).first()
        if query:
            query.status = "error"
            query.error_message = str(e)
            session.commit()
        socketio.emit("error", {"query_id": query_id, "error": str(e)})

    finally:
        session.close()


# === Вспомогательные функции ===

def _rooms_match(listing_rooms: Optional[str], target_rooms: str) -> bool:
    """Проверяет совпадение количества комнат."""
    if not listing_rooms:
        return True  # Если не определено, считаем подходящим

    listing_rooms = str(listing_rooms).lower().strip()
    target = target_rooms.lower().strip()

    if target == "studio":
        return listing_rooms in ("студия", "studio", "с", "0")
    elif target == "4+":
        try:
            return int(listing_rooms) >= 4
        except (ValueError, TypeError):
            return False
    else:
        return listing_rooms == target


def _compute_analytics(
    all_results: list,
    strict_results: list,
    user_price: int,
    user_area: Optional[float],
    user_year: Optional[int],
) -> dict:
    """
    Вычисляет аналитические метрики для сравнения.

    Returns:
        Словарь с аналитикой.
    """
    analytics = {
        "total_analogs": len(all_results),
        "strict_analogs": len(strict_results),
        "warnings": [],
    }

    # Цены за м² для строгих аналогов
    prices_per_m2 = []
    prices = []
    years = []

    for item in strict_results:
        p = item.get("price")
        a = item.get("total_area")
        if p and a and a > 0:
            prices_per_m2.append(p / a)
            prices.append(p)
        y = item.get("year_built")
        if y:
            years.append(y)

    if prices_per_m2:
        avg_price_m2 = statistics.mean(prices_per_m2)
        median_price_m2 = statistics.median(prices_per_m2)
        analytics["avg_price_per_m2"] = round(avg_price_m2)
        analytics["median_price_per_m2"] = round(median_price_m2)
        analytics["min_price_per_m2"] = round(min(prices_per_m2))
        analytics["max_price_per_m2"] = round(max(prices_per_m2))

        # Цена пользователя за м²
        if user_area and user_area > 0:
            user_price_m2 = user_price / user_area
            analytics["user_price_per_m2"] = round(user_price_m2)
            deviation = ((user_price_m2 - avg_price_m2) / avg_price_m2) * 100
            analytics["price_deviation_pct"] = round(deviation, 1)

            if deviation > 15:
                analytics["warnings"].append(
                    f"Возможно, цена завышена: ваша цена за м² на "
                    f"{abs(round(deviation, 1))}% выше средней по аналогам."
                )
            elif deviation < -15:
                analytics["warnings"].append(
                    f"Цена ниже рынка: ваша цена за м² на "
                    f"{abs(round(deviation, 1))}% ниже средней по аналогам."
                )

    if prices:
        analytics["median_price"] = round(statistics.median(prices))
        analytics["avg_price"] = round(statistics.mean(prices))

    # Год постройки
    if years:
        avg_year = statistics.mean(years)
        analytics["avg_year_built"] = round(avg_year)

        if user_year:
            year_diff = user_year - avg_year
            analytics["year_deviation"] = round(year_diff, 1)

            if abs(year_diff) > 10:
                if year_diff > 0:
                    analytics["warnings"].append(
                        f"Год постройки дома значительно новее аналогов "
                        f"(разница {round(abs(year_diff))} лет). "
                        f"Это может объяснять более высокую цену."
                    )
                else:
                    analytics["warnings"].append(
                        f"Год постройки дома значительно старше аналогов "
                        f"(разница {round(abs(year_diff))} лет). "
                        f"Это может объяснять разницу в цене."
                    )

            # Эвристика корректировки по возрасту
            price_correction_pct = year_diff * 1.0  # 1% за каждый год
            analytics["year_price_correction_pct"] = round(price_correction_pct, 1)

    # Гистограмма данных
    if prices_per_m2:
        analytics["histogram_data"] = [round(p) for p in sorted(prices_per_m2)]

    # Предупреждение о недостатке данных
    if len(strict_results) < 5:
        analytics["warnings"].insert(
            0,
            f"Найдено мало аналогов с точным совпадением по комнатам "
            f"({len(strict_results)} из рекомендуемых 5). "
            f"Результаты могут быть неточными."
        )

    return analytics


def _parse_float(value) -> Optional[float]:
    """Безопасный парсинг float."""
    if not value:
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return None


def _parse_int(value) -> Optional[int]:
    """Безопасный парсинг int."""
    if not value:
        return None
    try:
        return int(str(value).replace(" ", ""))
    except (ValueError, TypeError):
        return None


# === Точка входа ===

if __name__ == "__main__":
    logger.info(f"Запуск приложения на {config.HOST}:{config.PORT}")
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        allow_unsafe_werkzeug=True,
    )
