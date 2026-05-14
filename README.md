# Avito Comparator — Красноярск

Веб-приложение для **сравнения цен на квартиры** в Красноярске на основе живых
данных с [Avito](https://www.avito.ru). Пользователь вводит параметры квартиры,
которую планирует купить — приложение собирает аналоги в том же районе/радиусе,
геокодирует их, считает медиану и среднюю цену за м², строит гистограмму
распределения и подсказывает, не завышена ли цена.

> **Disclaimer.** Парсер использует Avito в образовательных целях. Перед
> использованием убедитесь, что это не противоречит пользовательскому
> соглашению Avito и применимому законодательству.

---

## Содержание

- [Возможности](#возможности)
- [Архитектура](#архитектура)
- [Структура проекта](#структура-проекта)
- [Переменные окружения](#переменные-окружения)
- [Способ 1 · Локальный запуск (docker compose)](#способ-1--локальный-запуск-docker-compose)
- [Способ 2 · Деплой на VPS](#способ-2--деплой-на-vps-digitalocean--aws-ec2--яндексоблако-и-т-д)
- [Способ 3 · Бесплатный деплой (Render / Fly.io)](#способ-3--бесплатный-деплой)
- [Запуск без Docker (для разработки)](#запуск-без-docker-для-разработки)
- [Тестирование](#тестирование)
- [Безопасность](#безопасность)
- [FAQ](#faq)

---

## Возможности

- 🔍 Парсинг Avito по реальному URL с жёсткой фильтрацией по числу комнат
  (студия / 1 / 2 / 3 / 4+).
- 📍 Геокодирование адресов через OSM Nominatim, фильтр по радиусу (по умолчанию
  2 км), кеш в БД.
- 📊 Сводная аналитика: средняя/медианная цена и цена/м², распределение
  (гистограмма Chart.js), отклонение от медианы, влияние года постройки.
- ⚡ WebSocket-прогресс-бар на Flask-SocketIO — пользователь видит, на каком
  этапе парсинг.
- 🗄 История последних 10 запросов.
- 🔗 Поделиться результатом по ссылке (живёт 24 часа).
- 📱 PWA: можно установить как нативное приложение на смартфон.
- 🔐 Опциональный HTTP Basic Auth, CSRF, заголовки безопасности, rate-limit.
- 📤 Экспорт таблицы в CSV (Excel-совместимый).
- 🌗 Светлая / тёмная тема (auto + переключатель).

---

## Архитектура

```
                         ┌──────────────────────────────────────┐
                         │            Браузер пользователя       │
                         │  (HTML + Bootstrap + Chart.js + SW)   │
                         └──────────────┬────────────────────────┘
                                        │ HTTPS  (Socket.IO + REST)
                                        ▼
                       ┌────────────────────────────────────┐
                       │ Nginx (ssl, gzip, rate-limit, ws)  │
                       └─────────────┬──────────────────────┘
                                     │ proxy_pass
                                     ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ Flask + Flask-SocketIO   (Gunicorn / eventlet, 1 worker)    │
   │   ├─ routes: / /search /result /history /export ...         │
   │   ├─ SocketIO: rooms по session-id, события progress/done   │
   │   ├─ background thread → AvitoParser (Playwright Chromium)  │
   │   ├─ Geocoder (Nominatim) + кеш (SQLAlchemy)                │
   │   └─ Аналитика → CachedResult + QueryHistory (SQLite/PG)    │
   └────────────┬─────────────────────────────────────────────┬──┘
                │                                             │
        Volume: /app/data                              External:
        (SQLite + кэш геокодинга)                  Nominatim, Avito
```

---

## Структура проекта

```
.
├── app/
│   ├── main.py              ← Flask + SocketIO + роуты
│   ├── avito_parser.py      ← Playwright + BeautifulSoup
│   ├── geocoder.py          ← Nominatim + кеш
│   ├── analytics.py         ← метрики и предупреждения
│   ├── models.py            ← SQLAlchemy модели
│   ├── config.py            ← переменные окружения
│   ├── templates/           ← Jinja-шаблоны (index, results, history, base)
│   └── static/              ← style.css, app.js, manifest.json, sw.js
├── nginx/
│   ├── nginx.conf
│   └── proxy.inc
├── docker/
│   └── Dockerfile           ← multi-stage Python + Playwright
├── scripts/
│   └── deploy.sh            ← интерактивный деплой
├── tests/                   ← pytest (parser, geocoder, analytics, smoke)
├── docker-compose.yml
├── render.yaml              ← Render.com Blueprint
├── fly.toml                 ← Fly.io
├── requirements.txt
├── .env.example
└── README.md
```

---

## Переменные окружения

Все настройки — в `.env` (см. [.env.example](./.env.example)). Ключевые:

| Переменная             | По умолчанию              | Назначение                          |
|------------------------|---------------------------|-------------------------------------|
| `APP_SECRET_KEY`       | `dev-secret-change-me`    | Подпись cookies / CSRF              |
| `APP_PASSWORD`         | _(пусто = открытый сайт)_ | Включает HTTP Basic Auth            |
| `APP_BASIC_AUTH_USER`  | `admin`                   | Логин для Basic Auth                |
| `APP_DATABASE_URL`     | `sqlite:///data/app.db`   | SQLite или PostgreSQL DSN           |
| `APP_HEADLESS`         | `true`                    | Headless-режим Playwright           |
| `APP_DELAY_MIN/MAX`    | `2.0` / `5.0`             | Задержки между действиями (сек.)    |
| `APP_PAGE_DELAY_MIN/MAX` | `10.0` / `20.0`         | Задержки между страницами выдачи    |
| `APP_MAX_PAGES`        | `5`                       | Лимит страниц поиска                |
| `APP_MAX_LISTINGS`     | `20`                      | Лимит итоговых аналогов             |
| `APP_COOKIES_FILE`     | _(пусто)_                 | Путь к JSON с куками (опц.)         |
| `APP_NOMINATIM_USER_AGENT` | `avito-comparator/...` | UA для Nominatim                  |
| `APP_SHARE_TTL_HOURS`  | `24`                      | Срок жизни share-ссылок             |
| `DOMAIN_NAME`          | _(пусто)_                 | Свой домен (для nginx + cookies)    |
| `LETSENCRYPT_EMAIL`    | _(пусто)_                 | E-mail для Let's Encrypt            |

---

## Способ 1 · Локальный запуск (`docker compose`)

**Что нужно:** установленный [Docker](https://docs.docker.com/get-docker/)
с Compose v2.

```bash
git clone https://github.com/<your-fork>/Indicidualproject.git
cd Indicidualproject

cp .env.example .env
# (откройте .env и при желании задайте APP_PASSWORD)

docker compose up --build
```

Через 2–3 минуты (на первом запуске тянется образ Playwright) откройте
`http://localhost/`. Страница со стартовой формой готова к использованию.

Полезное:

```bash
docker compose logs -f app    # хвост логов приложения
docker compose down           # остановить
docker compose down -v        # остановить и удалить БД-volume
```

> Если порт 80 занят (например, локальным веб-сервером), измените секцию
> `ports` в `docker-compose.yml`, например на `"8080:80"`, и откройте
> `http://localhost:8080/`.

---

## Способ 2 · Деплой на VPS (DigitalOcean / AWS EC2 / Яндекс.Облако и т. д.)

**Сценарий:** у вас есть Linux-сервер (Ubuntu 22.04+) с публичным IP и
(опционально) свой домен.

### 2.1. Подготовка сервера

```bash
ssh root@YOUR_IP

# Установка Docker (упрощённо; для production используйте официальный гайд):
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# Открыть порты на firewall:
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### 2.2. Деплой кода

```bash
git clone https://github.com/<your-fork>/Indicidualproject.git
cd Indicidualproject

cp .env.example .env
nano .env
# Минимально задайте:
#   APP_SECRET_KEY=...сгенерируйте 64+ символов...
#   APP_PASSWORD=...свой пароль...
#   DOMAIN_NAME=example.com
#   LETSENCRYPT_EMAIL=you@example.com

./scripts/deploy.sh vps
# (или вручную: docker compose up -d --build)
```

После запуска:

```bash
curl http://localhost/healthz
# {"status":"ok",...}
```

Откройте `http://YOUR_IP/` или `http://example.com/` — приложение работает по HTTP.

### 2.3. SSL через Let's Encrypt

1. Убедитесь, что DNS A-запись `example.com` указывает на IP сервера:
   ```bash
   dig +short example.com
   ```
2. Получите сертификат:
   ```bash
   docker compose run --rm certbot certonly \
     --webroot -w /var/www/certbot \
     -d example.com \
     --email you@example.com \
     --agree-tos --no-eff-email
   ```
3. Откройте `nginx/nginx.conf`, раскомментируйте блок `server { listen 443 ssl; ... }`
   и (опционально) замените содержимое блока `server { listen 80; }` на
   ```nginx
   return 301 https://$host$request_uri;
   ```
4. Перезапустите nginx:
   ```bash
   docker compose restart nginx
   ```

### 2.4. Авто-обновление сертификата

Добавьте cron-задачу:
```bash
crontab -e
```
```cron
0 3 * * * cd /root/Indicidualproject && docker compose run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload
```

---

## Способ 3 · Бесплатный деплой

### Render.com

1. Сделайте fork репозитория на GitHub.
2. Зарегистрируйтесь на <https://render.com> (можно через GitHub).
3. На дашборде нажмите **New +** → **Blueprint** и выберите свой форк.
4. Render найдёт `render.yaml` и автоматически создаст сервис.
5. Откройте свежесозданный сервис → **Environment** → задайте:
   - `APP_PASSWORD` — пароль для Basic Auth (если не задать, сайт открыт всем).
   - `DOMAIN_NAME` — если планируете подключить свой домен.
6. Render выпустит и обновит SSL-сертификат автоматически.

После деплоя сайт будет на `https://avito-comparator.onrender.com` (имя зависит
от названия сервиса).

> **На бесплатном тарифе Render** сервис «засыпает» после 15 минут простоя —
> первый запрос после простоя может занять до 30 секунд.

### Fly.io

```bash
# 1. Установите flyctl: https://fly.io/docs/hands-on/install-flyctl/
flyctl auth signup    # или login

# 2. Запустите интерактивный сценарий:
./scripts/deploy.sh fly

# Эквивалент вручную:
flyctl launch --no-deploy --copy-config --dockerfile docker/Dockerfile
flyctl volumes create avito_data --size 1 --region fra
flyctl secrets set APP_SECRET_KEY="$(openssl rand -hex 32)" \
                  APP_PASSWORD="свой_пароль"
flyctl deploy
```

Сайт будет доступен на `https://<app-name>.fly.dev`. Чтобы привязать свой
домен:

```bash
flyctl certs add example.com
# Затем добавьте AAAA / A запись в DNS, как покажет fly.
```

---

## Запуск без Docker (для разработки)

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# ВАЖНО: установить Chromium для Playwright
playwright install chromium

cp .env.example .env
mkdir -p data

# Dev-сервер с горячей перезагрузкой:
APP_DEBUG=true python -m app.main
```

Откройте <http://localhost:8000/>.

---

## Тестирование

```bash
pip install -r requirements.txt
pytest -q
```

Тесты не требуют Avito/сети: парсер тестируется на встроенных HTML-фикстурах,
геокодер — на замоканном Nominatim, Flask — на тестовом клиенте.

---

## Безопасность

Включено по умолчанию:

- **CSRF-токен** во всех формах (`Flask-WTF`).
- **Заголовки безопасности**: CSP, X-Frame-Options, X-Content-Type-Options,
  Referrer-Policy, Permissions-Policy, HSTS (при HTTPS).
- **Rate-limit** на `/search` (5 запросов/мин на IP).
- **HTTP Basic Auth** при заданном `APP_PASSWORD`.
- **HttpOnly + SameSite=Lax** cookies. `Secure` включается, когда задан
  `DOMAIN_NAME` (т. е. ожидается HTTPS).
- В nginx — отдельный rate-limit на `/search`, лимит размера запроса 4 МБ.

Дополнительно рекомендуется:

- Регулярно обновлять зависимости: `pip-audit` или `safety check`.
- Использовать PostgreSQL вместо SQLite, если ожидаются конкурентные пользователи.
- Перенести `APP_SECRET_KEY` и `APP_PASSWORD` в секреты платформы (Render/Fly
  делают это автоматически).

---

## FAQ

**Парсер ничего не находит / возвращает 0 аналогов.**
Скорее всего Avito показал капчу. Решения по убыванию эффективности:

1. Экспортируйте куки залогиненной сессии из браузера в JSON и укажите
   `APP_COOKIES_FILE=/path/to/cookies.json`.
2. Увеличьте задержки `APP_DELAY_MIN/MAX` и `APP_PAGE_DELAY_MIN/MAX`.
3. Запускайте через резидентский прокси (поддержка прокси легко добавляется
   в `AvitoParser` — параметр `proxy` у `chromium.launch`).

**Можно ли использовать другой город?**
Да. Задайте `APP_CITY=novosibirsk` и `APP_CITY_DISPLAY=Новосибирск`. Фильтры
районов в `app/config.py` написаны для Красноярска — для другого города их
нужно подправить.

**Как импортировать существующее объявление автоматически?**
Кнопка «Заполнить автоматически» зарезервирована в форме, но для её работы
нужен парсер одного URL — он есть в `AvitoParser._enrich_listing`. Достаточно
добавить роут `POST /autofill` (вне рамок ТЗ), который вернёт JSON с полями,
а JS просто заполнит форму.

**Где смотреть прогресс?**
Вживую — на странице с формой (прогресс-бар появляется после нажатия
«Найти аналоги»). В логах: `docker compose logs -f app`.

---

## Лицензия

Проект — образовательный. Используйте свободно с указанием авторства.
Соблюдайте пользовательское соглашение Avito и применимое законодательство.
