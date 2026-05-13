"""
Flask-приложение для сравнения стоимости квартир (Avito / Красноярск).

Архитектура:
    * /             — стартовая форма (index.html).
    * /search       — POST: запускает фоновую задачу парсинга, отдаёт job_id.
    * /progress/<id>— страница ожидания с прогресс-баром (SocketIO).
    * /results/<id> — страница результата (results.html).
    * /export/<id>  — CSV-выгрузка таблицы аналогов.
    * /history      — последние 10 запросов.
    * /share/<token>— просмотр расшаренного результата.

Парсер запускается в отдельном потоке (threading.Thread). Внутри потока
поднимается собственный asyncio-event-loop. Прогресс пробрасывается в UI
через Flask-SocketIO (room == job_id).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_socketio import SocketIO, join_room

import config
from avito_parser import AvitoParser, SearchParams
from models import SearchHistory, SharedResult, get_session, init_db
from utils import analyze, fmt_money, fmt_number, listings_to_csv


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
def _setup_logging() -> None:
    handler = RotatingFileHandler(
        config.LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # не дублировать handler при reload
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    # дублируем в консоль
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


_setup_logging()
log = logging.getLogger("app")


# ---------------------------------------------------------------------------
# Flask + SocketIO
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.jinja_env.filters["money"] = fmt_money
app.jinja_env.filters["num"] = fmt_number

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
init_db()

# ---------------------------------------------------------------------------
# Хранилище фоновых задач (in-memory)
# ---------------------------------------------------------------------------
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _set_job(job_id: str, **kwargs: Any) -> None:
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {}).update(kwargs)


def _get_job(job_id: str) -> Optional[dict[str, Any]]:
    with JOBS_LOCK:
        return JOBS.get(job_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index() -> str:
    """Стартовая страница с формой ввода квартиры."""
    return render_template(
        "index.html",
        districts=config.DISTRICTS,
        micro_districts=config.MICRO_DISTRICTS,
        defaults={
            "distance_km": config.DEFAULT_DISTANCE_KM,
            "depth": config.DEFAULT_RESULTS,
            "area_tolerance_pct": int(config.DEFAULT_AREA_TOLERANCE * 100),
        },
    )


@app.route("/search", methods=["POST"])
def search() -> Any:
    """Принять форму, запустить фоновую задачу, отдать redirect на /progress."""
    form = request.form

    try:
        params_dict = _form_to_dict(form)
    except ValueError as exc:
        return render_template(
            "index.html",
            districts=config.DISTRICTS,
            micro_districts=config.MICRO_DISTRICTS,
            error=str(exc),
            defaults={
                "distance_km": config.DEFAULT_DISTANCE_KM,
                "depth": config.DEFAULT_RESULTS,
                "area_tolerance_pct": int(config.DEFAULT_AREA_TOLERANCE * 100),
            },
        ), 400

    job_id = uuid.uuid4().hex[:12]
    _set_job(
        job_id,
        status="queued",
        progress=0,
        message="Постановка в очередь…",
        target=params_dict,
        listings=None,
        error=None,
        created_at=datetime.utcnow().isoformat(),
    )

    thread = threading.Thread(
        target=_run_job, args=(job_id, params_dict), daemon=True
    )
    thread.start()

    return redirect(url_for("progress_page", job_id=job_id))


@app.route("/progress/<job_id>")
def progress_page(job_id: str) -> Any:
    job = _get_job(job_id)
    if job is None:
        abort(404)
    return render_template("progress.html", job_id=job_id, job=job)


@app.route("/api/job/<job_id>")
def job_status(job_id: str) -> Any:
    job = _get_job(job_id)
    if job is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(
        {
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "error": job.get("error"),
            "result_url": url_for("results", job_id=job_id) if job["status"] == "done" else None,
        }
    )


@app.route("/results/<job_id>")
def results(job_id: str) -> Any:
    job = _get_job(job_id)
    if job is None:
        abort(404)
    if job["status"] != "done":
        return redirect(url_for("progress_page", job_id=job_id))

    analysis = job["analysis"]
    return render_template(
        "results.html",
        job_id=job_id,
        target=analysis["target"],
        listings=analysis["listings_sorted"],
        stats=analysis["stats"],
        warnings=analysis["warnings"],
        histogram=analysis["histogram"],
        share_url=None,
    )


@app.route("/export/<job_id>.csv")
def export_csv(job_id: str) -> Any:
    job = _get_job(job_id)
    if job is None or job.get("status") != "done":
        abort(404)
    csv_data = listings_to_csv(job["analysis"]["listings_sorted"])
    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="analogs_{job_id}.csv"',
        },
    )


@app.route("/history")
def history() -> str:
    session = get_session()
    try:
        rows = (
            session.query(SearchHistory)
            .order_by(SearchHistory.created_at.desc())
            .limit(10)
            .all()
        )
    finally:
        session.close()
    return render_template("history.html", rows=rows)


@app.route("/share/<job_id>", methods=["POST"])
def share(job_id: str) -> Any:
    """Сгенерировать постоянную ссылку на результат (24 часа)."""
    job = _get_job(job_id)
    if job is None or job.get("status") != "done":
        abort(404)
    payload = {
        "target": job["analysis"]["target"],
        "listings": job["analysis"]["listings_sorted"],
        "stats": job["analysis"]["stats"],
        "warnings": job["analysis"]["warnings"],
        "histogram": job["analysis"]["histogram"],
    }
    session = get_session()
    try:
        sr = SharedResult.create(payload)
        session.add(sr)
        session.commit()
        token = sr.token
    finally:
        session.close()
    return jsonify({"share_url": url_for("shared", token=token, _external=True)})


@app.route("/shared/<token>")
def shared(token: str) -> Any:
    session = get_session()
    try:
        sr = (
            session.query(SharedResult)
            .filter(SharedResult.token == token)
            .one_or_none()
        )
        if sr is None:
            abort(404)
        if sr.is_expired:
            return render_template("expired.html"), 410
        payload = json.loads(sr.payload_json)
    finally:
        session.close()

    return render_template(
        "results.html",
        job_id=None,
        target=payload["target"],
        listings=payload["listings"],
        stats=payload["stats"],
        warnings=payload["warnings"],
        histogram=payload["histogram"],
        share_url=request.url,
    )


# ---------------------------------------------------------------------------
# SocketIO
# ---------------------------------------------------------------------------
@socketio.on("subscribe")
def _on_subscribe(data: dict[str, Any]) -> None:
    """Клиент подписывается на канал свого job_id для прогресс-апдейтов."""
    job_id = (data or {}).get("job_id")
    if job_id:
        join_room(job_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _form_to_dict(form: Any) -> dict[str, Any]:
    """Валидация и нормализация данных формы."""
    rooms = (form.get("rooms") or "").strip().lower()
    if rooms not in {"studio", "1", "2", "3", "4+"}:
        raise ValueError("Не выбрано количество комнат.")
    address = (form.get("address") or "").strip()
    if not address:
        raise ValueError("Поле «Адрес» обязательно.")

    def to_float(name: str) -> Optional[float]:
        v = (form.get(name) or "").strip().replace(",", ".")
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            raise ValueError(f"Поле «{name}» должно быть числом.")

    def to_int(name: str) -> Optional[int]:
        v = (form.get(name) or "").strip()
        if not v:
            return None
        try:
            return int(v)
        except ValueError:
            raise ValueError(f"Поле «{name}» должно быть целым числом.")

    distance_km = to_float("distance_km") or config.DEFAULT_DISTANCE_KM
    depth = to_int("depth") or config.DEFAULT_RESULTS
    depth = max(5, min(depth, config.MAX_RESULTS_HARD_CAP))
    area_tolerance_pct = to_int("area_tolerance_pct") or int(
        config.DEFAULT_AREA_TOLERANCE * 100
    )

    return {
        "address": address,
        "district": (form.get("district") or "").strip() or None,
        "rooms": rooms,
        "total_area": to_float("total_area"),
        "kitchen_area": to_float("kitchen_area"),
        "floor": to_int("floor"),
        "floors_total": to_int("floors_total"),
        "build_year": to_int("build_year"),
        "price": to_float("price"),
        "distance_km": distance_km,
        "depth": depth,
        "area_tolerance": area_tolerance_pct / 100.0,
    }


def _run_job(job_id: str, target: dict[str, Any]) -> None:
    """Запускается в отдельном потоке. Поднимает asyncio-loop и парсер."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_job_async(job_id, target))
    except Exception as exc:  # noqa: BLE001
        log.exception("Job %s crashed: %s", job_id, exc)
        _set_job(
            job_id,
            status="error",
            progress=100,
            message="Не удалось получить данные, попробуйте позже.",
            error=str(exc),
        )
        socketio.emit(
            "progress",
            {
                "status": "error",
                "progress": 100,
                "message": str(exc),
            },
            to=job_id,
        )
    finally:
        loop.close()


