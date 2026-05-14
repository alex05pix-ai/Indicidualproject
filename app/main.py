"""Flask-приложение «Avito Comparator».

Содержит:
- Роуты:
  - ``GET  /``                       — стартовая форма;
  - ``POST /search``                 — запуск поиска и аналитики;
  - ``GET  /result/<share_id>``      — просмотр сохранённого сравнения;
  - ``GET  /history``                — список последних запросов;
  - ``GET  /export/<share_id>.csv``  — выгрузка таблицы аналогов в CSV;
  - ``GET  /healthz``                — health-check;
  - ``GET  /manifest.json``,
    ``GET  /sw.js``                  — отдача PWA-манифеста и service-worker.
- Защиту HTTP Basic Auth (если задан ``APP_PASSWORD``).
- Защиту от CSRF через ``Flask-WTF``.
- Заголовки безопасности (CSP, X-Frame-Options, и т.д.).
- WebSocket-канал ``/socket.io`` для прогресс-бара парсинга.

Запуск под Gunicorn::

    gunicorn -k eventlet -w 1 -b 0.0.0.0:8000 'app.main:app'
"""

from __future__ import annotations

import csv
import io
import logging
import threading
import uuid
from functools import wraps
from typing import Any, Optional

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, join_room
from flask_wtf.csrf import CSRFProtect, generate_csrf

from .analytics import UserApartment, analyze
from .avito_parser import SearchParams, run_search
from .config import (
    DISTRICTS,
    MICRODISTRICT_TO_DISTRICT,
    MICRODISTRICTS,
    ROOM_OPTIONS,
    settings,
)
from .geocoder import GeoPoint, get_geocoder
from .models import CachedResult, QueryHistory, db, init_db

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Application factory
# -----------------------------------------------------------------------------


