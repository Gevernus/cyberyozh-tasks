# Task Management API

REST API системы управления задачами на Django + Django REST Framework.

Пользователи создают, редактируют и удаляют задачи, назначают их другим
пользователям, отмечают выполненными и обсуждают в комментариях.

## Что сделано

- CRUD задач; автор задачи — текущий пользователь.
- Назначение исполнителя: `POST /api/tasks/{id}/assign/` или `PATCH` поля `assignee_id`.
- Отметка о выполнении: `POST /api/tasks/{id}/complete/` и обратное действие `/reopen/`.
- Комментарии к задачам: список, создание, редактирование и удаление своих комментариев.
- Фильтры, поиск, сортировка и пагинация списка задач.
- Регистрация и JWT-аутентификация (`djangorestframework-simplejwt`).
- OpenAPI-схема, Swagger UI и Redoc (`drf-spectacular`).
- 84 теста на pytest, покрытие 97%, включая тест гонки `complete`/`reopen` на PostgreSQL.
- SQLite по умолчанию, PostgreSQL через `DATABASE_URL`.
- Продакшен-обвязка: многоэтапный Dockerfile (gunicorn, non-root), Docker Compose
  с PostgreSQL и Redis, логи в stdout, health-check, троттлинг, настройки безопасности, CI.
- Команда `seed_demo` для демо-данных.

## Стек

Python 3.12, Django 5.2 LTS, Django REST Framework, simplejwt, drf-spectacular,
django-filter, dj-database-url, gunicorn, WhiteNoise, PostgreSQL, Redis,
pytest + pytest-django + factory_boy, ruff.

## Структура

```
config/                 настройки (из переменных окружения), корневые URL, пагинация, health-check
apps/accounts/          модель пользователя, регистрация, JWT-вьюхи, /api/users/
apps/tasks/             модели Task и Comment, API, права, фильтры, seed_demo
tests/                  тесты API, прав, фильтров, моделей, троттлинга, конкурентности
gunicorn.conf.py        настройки gunicorn
docker/entrypoint.sh    миграции и запуск процесса в контейнере
Dockerfile, docker-compose.yml, .env.example
.github/workflows/ci.yml
```

