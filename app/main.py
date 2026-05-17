"""Flask-приложение Квартира-Компаратор."""
import json
import logging
import statistics
from functools import wraps
from threading import Thread
from flask import Flask, render_template, request, jsonify, Response, make_response
from app.config import config
from app.models import init_db, save_search, update_search_results, update_search_error, get_search, get_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = config.SECRET_KEY

init_db()


# === Auth ===
def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not config.PASSWORD:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or auth.password != config.PASSWORD:
            return Response("Требуется пароль", 401, {"WWW-Authenticate": 'Basic realm="App"'})
        return f(*args, **kwargs)
    return decorated


# === Маршруты ===
@app.route("/")
@requires_auth
def index():
    districts = list(config.DISTRICTS.keys())
    microdistricts = list(config.MICRODISTRICTS.keys())
    return render_template("index.html", districts=districts, microdistricts=microdistricts)


@app.route("/search", methods=["POST"])
@requires_auth
def search():
    data = request.get_json() if request.is_json else request.form.to_dict()
    address = data.get("address", "").strip()
    rooms = data.get("rooms", "").strip()
    price = data.get("price", "")

    if not address or not rooms or not price:
        return jsonify({"error": "Заполните обязательные поля"}), 400
    try:
        price = int(str(price).replace(" ", "").replace(",", ""))
    except ValueError:
        return jsonify({"error": "Некорректная цена"}), 400

    search_data = {
        "address": address, "district": data.get("district"), "rooms": rooms,
        "price": price, "total_area": _float(data.get("total_area")),
        "floor": _int(data.get("floor")), "year_built": _int(data.get("year_built")),
    }

    mode = data.get("mode", "manual")  # "manual" или "auto"

    # Собираем аналоги из формы (ручной режим)
    manual_analogs = []
    if mode == "manual":
        if request.is_json:
            manual_analogs = data.get("analogs", [])
        else:
            analog_prices = request.form.getlist("analog_price[]")
            analog_areas = request.form.getlist("analog_area[]")
            for p, a in zip(analog_prices, analog_areas):
                p_clean = p.replace(" ", "").replace(",", "")
                if p_clean:
                    analog = {"price": int(p_clean)}
                    if a:
                        analog["total_area"] = float(a)
                    manual_analogs.append(analog)

    search_id = save_search(search_data)

    if mode == "auto":
        # Парсинг в фоне
        Thread(target=_auto_search, args=(search_id, search_data), daemon=True).start()
        return jsonify({"id": search_id, "status": "processing"})
    else:
        # Ручной режим — сразу считаем аналитику
        analytics = compute_analytics(manual_analogs, price, _float(data.get("total_area")))
        update_search_results(search_id, manual_analogs, analytics)
        return jsonify({"id": search_id, "status": "completed"})


@app.route("/results/<search_id>")
@requires_auth
def results(search_id):
    data = get_search(search_id)
    if not data:
        return "Не найдено", 404
    return render_template("results.html", search=data, results=data["results"], analytics=data["analytics"])


@app.route("/status/<search_id>")
@requires_auth
def status(search_id):
    data = get_search(search_id)
    if not data:
        return jsonify({"error": "Не найден"}), 404
    # Фронтенд ожидает "done" или "error"
    s = data["status"]
    if s == "completed":
        s = "done"
    return jsonify({"status": s})


@app.route("/history")
@requires_auth
def history():
    return jsonify(get_history())


@app.route("/export/<search_id>")
@requires_auth
def export_csv(search_id):
    data = get_search(search_id)
    if not data:
        return "Не найдено", 404
    import csv, io
    output = io.StringIO()
    w = csv.writer(output, delimiter=";")
    w.writerow(["Комнаты", "Адрес", "Цена", "Площадь", "Цена/м²", "Этаж", "Год", "Ссылка"])
    for item in data["results"]:
        ppm = round(item["price"] / item["total_area"]) if item.get("price") and item.get("total_area") else ""
        w.writerow([item.get("rooms",""), item.get("address",""), item.get("price",""),
                    item.get("total_area",""), ppm, item.get("floor",""), item.get("year_built",""), item.get("url","")])
    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = f"attachment; filename=analogs_{search_id}.csv"
    return resp


# === Фоновый парсинг ===
def _auto_search(search_id: str, search_data: dict):
    try:
        from app.avito_parser import run_parser
        price = search_data["price"]
        results = run_parser(
            rooms=search_data["rooms"],
            district=search_data.get("district"),
            min_price=int(price * 0.5),
            max_price=int(price * 1.8),
        )
        analytics = compute_analytics(results, price, search_data.get("total_area"))
        update_search_results(search_id, results, analytics)
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        update_search_error(search_id, str(e))


# === Аналитика ===
def compute_analytics(results: list, user_price: int, user_area=None) -> dict:
    analytics = {"total": len(results), "warnings": []}
    prices_m2 = []
    prices = []

    for item in results:
        p = item.get("price")
        a = item.get("total_area")
        if p and a and a > 0:
            prices_m2.append(p / a)
            prices.append(p)

    if prices_m2:
        avg = statistics.mean(prices_m2)
        analytics["avg_price_m2"] = round(avg)
        analytics["median_price_m2"] = round(statistics.median(prices_m2))
        analytics["min_price_m2"] = round(min(prices_m2))
        analytics["max_price_m2"] = round(max(prices_m2))
        analytics["histogram"] = [round(p) for p in sorted(prices_m2)]

        if user_area and user_area > 0:
            user_m2 = user_price / user_area
            analytics["user_price_m2"] = round(user_m2)
            dev = ((user_m2 - avg) / avg) * 100
            analytics["deviation"] = round(dev, 1)
            if dev > 15:
                analytics["warnings"].append(f"Цена может быть завышена на {abs(round(dev))}%")
            elif dev < -15:
                analytics["warnings"].append(f"Цена ниже рынка на {abs(round(dev))}%")

    if prices:
        analytics["median_price"] = round(statistics.median(prices))
        analytics["avg_price"] = round(statistics.mean(prices))

    if len(results) < 5:
        analytics["warnings"].insert(0, f"Мало аналогов ({len(results)}). Результаты могут быть неточными.")

    return analytics


def _float(v):
    try: return float(str(v).replace(",", ".").replace(" ", "")) if v else None
    except: return None

def _int(v):
    try: return int(str(v).replace(" ", "")) if v else None
    except: return None


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