def create_app() -> tuple[Flask, SocketIO]:
    """Создаёт Flask-приложение и привязывает к нему SocketIO."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )

    # --- Конфигурация ---
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(settings.domain_name),  # secure только за HTTPS
        WTF_CSRF_TIME_LIMIT=None,  # CSRF-токен живёт всю сессию
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # 2 MiB на форму
    )

    # --- Создаём data-каталог для SQLite, если его нет ---
    if settings.database_url.startswith("sqlite"):
        data_dir = settings.project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

    # --- Расширения ---
    db.init_app(app)
    csrf = CSRFProtect(app)

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per hour", "20 per minute"],
        storage_uri="memory://",
    )

    # SocketIO — eventlet рекомендован для Gunicorn в продакшне.
    # cors_allowed_origins ограничен своим доменом, если задан DOMAIN_NAME.
    cors_origins = (
        [f"https://{settings.domain_name}", f"http://{settings.domain_name}"]
        if settings.domain_name
        else "*"
    )
    socketio = SocketIO(
        app,
        cors_allowed_origins=cors_origins,
        async_mode="threading",  # совместимо с Flask dev-сервером
        logger=False,
        engineio_logger=False,
    )

    # --- Инициализация БД ---
    with app.app_context():
        try:
            init_db(app)
        except Exception as e:  # noqa: BLE001
            logger.warning("DB init failed (will retry on first request): %s", e)

    # --- Хуки безопасности ---
    @app.after_request
    def _set_security_headers(response: Response) -> Response:
        # Базовые заголовки безопасности.
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # CSP — разрешаем CDN Bootstrap/Chart.js + self для остального.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://cdn.jsdelivr.net; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none';",
        )
        if settings.domain_name and request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    # --- HTTP Basic Auth (если задан APP_PASSWORD) ---
    def require_basic_auth(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not settings.auth_enabled:
                return view(*args, **kwargs)
            auth = request.authorization
            if (
                not auth
                or auth.username != settings.basic_auth_user
                or auth.password != settings.password
            ):
                return Response(
                    "Authentication required",
                    status=401,
                    headers={"WWW-Authenticate": 'Basic realm="Avito Comparator"'},
                )
            return view(*args, **kwargs)

        return wrapper

    # --- Контекст для шаблонов ---
    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "city_display": settings.city_display,
            "districts": DISTRICTS,
            "microdistricts": MICRODISTRICTS,
            "microdistrict_to_district": MICRODISTRICT_TO_DISTRICT,
            "room_options": ROOM_OPTIONS,
            "csrf_token": generate_csrf,
            "auth_enabled": settings.auth_enabled,
        }

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify({"status": "ok", "version": "1.0.0"})

    @app.get("/")
    @require_basic_auth
    def index() -> str:
        # Гарантируем session_id для привязки сокет-комнаты к запросу
        if "sid" not in session:
            session["sid"] = uuid.uuid4().hex
        return render_template("index.html", sid=session["sid"])

    @app.get("/history")
    @require_basic_auth
    def history() -> str:
        items = (
            QueryHistory.query.order_by(QueryHistory.created_at.desc())
            .limit(settings.history_limit)
            .all()
        )
        return render_template("history.html", items=[i.to_dict() for i in items])

    @app.post("/search")
    @require_basic_auth
    @limiter.limit("5 per minute")
    def search() -> Response:
        """Запускает парсинг + аналитику и возвращает JSON со ссылкой на result.

        Парсинг выполняется в фоновом потоке, прогресс отдаётся через SocketIO
        в комнату ``sid`` (id сессии). По окончании клиент получает событие
        ``done`` с redirect-URL.
        """
        try:
            payload = _parse_form(request.form)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        sid = session.get("sid")
        if not sid:
            sid = uuid.uuid4().hex
            session["sid"] = sid

        # Запускаем поиск в фоне, чтобы HTTP-ответ не висел.
        thread = threading.Thread(
            target=_run_search_job,
            args=(app, socketio, sid, payload),
            daemon=True,
        )
        thread.start()
        return jsonify({"status": "started", "sid": sid})

    @app.get("/result/<share_id>")
    @require_basic_auth
    def result(share_id: str) -> str:
        cached = CachedResult.query.filter_by(share_id=share_id).first()
        if cached is None:
            abort(404)
        if cached.is_expired():
            abort(410, description="Срок хранения этой ссылки истёк")
        data = cached.get_payload()
        return render_template(
            "results.html",
            share_id=share_id,
            data=data,
            created_at=cached.created_at.isoformat(),
        )

    @app.get("/export/<share_id>.csv")
    @require_basic_auth
    def export_csv(share_id: str) -> Response:
        cached = CachedResult.query.filter_by(share_id=share_id).first()
        if cached is None or cached.is_expired():
            abort(404)
        data = cached.get_payload()
        listings = data.get("analytics", {}).get("listings", [])

        buf = io.StringIO()
        # BOM, чтобы Excel корректно открыл UTF-8
        buf.write("\ufeff")
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(
            [
                "Кол-во комнат",
                "Адрес",
                "Цена, руб.",
                "Площадь, м²",
                "Цена/м², руб.",
                "Этаж",
                "Этажность",
                "Год постройки",
                "Тип дома",
                "Расстояние, км",
                "Ссылка",
                "Примечание",
            ]
        )
        for it in listings:
            note = "Отклонение по комнатам" if it.get("rooms_mismatch") else ""
            writer.writerow(
                [
                    it.get("rooms_raw") or it.get("rooms") or "",
                    it.get("address") or "",
                    it.get("price") or "",
                    it.get("total_area") or "",
                    it.get("price_per_m2") or "",
                    it.get("floor") or "",
                    it.get("floors_total") or "",
                    it.get("year_built") or "",
                    it.get("house_type") or "",
                    f"{it.get('distance_km'):.2f}" if it.get("distance_km") is not None else "",
                    it.get("url") or "",
                    note,
                ]
            )

        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="comparison_{share_id}.csv"',
            },
        )

    # PWA assets
    @app.get("/manifest.json")
    def manifest() -> Response:
        return send_from_directory(app.static_folder, "manifest.json", mimetype="application/manifest+json")

    @app.get("/sw.js")
    def service_worker() -> Response:
        # Service worker должен отдаваться с корня (scope), поэтому отдельный роут.
        response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    # CSRF не нужен на сокет-handshake и health — а вот /search через JSON-форму
    # сохраняет CSRF (мы посылаем заголовок).
    csrf.exempt(healthz)

    # ------------------------------------------------------------------
    # SocketIO events
    # ------------------------------------------------------------------

    @socketio.on("connect")
    def _on_connect() -> None:
        sid = session.get("sid")
        if sid:
            join_room(sid)
            logger.info("Socket joined room %s", sid)

    @socketio.on("subscribe")
    def _on_subscribe(data: dict) -> None:
        sid = (data or {}).get("sid") or session.get("sid")
        if sid:
            join_room(sid)

    return app, socketio


# -----------------------------------------------------------------------------
# Helpers (вне фабрики, чтобы их можно было использовать в фоне)
# -----------------------------------------------------------------------------


def _parse_form(form) -> dict[str, Any]:
    """Валидирует и нормализует данные формы поиска.

    Возвращает словарь с готовыми значениями. Поднимает ``ValueError``
    при критических ошибках валидации.
    """
    address = (form.get("address") or "").strip()
    if not address:
        raise ValueError("Поле «Адрес» обязательно")

    rooms = (form.get("rooms") or "").strip()
    valid_rooms = {key for key, _ in ROOM_OPTIONS}
    if rooms not in valid_rooms:
        raise ValueError("Некорректное количество комнат")

    try:
        price = float((form.get("price") or "").replace(" ", "").replace(",", "."))
    except ValueError as e:
        raise ValueError("Цена должна быть числом") from e
    if price <= 0:
        raise ValueError("Цена должна быть больше нуля")

    def _opt_float(name: str) -> Optional[float]:
        raw = (form.get(name) or "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _opt_int(name: str) -> Optional[int]:
        raw = (form.get(name) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    district = (form.get("district") or "").strip() or None

    return {
        "address": address,
        "district": district,
        "rooms": rooms,
        "total_area": _opt_float("total_area"),
        "kitchen_area": _opt_float("kitchen_area"),
        "floor": _opt_int("floor"),
        "floors_total": _opt_int("floors_total"),
        "year_built": _opt_int("year_built"),
        "price": price,
        "radius_km": _opt_float("radius_km") or 2.0,
        "area_tolerance": _opt_float("area_tolerance") or 0.15,
        "depth": min(_opt_int("depth") or 20, settings.max_listings),
    }


def _run_search_job(app: Flask, socketio: SocketIO, sid: str, payload: dict[str, Any]) -> None:
    """Фоновая задача: парсинг + геофильтрация + аналитика + сохранение в БД.

    Все ошибки ловятся и отправляются клиенту через сокет (``error``).
    """

    def emit(event: str, data: dict) -> None:
        try:
            socketio.emit(event, data, room=sid)
        except Exception as e:  # noqa: BLE001
            logger.debug("socketio.emit failed: %s", e)

    def progress(percent: int, message: str) -> None:
        emit("progress", {"percent": percent, "message": message})

    try:
        with app.app_context():
            emit("progress", {"percent": 1, "message": "Геокодирую адрес…"})
            geocoder = get_geocoder()

            user_query = payload["address"]
            if payload.get("district"):
                user_query = f"{user_query}, {payload['district']}"

            user_point: Optional[GeoPoint] = geocoder.geocode(
                user_query, city_hint=settings.city_display
            )
            if not user_point and payload.get("district"):
                # fallback — только по району
                user_point = geocoder.geocode(
                    payload["district"], city_hint=settings.city_display
                )

            if not user_point:
                emit(
                    "error",
                    {"message": "Не удалось распознать адрес. Уточните район или микрорайон."},
                )
                return

            params = SearchParams(
                rooms=payload["rooms"],
                address=payload["address"],
                district=payload.get("district"),
                total_area=payload.get("total_area"),
                area_tolerance=payload["area_tolerance"],
                price=payload["price"],
                radius_km=payload["radius_km"],
                depth=payload["depth"],
            )

            try:
                listings = run_search(params, progress_cb=progress)
            except Exception as e:  # noqa: BLE001
                logger.exception("Avito parsing failed: %s", e)
                emit(
                    "error",
                    {
                        "message": (
                            "Не удалось получить данные с Avito. "
                            "Возможна блокировка или капча. Попробуйте позже."
                        )
                    },
                )
                return

            # Геофильтрация и расчёт расстояний
            progress(92, "Проверяю расстояния…")
            filtered: list[dict[str, Any]] = []
            for lst in listings:
                addr = lst.address or lst.district or payload.get("district") or ""
                point = geocoder.geocode(addr, city_hint=settings.city_display) if addr else None
                if point:
                    lst.latitude = point.latitude
                    lst.longitude = point.longitude
                    lst.distance_km = round(geocoder.distance_km(user_point, point), 3)
                else:
                    lst.distance_km = None

                # Фильтр по радиусу — пропускаем те, что не геокодировались
                if (
                    lst.distance_km is not None
                    and lst.distance_km > payload["radius_km"]
                ):
                    continue
                filtered.append(lst.to_dict())

            # Аналитика
            user_apt = UserApartment(
                address=payload["address"],
                rooms=payload["rooms"],
                price=payload["price"],
                total_area=payload.get("total_area"),
                year_built=payload.get("year_built"),
            )
            result = analyze(user_apt, filtered)

            # Сохраняем результат и историю
            result_dict = result.to_dict()
            result_dict["filters"] = {
                "radius_km": payload["radius_km"],
                "area_tolerance": payload["area_tolerance"],
                "depth": payload["depth"],
                "district": payload.get("district"),
            }

            cached = CachedResult.create(
                {"analytics": result_dict, "params": payload, "user_point": user_point.coords},
                ttl_hours=settings.share_ttl_hours,
            )
            db.session.add(cached)

            history_entry = QueryHistory(
                address=payload["address"],
                district=payload.get("district"),
                rooms=payload["rooms"],
                total_area=payload.get("total_area"),
                kitchen_area=payload.get("kitchen_area"),
                floor=payload.get("floor"),
                floors_total=payload.get("floors_total"),
                year_built=payload.get("year_built"),
                price=payload["price"],
                radius_km=payload["radius_km"],
                area_tolerance=payload["area_tolerance"],
                depth=payload["depth"],
                listings_found=result.strict_count,
                avg_price_per_m2=result.avg_price_per_m2,
                median_price=result.median_price,
                share_id=cached.share_id,
            )
            db.session.add(history_entry)
            db.session.commit()

            emit("progress", {"percent": 100, "message": "Готово"})
            emit("done", {"share_id": cached.share_id, "redirect": f"/result/{cached.share_id}"})

    except Exception as e:  # noqa: BLE001
        logger.exception("Search job failed: %s", e)
        emit("error", {"message": f"Внутренняя ошибка: {e}"})


# -----------------------------------------------------------------------------
# Module-level WSGI entrypoint
# -----------------------------------------------------------------------------

app, socketio = create_app()


if __name__ == "__main__":
    socketio.run(
        app,
        host=settings.host,
        port=settings.port,
        debug=settings.debug,
        allow_unsafe_werkzeug=True,
    )