## Быстрый старт (локально, SQLite)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python manage.py migrate
python manage.py createsuperuser     # по желанию, для /admin/
python manage.py seed_demo           # по желанию: демо-данные, логины и пароль в выводе
python manage.py runserver
```

`seed_demo` создаёт пользователей `alice`, `bob`, `carol` с задачами и комментариями.
Пароль генерируется заново при каждом запуске и печатается один раз; свой можно задать
через `DEMO_PASSWORD` (тогда он не печатается) или `--password`. Повторный запуск не
дублирует данные, но ставит демо-пользователям новый пароль. Команда — только для
локального или закрытого окружения: на публично доступном стенде демо-учётки с известным
паролем не нужны.

После запуска:

| Что | Адрес |
|---|---|
| Swagger UI | http://127.0.0.1:8000/api/docs/ |
| Redoc | http://127.0.0.1:8000/api/redoc/ |
| OpenAPI-схема | http://127.0.0.1:8000/api/schema/ |
| Админка (при `DEBUG`) | http://127.0.0.1:8000/admin/ |

Локально переменные окружения не нужны: по умолчанию включён `DEBUG`, используется
SQLite и кэш в памяти процесса. Админка по умолчанию подключена только при `DEBUG`,
см. «Безопасность».

## Запуск через Docker Compose

```bash
cp .env.example .env    # заменить все change-me: DJANGO_SECRET_KEY и POSTGRES_PASSWORD
docker compose up --build -d
docker compose exec web python manage.py seed_demo          # демо-данные, только на закрытом стенде
docker compose exec web python manage.py createsuperuser    # если нужна админка
```

API будет доступно на http://localhost:8000/api/docs/ (порт меняется через `HTTP_PORT`).
Поднимаются три сервиса: `web` (gunicorn), `db` (PostgreSQL 17) и `redis`. Наружу
опубликован только `web`; пароли в compose-файле не зашиты, без `POSTGRES_PASSWORD`
compose не стартует. Миграции применяются при старте контейнера, статика собирается
при сборке образа и отдаётся через WhiteNoise.

Образ собирается в два этапа: в `builder` зависимости собираются в wheels, в финальный
образ попадают только они и код, без компиляторов и dev-зависимостей. Процесс работает
от непривилегированного пользователя (uid 10001), код ему доступен только на чтение.
`ENTRYPOINT` применяет миграции (`DJANGO_MIGRATE=0` отключает — например, если реплик
несколько и миграции идут отдельным шагом релиза), затем запускает gunicorn через `exec`,
чтобы SIGTERM доходил до него и остановка была плавной.

### Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DJANGO_DEBUG` | `True` | режим отладки |
| `DJANGO_SECRET_KEY` | ключ для разработки | обязателен при `DJANGO_DEBUG=False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | список через запятую; `localhost` нужен healthcheck контейнера |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | пусто | например `https://tasks.example.com`, нужно для админки по HTTPS |
| `DJANGO_ADMIN_ENABLED` | как `DJANGO_DEBUG` | подключить админку; в продакшене по умолчанию выключена |
| `DJANGO_ADMIN_URL` | `admin/` | путь админки |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | например `postgres://user:pass@host:5432/db`; в compose собирается сам |
| `DJANGO_CONN_MAX_AGE` | `60` | время жизни постоянного соединения с БД, секунды |
| `REDIS_URL` | пусто (кэш в памяти) | например `redis://redis:6379/0`; в compose задан |
| `DJANGO_LOG_LEVEL` | `INFO` | уровень логов |
| `DJANGO_MIGRATE` | `1` | применять миграции при старте контейнера |
| `DJANGO_SECURE_HTTPS` | `0` | редирект на HTTPS, secure-cookies, HSTS |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | `0` | доверять `X-Forwarded-Proto` от прокси |
| `DJANGO_SECURE_HSTS_SECONDS` | `31536000` | срок HSTS при `DJANGO_SECURE_HTTPS=1` |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_SECURE_HSTS_PRELOAD` | `0` | расширения HSTS |
| `THROTTLE_ANON_RATE` / `THROTTLE_USER_RATE` | `100/hour` / `1000/hour` | общие лимиты запросов |
| `THROTTLE_AUTH_RATE` | `10/min` | лимит на регистрацию и выдачу токенов |
| `NUM_PROXIES` | `0` | число прокси перед приложением (для определения IP клиента) |
| `GUNICORN_WORKERS` | `min(2 * CPU + 1, 4)` | процессы gunicorn |
| `GUNICORN_THREADS` | `4` | потоки в процессе |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | чьим `X-Forwarded-*` доверяет gunicorn |
| `HTTP_PORT` | `8000` | порт на хосте (compose) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `tasks` / `tasks` / — | БД в compose, пароль обязателен |

## Работа с API

Все эндпоинты, кроме регистрации, получения токена, документации и health-check, требуют
заголовок `Authorization: Bearer <access>`. Access-токен живёт 30 минут,
refresh — 7 дней. В Swagger UI токен вводится через кнопку **Authorize**.

```bash
# Регистрация
curl -X POST http://127.0.0.1:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"username": "dave", "email": "dave@example.com", "password": "Sup3r-secret!"}'

# Получение пары токенов
curl -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "dave", "password": "Sup3r-secret!"}'
# -> {"refresh": "...", "access": "..."}

TOKEN=<access из ответа>

# Создать задачу и сразу назначить исполнителя (id из GET /api/users/)
curl -X POST http://127.0.0.1:8000/api/tasks/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "Подготовить отчёт", "priority": 3, "due_date": "2030-01-31", "assignee_id": 1}'

# Переназначить или снять исполнителя
curl -X POST http://127.0.0.1:8000/api/tasks/1/assign/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"assignee_id": null}'

