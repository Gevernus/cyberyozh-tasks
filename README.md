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
- 67 тестов на pytest, покрытие 99%.
- SQLite по умолчанию, PostgreSQL через `DATABASE_URL`, Docker Compose с PostgreSQL.
- Команда `seed_demo` для демо-данных.

## Стек

Python 3.12, Django 5.2 LTS, Django REST Framework, simplejwt, drf-spectacular,
django-filter, dj-database-url, pytest + pytest-django + factory_boy, ruff.

## Структура

```
config/                 настройки (из переменных окружения), корневые URL, пагинация
apps/accounts/          модель пользователя, регистрация, /api/users/
apps/tasks/             модели Task и Comment, API, права, фильтры, seed_demo
tests/                  тесты API, прав, фильтров, моделей, документации
```

## Быстрый старт (локально, SQLite)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python manage.py migrate
python manage.py createsuperuser     # по желанию, для /admin/
python manage.py seed_demo           # по желанию: alice, bob, carol / demo-pass-123
python manage.py runserver
```

После запуска:

| Что | Адрес |
|---|---|
| Swagger UI | http://127.0.0.1:8000/api/docs/ |
| Redoc | http://127.0.0.1:8000/api/redoc/ |
| OpenAPI-схема | http://127.0.0.1:8000/api/schema/ |
| Админка | http://127.0.0.1:8000/admin/ |

Локально переменные окружения не нужны: по умолчанию включён `DEBUG` и используется SQLite.

### Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DJANGO_DEBUG` | `True` | режим отладки |
| `DJANGO_SECRET_KEY` | ключ для разработки | обязателен при `DJANGO_DEBUG=False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | список через запятую |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | например `postgres://user:pass@host:5432/db` |

## Запуск через Docker Compose (PostgreSQL)

```bash
cp .env.example .env    # по желанию: задать свой DJANGO_SECRET_KEY
docker compose up --build
docker compose exec web python manage.py seed_demo          # демо-данные
docker compose exec web python manage.py createsuperuser    # админ
```

API будет доступно на http://localhost:8000/api/docs/. Миграции применяются при старте
контейнера, статика собирается при сборке образа и отдаётся через WhiteNoise.

## Работа с API

Все эндпоинты, кроме регистрации, получения токена и документации, требуют
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
  чтобы клиент не перезаписал время выполнения по ошибке.
- Исполнителем можно назначить только активного пользователя. При удалении исполнителя
  задача остаётся без исполнителя. При удалении автора его задачи удаляются.
- Для чужих объектов изменение возвращает `403`, для несуществующих — `404`.

## Тесты и линтер

```bash
pytest                  # все тесты
pytest --cov            # с отчётом о покрытии
ruff check .            # линтер (PEP 8, isort, pyflakes, bugbear, правила Django)
ruff format --check .   # форматирование
```

Тесты покрывают регистрацию и JWT, CRUD задач, права доступа, `complete`/`reopen`,
назначение исполнителя, комментарии, фильтры, поиск и сортировку, модели, `seed_demo`
и генерацию OpenAPI-схемы (тест падает на любом предупреждении drf-spectacular).
По умолчанию тесты идут на SQLite. С `DATABASE_URL` они запускаются на PostgreSQL.

## Возможные доработки

- HTTPS-настройки для продакшена (`SECURE_*`, HSTS, secure cookies). Сейчас их нет,
  потому что compose-окружение работает по HTTP.
- Blacklist refresh-токенов для logout.
- История изменений задачи и уведомления исполнителю.
