# Task Management API

REST API системы управления задачами на Django 5.2 + Django REST Framework.
Пользователи создают, редактируют и удаляют задачи, назначают их другим пользователям,
отмечают выполненными и обсуждают в комментариях.

Сервис рассчитан на промышленную нагрузку: HTTPS через Caddy, горизонтальное
масштабирование, курсорная пагинация по индексам, структурные логи, метрики, Sentry,
зависимости с хешами и проверки безопасности в CI. Эксплуатация подробно —
в [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Быстрый старт

**Локально** (SQLite, кэш в памяти, `DEBUG` включён — переменные окружения не нужны):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo      # по желанию: alice, bob, carol; пароль печатается
python manage.py runserver      # http://127.0.0.1:8000/api/docs/
```

**Docker Compose** (PostgreSQL, Redis, Caddy с HTTPS):

```bash
cp .env.example .env            # заменить change-me: DJANGO_SECRET_KEY, POSTGRES_PASSWORD
docker compose up -d --build --wait
CURL_OPTS=--insecure deploy/smoke.sh localhost   # сертификат от CA Caddy
```

`.env.example` настроен на `DOMAIN=localhost` и `CADDY_TLS=internal`. Для публичного
домена: `DOMAIN=tasks.example.com`, `CADDY_TLS=acme` — Caddy получит сертификат
Let's Encrypt. Наружу открыт только Caddy (80/443).

## API

Документация: `/api/docs/` (Swagger UI), `/api/redoc/`, схема `/api/schema/`.

| Метод и путь | Описание |
|---|---|
| `POST /api/auth/register/` | регистрация |
| `POST /api/auth/token/` | пара JWT по логину и паролю |
| `POST /api/auth/token/refresh/` | новая пара; старый refresh больше не действует |
| `POST /api/auth/token/blacklist/` | выход: отзыв refresh-токена |
| `GET /api/users/`, `/api/users/{id}/`, `/api/users/me/` | активные пользователи |
| `GET, POST /api/tasks/` | список (курсор) и создание задач |
| `GET, PUT, PATCH, DELETE /api/tasks/{id}/` | задача |
| `POST /api/tasks/{id}/assign/` | назначить исполнителя (`{"assignee_id": id или null}`) |
| `POST /api/tasks/{id}/complete/`, `/reopen/` | выполнить / вернуть в работу |
| `GET, POST /api/tasks/{id}/comments/` | комментарии задачи |
| `GET, PUT, PATCH, DELETE /api/tasks/{id}/comments/{comment_id}/` | комментарий |
| `GET /api/health/live/`, `/api/health/` | liveness и readiness |

```bash
curl -X POST https://$DOMAIN/api/auth/token/ -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "…"}'                  # -> {"access", "refresh"}
curl https://$DOMAIN/api/tasks/?status=todo -H "Authorization: Bearer $ACCESS"
curl https://$DOMAIN/api/tasks/ -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" -d '{"title": "Отчёт", "assignee_id": 2}'
```

**Список задач**: новые сначала, по 20 (`page_size` до 100). Ответ
`{"next", "previous", "results"}` — переходить по ссылкам `next`/`previous`.
Фильтры: `status`, `priority`, `author`, `assignee`, `unassigned=true`,
`due_after`/`due_before`; `search` — по названию и описанию. **Комментарии задачи** — тоже
по курсору, в порядке обсуждения (старые сначала). Пользователи — постраничные (`page`,
`page_size` до 100, есть `count`).

**Ограничения полей**: `title` до 255 символов, `description` до 10 000, текст
комментария до 2 000, пароль от 10 символов. Access-токен живёт 15 минут, refresh — 7 дней.

**Права**: читать и создавать может любой вошедший; менять, удалять и назначать задачу —
только автор; `complete`/`reopen` — автор или исполнитель; комментарий правит его автор.
Для чужих объектов — `403`, для несуществующих — `404`. Все видят все задачи — общая
доска одной команды; изоляция, если понадобится, добавляется в `get_queryset`.

### Изменения, ломающие совместимость

| Было | Стало | Почему |
|---|---|---|
| список задач: `?page=`, в ответе `count` | курсор: ссылки `next`/`previous`, без `count` | `OFFSET` и `COUNT(*)` растут с таблицей |
| `?ordering=` у списка задач | порядок фиксирован: новые сначала | курсор стабилен только по неизменному ключу |
| комментарии: `?page=`, в ответе `count` | курсор, старые сначала: ссылки `next`/`previous`, без `count` | на задаче со 100 тыс. комментариев `COUNT` — 12 мс, последняя страница — 73 мс с сортировкой на диске; курсор — 0,05 мс |
| занятый логин: `{"username": ["… already exists"]}` | `400 {"non_field_errors": ["Registration failed."]}` | не раскрывать существующие аккаунты |
| refresh-токен многоразовый | одноразовый: refresh выдаёт новый | украденный токен живёт до первого использования |
| access-токен 30 минут | 15 минут (`JWT_ACCESS_TOKEN_MINUTES`) | его нельзя отозвать |
| пароль от 8 символов | от 10 | |
| API на `http://…:8000` | только `https://$DOMAIN` через Caddy | TLS, заголовки безопасности, балансировка |

## Ключевые решения

**Конкурентность.** `complete`/`reopen` блокируют строку (`SELECT … FOR UPDATE`) и проверяют
статус под блокировкой: из двух одновременных `complete` один получит `200`, другой — `400`.
Так же refresh и logout блокируют строку refresh-токена: из двух запросов с одним токеном
новую пару получит один, второй — `401`.
`PUT`/`PATCH` работают по принципу «последняя запись побеждает», `completed_at` всегда
согласован со статусом (`Task.save()`). Тесты гонок идут на PostgreSQL.

**Счётчик комментариев** хранится в задаче (`comments_count`) и меняется атомарным
`UPDATE … SET comments_count = comments_count ± N` в той же транзакции, что и комментарий.
Вычитается число реально удалённых строк: комментарий, удалённый двумя запросами сразу,
вычтется один раз. Удаление задачи стирает её комментарии одним `DELETE`, удаление
пользователя вычитает его комментарии на чужих задачах одним `UPDATE` — число запросов не
зависит от числа комментариев. Полное сохранение задачи счётчик не перезаписывает.
Список задач не делает `COUNT` по комментариям.

**Пагинация по курсору** по `(created_at, id)` с индексом — любая страница это
range-scan индекса, в списке задач и в комментариях задачи. Фильтры по исполнителю и автору обслуживаются индексами в том же
порядке, поиск — trigram-индексами (PostgreSQL). Число SQL-запросов каждого list/retrieve
зафиксировано тестами.

**Троттлинг** в Redis: анонимы 100/час, пользователи 1000/час; вход — 10/мин на IP,
10/час на пару «аккаунт, IP» и 100/час на аккаунт со всех IP (страховка от распределённого
подбора с алертом в логе). Чужой вход с одного адреса не заблокировать: запрос, отклонённый
по адресу, не расходует общий лимит аккаунта. Без Redis общие лимиты пропускают запросы, а
лимиты входа считаются в памяти процесса — подбор остаётся ограниченным (эффективные
значения — в OPERATIONS).

**Регистрация** не раскрывает занятые имена: одинаковый ответ и одинаковая работа
(хеширование пароля) для занятого имени, проверка — после остальных полей. Ошибки формата
по-прежнему указывают поле. Компромисс: `201` для свободного имени всё равно отличается от
`400`, полностью закрыть перебор можно только подтверждением по email (асинхронный `202`);
здесь перебор ограничен лимитом `auth`.

**Безопасность.** HTTPS и HSTS, CSP без CDN и инлайн-скриптов (Swagger UI и Redoc из
статики), `X-Forwarded-For` перезаписывает Caddy, Django доверяет ровно одному прокси.
Админка выключена в продакшене. `/metrics` — только из частной сети. Sentry без
персональных данных. `statement_timeout` 5 с. Образ: non-root, только wheels с проверкой
хешей. CI: pip-audit, bandit, gitleaks по всей истории, Trivy по образу.

## Production & scaling

```
клиент ─HTTPS─▶ Caddy ─┬─▶ web #1 (gunicorn: 4 процесса × 4 потока) ─┬─▶ PostgreSQL
  TLS/HSTS/CSP,        ├─▶ web #2                                     └─▶ Redis (лимиты)
  лимит тела 1 МБ,     └─▶ web #N      ← docker compose up --scale web=N
  /metrics закрыт      migrate: одноразовый контейнер до старта web
```

- **Горизонтально**: `web` без состояния; `docker compose up -d --scale web=N`. Caddy
  находит реплики через DNS Docker, балансирует `least_conn`, повторяет запрос на другой
  реплике при ошибке соединения и выводит сбойную реплику из ротации. Миграции — отдельный
  сервис `migrate`, web сам не мигрирует, поэтому реплик может быть сколько угодно.
- **За пределы одного хоста**: управляемые PostgreSQL и Redis,
  тот же образ на нескольких машинах за балансировщиком; `migrate` — шаг релиза;
  liveness `/api/health/live/`, readiness `/api/health/`. Kubernetes не нужен, пока
  хватает нескольких хостов: образ к нему готов (Deployment + Job для миграций + HPA по
  CPU/латентности), но оркестратор — это отдельная эксплуатационная нагрузка.
- **Без PgBouncer**: каждый поток держит постоянное соединение, `N × 16` соединений
  укладываются в `max_connections=100` до ~5 реплик. PgBouncer в режиме `transaction`
  несовместим со `statement_timeout` в параметрах соединения и серверными курсорами —
  его стоит включать, когда соединений станет больше, с настройками из OPERATIONS.

### Нагрузка

Стенд: 2 vCPU, 1,9 ГБ RAM, compose на одном хосте, 1 млн задач (`seed_bulk`), k6 с
внешней машины через HTTPS, смешанный сценарий (`loadtest/tasks.js`).

| Интенсивность | Запросов/с | p50 | p95 | p99 | Ошибок |
|---|---|---|---|---|---|
| _заполняется после прогона на стенде_ | | | | | |

Результаты k6 — в `loadtest/results/`, методика — в OPERATIONS.

## Разработка и проверки

```bash
ruff check . && ruff format --check .
pytest --cov                                                     # SQLite
DATABASE_URL=postgres://localhost:5432/tasks pytest              # + тесты гонок и индексов
python manage.py makemigrations --check --dry-run
python manage.py spectacular --validate --fail-on-warn --file /dev/null
pip-audit --strict --disable-pip --require-hashes -r requirements.txt -r requirements-dev.txt
bandit -c pyproject.toml -r .
```

210 тестов на PostgreSQL (на SQLite 203: тесты гонок и индексов пропускаются), покрытие 98%.
CI (`.github/workflows/ci.yml`): линтер; проверки Django, миграций, OpenAPI и
`check --deploy`; тесты на PostgreSQL; security-сканы; сборка стека с двумя репликами web
и сквозной smoke-тест через Caddy (`deploy/smoke.sh`).

```
config/          настройки из окружения, URL, пагинация, троттлинг, health, метрики, request id
apps/accounts/   пользователь, регистрация, JWT
apps/tasks/      задачи, комментарии, права, фильтры, seed_demo, seed_bulk
deploy/          Caddyfile, smoke.sh
loadtest/        сценарий k6 и результаты
tests/           pytest
docs/            OPERATIONS.md
```