async def _run_job_async(job_id: str, target: dict[str, Any]) -> None:
    """Реальная асинхронная работа: парсинг + аналитика + сохранение в БД."""

    def emit_progress(stage: str, percent: int, message: str) -> None:
        _set_job(job_id, status="running", progress=percent, message=message)
        socketio.emit(
            "progress",
            {"status": "running", "stage": stage, "progress": percent, "message": message},
            to=job_id,
        )

    emit_progress("init", 1, "Инициализация парсера…")

    params = SearchParams(
        rooms=target["rooms"],
        address=target["address"],
        district=target.get("district"),
        total_area=target.get("total_area"),
        area_tolerance=target["area_tolerance"],
        distance_km=target["distance_km"],
        depth=target["depth"],
    )

    async with AvitoParser() as parser:
        listings_objs = await parser.search(params, on_progress=emit_progress)

    listings_dicts = [l.to_dict() for l in listings_objs]
    analysis = analyze(target, listings_dicts)

    # Сохраняем в БД
    session = get_session()
    try:
        row = SearchHistory(
            address=target["address"],
            district=target.get("district"),
            rooms=target["rooms"],
            total_area=target.get("total_area"),
            kitchen_area=target.get("kitchen_area"),
            floor=target.get("floor"),
            floors_total=target.get("floors_total"),
            build_year=target.get("build_year"),
            price=target.get("price"),
            distance_km=target["distance_km"],
            area_tolerance=target["area_tolerance"],
            depth=target["depth"],
            result_json=json.dumps(
                {
                    "stats": analysis["stats"],
                    "warnings": analysis["warnings"],
                    "count": len(listings_dicts),
                },
                ensure_ascii=False,
                default=str,
            ),
        )
        session.add(row)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось сохранить историю: %s", exc)
    finally:
        session.close()

    _set_job(
        job_id,
        status="done",
        progress=100,
        message=f"Готово: {len(listings_dicts)} аналогов",
        analysis=analysis,
    )
    socketio.emit(
        "progress",
        {
            "status": "done",
            "progress": 100,
            "message": f"Готово: {len(listings_dicts)} аналогов",
            "result_url": url_for("results", job_id=job_id),
        },
        to=job_id,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Запуск приложения на %s:%d", config.HOST, config.PORT)
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        allow_unsafe_werkzeug=True,
    )
