# Квартира-Компаратор

Веб-приложение для сравнения стоимости квартир в Красноярске на основе реальных данных с Avito. Доступно с любого устройства через браузер.

## Возможности

- Парсинг объявлений Avito в реальном времени (Playwright + BeautifulSoup)
- Гео-валидация аналогов (Nominatim/OpenStreetMap)
- Сравнительная аналитика: цена/м², медиана, отклонения, гистограмма
- Адаптивный интерфейс (Bootstrap 5, mobile-first, тёмная/светлая тема)
- PWA — устанавливается на смартфон как приложение
- Экспорт результатов в CSV
- История запросов и публичные ссылки на результаты
- WebSocket прогресс-бар парсинга
- Защита паролем (HTTP Basic Auth)
- Docker-контейнеризация с Nginx и SSL

## Структура проекта

```
├── app/
│   ├── main.py              # Flask-приложение, маршруты, аналитика
│   ├── avito_parser.py      # Парсер Avito (Playwright)
│   ├── geocoder.py          # Геокодирование (Nominatim)
│   ├── models.py            # SQLAlchemy модели (БД)
│   ├── config.py            # Конфигурация из переменных окружения
│   ├── templates/
│   │   ├── index.html       # Форма ввода параметров
│   │   └── results.html     # Страница результатов
│   └── static/
│       ├── style.css        # Стили (адаптивные)
│       ├── app.js           # Клиентская логика
│       ├── manifest.json    # PWA-манифест
│       └── sw.js            # Service Worker
├── nginx/
│   └── nginx.conf           # Конфигурация Nginx
├── docker/
│   └── Dockerfile           # Образ приложения
├── tests/
│   ├── test_geocoder.py     # Тесты геокодера
│   ├── test_parser.py       # Тесты парсера
│   └── test_app.py          # Smoke-тесты веб-интерфейса
├── docker-compose.yml       # Запуск всех сервисов
├── render.yaml              # Конфиг Render.com
├── fly.toml                 # Конфиг Fly.io
├── deploy.sh                # Интерактивный скрипт деплоя
├── requirements.txt         # Python-зависимости
├── .env.example             # Шаблон переменных окружения
└── README.md                # Этот файл
```

## Быстрый старт

### Предварительные требования

- Docker и Docker Compose (для контейнерного запуска)
- ИЛИ Python 3.11+ (для локального запуска без Docker)

---

## Вариант 1: Локальный запуск (Docker)

Самый простой способ — всё работает из коробки одной командой.

```bash
# 1. Клонируем репозиторий
git clone https://github.com/your-repo/kvartira-comparator.git
cd kvartira-comparator

# 2. Копируем конфигурацию
cp .env.example .env

# 3. (Опционально) Редактируем .env — задаём пароль
#    APP_PASSWORD=your-password

# 4. Запускаем
docker-compose up -d --build

# 5. Открываем в браузере
# http://localhost
```

**Остановка:**
```bash
docker-compose down
```

**Логи:**
```bash
docker-compose logs -f app
```

---

## Вариант 2: Локальный запуск (без Docker)

Для разработки и отладки.

```bash
# 1. Клонируем и входим в директорию
git clone https://github.com/your-repo/kvartira-comparator.git
cd kvartira-comparator

# 2. Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Устанавливаем зависимости
pip install -r requirements.txt

# 4. Устанавливаем браузер для Playwright
playwright install chromium

# 5. Копируем конфигурацию
cp .env.example .env

# 6. Создаём директорию для БД
mkdir -p data

# 7. Запускаем
python -m app.main
```

Приложение будет доступно по адресу: `http://localhost:5000`

---

## Вариант 3: Деплой на VPS/Сервер

Для развёртывания на выделенном сервере (DigitalOcean, AWS EC2, Яндекс.Облако и т.д.).

### Пошаговая инструкция

```bash
# 1. Подключаемся к серверу
ssh root@your-server-ip

# 2. Устанавливаем Docker (если ещё нет)
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin

# 3. Клонируем репозиторий
git clone https://github.com/your-repo/kvartira-comparator.git
cd kvartira-comparator

# 4. Запускаем интерактивный скрипт деплоя
chmod +x deploy.sh
./deploy.sh
# Выбираем вариант 2 (VPS)
```

### Настройка SSL (HTTPS)

```bash
# После запуска приложения (домен уже должен указывать на сервер):

# 1. Убедитесь что DNS-запись A указывает на IP сервера
# 2. В .env задайте DOMAIN_NAME=your-domain.com
# 3. Раскомментируйте redirect в nginx.conf
# 4. Получите сертификат:
docker compose --profile ssl run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    --email your@email.com \
    -d your-domain.com \
    --agree-tos --no-eff-email

# 5. Раскомментируйте HTTPS-блок в nginx/nginx.conf
# 6. Перезапустите:
docker compose restart nginx
```