# Отметить выполненной / вернуть в работу
curl -X POST http://127.0.0.1:8000/api/tasks/1/complete/ -H "Authorization: Bearer $TOKEN"
curl -X POST http://127.0.0.1:8000/api/tasks/1/reopen/ -H "Authorization: Bearer $TOKEN"

# Комментарий
curl -X POST http://127.0.0.1:8000/api/tasks/1/comments/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "Взял в работу"}'

# Мои открытые задачи с высоким приоритетом, сначала ближайшие по сроку
curl "http://127.0.0.1:8000/api/tasks/?assignee=1&status=todo&priority=3&ordering=due_date" \
  -H "Authorization: Bearer $TOKEN"

# Обновить access-токен
curl -X POST http://127.0.0.1:8000/api/auth/token/refresh/ \
  -H "Content-Type: application/json" -d '{"refresh": "<refresh>"}'
```

### Эндпоинты

| Метод и путь | Описание |
|---|---|
| `POST /api/auth/register/` | регистрация |
| `POST /api/auth/token/` | пара JWT-токенов по логину и паролю |
| `POST /api/auth/token/refresh/` | новый access-токен |
| `GET /api/users/`, `GET /api/users/{id}/` | активные пользователи (для выбора исполнителя), `?search=` |
| `GET /api/users/me/` | текущий пользователь |
| `GET, POST /api/tasks/` | список и создание задач |
| `GET, PUT, PATCH, DELETE /api/tasks/{id}/` | задача |
| `POST /api/tasks/{id}/assign/` | назначить исполнителя (`{"assignee_id": id или null}`) |
| `POST /api/tasks/{id}/complete/` | отметить выполненной |
| `POST /api/tasks/{id}/reopen/` | вернуть в работу |
| `GET, POST /api/tasks/{id}/comments/` | комментарии задачи |
| `GET, PUT, PATCH, DELETE /api/tasks/{id}/comments/{comment_id}/` | комментарий |
| `GET /api/health/` | состояние сервиса и зависимостей, без аутентификации |

### Модель задачи

| Поле | Описание |
|---|---|
| `title`, `description` | название (обязательно) и описание |
| `status` | `todo`, `in_progress`, `done` |
| `priority` | `1` низкий, `2` средний (по умолчанию), `3` высокий |
| `due_date` | срок, `YYYY-MM-DD` |
| `author` | создатель, выставляется автоматически |
| `assignee` / `assignee_id` | исполнитель: в ответе объект, при записи id или `null` |
| `completed_at` | время выполнения, выставляется и сбрасывается автоматически |
| `comments_count` | число комментариев |

### Фильтры, поиск, сортировка, пагинация

- `status`, `priority`, `author`, `assignee` — точное совпадение (`author` и `assignee` — id пользователя);
- `unassigned=true` — задачи без исполнителя;
- `due_after`, `due_before` — диапазон срока, включительно;
- `search` — по названию и описанию;
- `ordering` — `created_at`, `updated_at`, `due_date`, `priority`, `title`, с `-` по убыванию.
  По умолчанию сначала новые;
- `page`, `page_size` — по 20 на странице, максимум 100.

## Права доступа

| Действие | Кто может |
|---|---|
| Читать задачи, комментарии, список пользователей | любой аутентифицированный пользователь |
| Создать задачу, оставить комментарий | любой аутентифицированный пользователь |
| Редактировать, удалить, назначить задачу | только автор задачи |
| Отметить выполненной или вернуть в работу | автор или исполнитель |
| Редактировать или удалить комментарий | только автор комментария |

Почему так:

- **Все видят все задачи.** Система рассчитана на одну команду, общая доска — ожидаемое
  поведение. Если понадобится изоляция, её легко добавить в `TaskViewSet.get_queryset`.
- **Исполнитель не редактирует задачу**, но управляет её выполнением: условие ставит автор,
  а отчитывается о результате тот, кто делает.
- **Статус можно менять и через `PATCH`** (автор может перевести задачу в `in_progress`).
  `completed_at` выставляется и сбрасывается в `Task.save()`, поэтому остаётся согласованным
  со статусом при любом способе изменения, включая админку.
- Повторный `complete` уже выполненной задачи (и `reopen` открытой) возвращает `400`,
  чтобы клиент не перезаписал время выполнения по ошибке. Это соблюдается и при
  одновременных запросах, см. «Конкурентность».
- Исполнителем можно назначить только активного пользователя. При удалении исполнителя
  задача остаётся без исполнителя. При удалении автора его задачи удаляются.
- Для чужих объектов изменение возвращает `403`, для несуществующих — `404`.

## Эксплуатация

### Логи

Всё пишется в stdout/stderr контейнера (`docker compose logs web`): access-лог gunicorn
со временем ответа, ошибки 5xx с трейсбеком (`django.request`), предупреждения
безопасности (`django.security`, например чужой `Host`). Стандартная рассылка ошибок
на почту админам отключена. Уровень задаётся `DJANGO_LOG_LEVEL`.

### Gunicorn

`gunicorn.conf.py`: воркеры `gthread` (по умолчанию `min(2 * CPU + 1, 4)` процессов
по 4 потока), чтобы медленный клиент или запрос не занимал процесс целиком; `timeout`
и `graceful_timeout` 30 с, `keepalive` 5 с; воркеры перезапускаются примерно каждые
1000 запросов (с разбросом, чтобы не все сразу); heartbeat-файлы в `/dev/shm`.
`stop_grace_period` в compose больше `graceful_timeout`, поэтому при остановке текущие
запросы успевают завершиться.

Постоянное соединение с БД держит каждый поток (`DJANGO_CONN_MAX_AGE`, с проверкой
живости перед использованием), всего до `workers * threads` соединений — это должно
укладываться в `max_connections` PostgreSQL.

### Health-check

`GET /api/health/` без аутентификации и троттлинга выполняет `SELECT 1` в БД и запрос
в кэш. Ответ `200 {"status": "ok", "checks": {...}}` или `503` с указанием упавшей
зависимости; подробности ошибки только в логе. Его вызывает `HEALTHCHECK` образа;
при `DJANGO_SECURE_HTTPS=1` путь исключён из редиректа на HTTPS.

### Троттлинг

- Анонимные запросы — `THROTTLE_ANON_RATE`, аутентифицированные — `THROTTLE_USER_RATE`
  на пользователя.
- Регистрация, получение и обновление токена делят отдельный, более строгий лимит
  `THROTTLE_AUTH_RATE` на IP — защита от перебора паролей. Для вьюх simplejwt сделаны
  подклассы с `throttle_scope`, без них скоуп не применяется.
- При превышении — `429` с заголовком `Retry-After`.
- Счётчики хранятся в Redis: кэш в памяти у каждого процесса gunicorn свой, и реальный
  лимит был бы в `workers` раз выше. Без `REDIS_URL` (локально, в тестах) используется
  кэш в памяти. Redis в compose без персистентности и с ограничением памяти.
- При недоступности Redis троттлинг пропускает запросы (fail-open, `config/throttling.py`):
  API продолжает работать, но **лимиты на время аварии не действуют**, включая лимит на
  подбор паролей. Это осознанный выбор: доступность сервиса важнее лимитов, а авария кэша
  видна сразу — каждый пропущенный лимит пишет `WARNING` в лог. Перехватываются только ошибки Redis (`RedisError`), остальные исключения
  не глотаются. Если Redis не отвечает, а не отказывает в соединении, каждый запрос
  дольше на таймаут сокета (2 с на обращение к кэшу).
- IP клиента берётся из адреса соединения (`NUM_PROXIES=0`). За прокси укажите число
  прокси: иначе DRF доверял бы `X-Forwarded-For`, и клиент обходил бы лимит подделкой
  заголовка (на это есть тест).

### Конкурентность

`complete` и `reopen` выполняются в транзакции: строка задачи блокируется
`SELECT ... FOR UPDATE`, и проверка текущего статуса идёт уже под блокировкой
(`Task.complete()` / `Task.reopen()`). Поэтому одновременные `complete`/`reopen` одной
задачи выполняются по очереди: из двух одновременных `complete` один получит `200`,
второй — `400`, `completed_at` выставляется один раз. Вьюха только проверяет права и
превращает доменную ошибку в `400`.

`PUT`/`PATCH` задачи (в том числе поля `status`) не блокируют строку: для них действует
«последняя запись побеждает», как обычно для полного обновления ресурса. `completed_at`
при этом всегда согласован со статусом (его выставляет `Task.save()`).

### Безопасность

- При `DJANGO_DEBUG=False` обязателен `DJANGO_SECRET_KEY`, иначе приложение не стартует.
- Всегда: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, HttpOnly-cookie сессии.
- Админка подключается только при `DJANGO_ADMIN_ENABLED=1` (по умолчанию — только при
  `DEBUG`), иначе её URL отдают `404`. У формы входа нет ограничения попыток, поэтому
  в продакшене её стоит включать только за HTTPS и VPN или списком IP на прокси,
  с неочевидным путём в `DJANGO_ADMIN_URL`. Через неё же работает вход в browsable API
  (session-аутентификация); без админки API доступно по JWT, в том числе из Swagger UI.
- `DJANGO_SECURE_HTTPS=1` включает редирект на HTTPS, secure-cookie и HSTS.
  По умолчанию выключено, потому что compose отдаёт приложение по HTTP.
- За TLS-терминатором (nginx, балансировщик облака): `DJANGO_SECURE_HTTPS=1`,
  `DJANGO_SECURE_PROXY_SSL_HEADER=1` (прокси должен перезаписывать `X-Forwarded-Proto`),
  `NUM_PROXIES=1`, домен в `DJANGO_ALLOWED_HOSTS` и `DJANGO_CSRF_TRUSTED_ORIGINS`.
  Порт `web` тогда публикуется только локально: `HTTP_PORT=127.0.0.1:8000`.
- `python manage.py check --deploy` с HTTPS-настройками проходит без предупреждений
  (так он запускается в CI). Без `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=1` и
  `DJANGO_SECURE_HSTS_PRELOAD=1` остаются предупреждения W005 и W021: распространять
  HSTS на поддомены и вносить домен в preload-список браузеров — решение владельца домена,
  поэтому по умолчанию это выключено.

## Тесты и линтер

```bash
pytest                  # все тесты на SQLite
pytest --cov            # с отчётом о покрытии
ruff check .            # линтер (PEP 8, isort, pyflakes, bugbear, правила Django)
ruff format --check .   # форматирование

