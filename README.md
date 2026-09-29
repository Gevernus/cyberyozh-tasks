# Task Management API

REST API для управления задачами на Django 5.2 и Django REST Framework. Пользователи
создают, редактируют и удаляют задачи, назначают их друг другу, отмечают выполненными и
обсуждают в комментариях. Аутентификация — JWT.

Стенд: [Swagger UI](https://5-129-210-237.sslip.io/api/docs/),
[Redoc](https://5-129-210-237.sslip.io/api/redoc/). Сценарий в Swagger UI:
`POST /api/auth/register/` → `POST /api/auth/token/` → Authorize с access-токеном →
запросы к `/api/tasks/`.

## Быстрый старт

Локально нужен Python 3.12+; база — SQLite, переменные окружения не нужны:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo      # пользователи alice, bob, carol; пароль печатается
python manage.py runserver      # http://127.0.0.1:8000/ открывает Swagger UI
```

Docker Compose поднимает PostgreSQL, Redis и Caddy с HTTPS:

```bash
cp .env.example .env            # заменить change-me
docker compose up -d --build --wait
CURL_OPTS=--insecure deploy/smoke.sh localhost
```

`.env.example` настроен на `DOMAIN=localhost` и сертификат от CA Caddy. Для публичного
домена: `DOMAIN=tasks.example.com`, `CADDY_TLS=acme`.

## Тесты и проверки

```bash
ruff check . && ruff format --check .
pytest                                                # SQLite
DATABASE_URL=postgres://localhost:5432/tasks pytest   # плюс тесты гонок и индексов PostgreSQL
python manage.py makemigrations --check --dry-run
pip-audit --strict --disable-pip --require-hashes -r requirements.txt -r requirements-dev.txt
bandit -c pyproject.toml -r .
```

CI (`.github/workflows/ci.yml`) запускает то же на PostgreSQL, `check --deploy`, gitleaks,
Trivy по образу и smoke-тест стека с двумя репликами `web`.

## API

| Метод и путь | Описание |
|---|---|
| `POST /api/auth/register/` | регистрация |
| `POST /api/auth/token/` | пара JWT по логину и паролю |
| `POST /api/auth/token/refresh/` | новая пара; старый refresh-токен отзывается |
| `POST /api/auth/token/blacklist/` | выход: отзыв refresh-токена |
| `GET /api/users/`, `/api/users/{id}/`, `/api/users/me/` | активные пользователи |
| `GET, POST /api/tasks/` | список и создание задач |
| `GET, PUT, PATCH, DELETE /api/tasks/{id}/` | задача |
| `POST /api/tasks/{id}/assign/` | назначить исполнителя: `{"assignee_id": id}` или `null` |
| `POST /api/tasks/{id}/complete/`, `/reopen/` | выполнить, вернуть в работу |
| `GET, POST /api/tasks/{id}/comments/` | комментарии задачи |
| `GET, PUT, PATCH, DELETE /api/tasks/{id}/comments/{comment_id}/` | комментарий |
| `GET /api/health/live/`, `/api/health/` | liveness и readiness |

Списки задач и комментариев — по курсору (`next`, `previous`, без `count`). Фильтры
задач: `status`, `priority`, `author`, `assignee`, `unassigned=true`, `due_after`,
`due_before`, `search`. Менять задачу может только автор, `complete` и `reopen` — автор или
исполнитель. Схема OpenAPI — `/api/schema/`.

## Документация

- [docs/architecture.md](docs/architecture.md) — устройство сервиса и решения по API,
  конкурентности, счётчику комментариев, индексам, троттлингу и безопасности.
- [docs/operations.md](docs/operations.md) — переменные окружения, деплой и обновление,
  миграции, наблюдаемость и runbook.
- [docs/load-testing.md](docs/load-testing.md) — методика нагрузочного теста на 1 млн задач
  и его результаты.

## Структура

```
config/     настройки, URL, WSGI/ASGI
core/       пагинация, троттлинг, health-check, метрики, request id, OpenAPI, миграции
apps/       accounts: пользователи и JWT; tasks: задачи и комментарии
deploy/     Caddyfile, smoke.sh
loadtest/   сценарий k6 и результаты
tests/      pytest
docs/       документация
```