### Схема архитектуры

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Клиент    │────▶│    Nginx    │────▶│  Flask App  │
│  (браузер)  │◀────│  (порт 80)  │◀────│ (порт 5000) │
└─────────────┘     └─────────────┘     └─────────────┘
                          │                     │
                          │ WebSocket           │ Playwright
                          │ проксирование       │ (Chromium)
                          │                     ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   Certbot   │     │   Avito.ru  │
                    │ (SSL certs) │     │  (парсинг)  │
                    └─────────────┘     └─────────────┘
```

---

## Вариант 4: Деплой на Render.com (бесплатно)

Render.com предоставляет бесплатный хостинг с автоматическим деплоем.

### Шаги

1. **Зарегистрируйтесь** на [render.com](https://render.com) через GitHub
2. **Создайте Blueprint**:
   - Dashboard → New + → Blueprint
   - Подключите репозиторий с проектом
   - Render обнаружит `render.yaml` автоматически
3. **Задайте переменные**:
   - `APP_PASSWORD` — пароль для доступа (рекомендуется)
4. **Нажмите Apply** — деплой начнётся автоматически
5. **Готово!** Приложение доступно по URL вида `https://kvartira-comparator.onrender.com`

### Особенности Render

- Бесплатный тир отключает приложение при неактивности (холодный старт ~30 сек)
- HTTPS включён автоматически
- Авто-деплой при пуше в main-ветку
- Диск 1 GB для SQLite базы данных

---

## Вариант 5: Деплой на Fly.io (бесплатно)

Fly.io — быстрая платформа с edge-серверами по всему миру.

### Шаги

```bash
# 1. Установите Fly CLI
curl -L https://fly.io/install.sh | sh

# 2. Авторизуйтесь
fly auth signup  # или fly auth login

# 3. Запустите скрипт деплоя
./deploy.sh
# Выбираем вариант 4 (Fly.io)

# --- ИЛИ вручную: ---

# 3. Создайте приложение
fly apps create kvartira-comparator

# 4. Создайте volume для БД
fly volumes create kvartira_data --size 1 --region ams

# 5. Задайте secrets
fly secrets set APP_SECRET_KEY=$(openssl rand -hex 32)
fly secrets set APP_PASSWORD=your-password

# 6. Деплой
fly deploy
```

**Результат:** `https://kvartira-comparator.fly.dev`

### Полезные команды Fly.io

```bash
fly logs              # Логи
fly status            # Статус приложения
fly ssh console       # SSH в контейнер
fly scale count 1     # Масштабирование
fly open              # Открыть в браузере
```

---

## Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `APP_SECRET_KEY` | Секретный ключ Flask | `change-me` |
| `APP_PASSWORD` | Пароль доступа (пустой = открыт всем) | — |
| `DOMAIN_NAME` | Доменное имя для SSL | — |
| `APP_DATABASE_URL` | URL базы данных | `sqlite:///data/app.db` |
| `APP_DEBUG` | Режим отладки | `false` |
| `APP_LOG_LEVEL` | Уровень логирования | `INFO` |
| `APP_PARSER_MAX_PAGES` | Макс. страниц Avito | `5` |
| `APP_PARSER_MAX_ANALOGS` | Макс. аналогов | `20` |
| `APP_DEFAULT_MAX_DISTANCE_KM` | Радиус поиска (км) | `2.0` |

Полный список — в файле `.env.example`.

---

## Тестирование

```bash
# Запуск тестов
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## Технологии

| Компонент | Технология |
|---|---|
| Backend | Python 3.11, Flask, Flask-SocketIO |
| Frontend | HTML5, Bootstrap 5, Vanilla JS, Chart.js |
| Парсинг | Playwright (Chromium), BeautifulSoup |
| Геокодирование | geopy + Nominatim (OSM) |
| База данных | SQLAlchemy + SQLite / PostgreSQL |
| Веб-сервер | Gunicorn + Nginx |
| Контейнеризация | Docker, Docker Compose |
| SSL | Let's Encrypt (Certbot) |
| PWA | Service Worker + manifest.json |

---

## Ограничения и дисклеймер

- Приложение предназначено **исключительно для образовательных целей**
- Парсинг Avito должен соответствовать их пользовательскому соглашению
- При интенсивном использовании Avito может заблокировать запросы (капча, HTTP 429)
- Данные геокодирования основаны на OpenStreetMap и могут быть неточными
- Аналитика носит справочный характер и не является профессиональной оценкой

---

## Лицензия

MIT License. Используйте на свой страх и риск.