# На PostgreSQL (так запускается и CI):
createdb tasks
DATABASE_URL=postgres://localhost:5432/tasks pytest
```

Тесты покрывают регистрацию и JWT, CRUD задач, права доступа, `complete`/`reopen`,
назначение исполнителя, комментарии, фильтры, поиск и сортировку, модели, `seed_demo`,
троттлинг, health-check и генерацию OpenAPI-схемы (тест падает на любом предупреждении
drf-spectacular).

Тест гонки (`tests/test_concurrency.py`) запускает два одновременных `complete`
(и `reopen`) из разных потоков: запрос, прошедший проверку статуса, ждёт второй на
барьере перед записью. С блокировкой второй стоит на `SELECT ... FOR UPDATE`, и итог
`200` + `400`; если убрать блокировку, оба проходят проверку и тест падает. На SQLite
он пропускается: там нет блокировок строк.

### CI

`.github/workflows/ci.yml`: `ruff check` и `ruff format --check`; `manage.py check`,
`makemigrations --check`, валидация OpenAPI-схемы, `check --deploy` с продакшен-настройками;
pytest с покрытием на PostgreSQL-сервисе (тест гонки выполняется); сборка образа и
запуск всего compose-стека с проверкой `/api/health/`.

## Возможные доработки

- Blacklist refresh-токенов для logout.
- История изменений задачи и уведомления исполнителю.
- Оптимистическая блокировка (версия или `ETag`/`If-Match`) для `PATCH`, если
  одновременное редактирование задачи станет реальным сценарием.
