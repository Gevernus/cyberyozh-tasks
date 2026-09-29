# Эксплуатация

Справочник для того, кто разворачивает и сопровождает сервис. Коротко о том, что это и
зачем так устроено, — в [README](../README.md).

- [Схема](#схема)
- [Переменные окружения](#переменные-окружения)
- [Деплой](#деплой)
- [TLS и Let's Encrypt](#tls-и-lets-encrypt)
- [Масштабирование и база данных](#масштабирование-и-база-данных)
- [Логи, метрики, ошибки](#логи-метрики-ошибки)
- [Health-check](#health-check)
- [Троттлинг и деградация без Redis](#троттлинг-и-деградация-без-redis)
- [Нагрузочный тест](#нагрузочный-тест)
- [Зависимости и проверки безопасности](#зависимости-и-проверки-безопасности)
- [Runbook](#runbook)

## Схема

```
клиент ──HTTPS──▶ caddy :80/:443 ──HTTP──▶ web × N (gunicorn gthread) ──▶ db (PostgreSQL 17)
                  TLS, HSTS, CSP,          stateless, без портов на хосте └──▶ redis (счётчики лимитов)
                  лимит тела 1 МБ,
                  балансировка, /metrics закрыт
migrate — одноразовый контейнер: `manage.py migrate` до старта web
```

Наружу опубликован только `caddy`. `web`, `db` и `redis` доступны лишь в сети compose.

## Переменные окружения

Все значения читаются в `config/settings.py`, шаблон — `.env.example`. Compose сам
собирает `DATABASE_URL`, `REDIS_URL`, `DJANGO_ALLOWED_HOSTS` (`$DOMAIN,localhost,127.0.0.1`)
и `DJANGO_CSRF_TRUSTED_ORIGINS` (`https://$DOMAIN`).

| Переменная | По умолчанию (без `.env`) | В `.env.example` | Назначение |
|---|---|---|---|
| `DOMAIN` | — | `localhost` | публичное имя; сертификат, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` |
| `CADDY_TLS` | `acme` | `internal` | `acme` — Let's Encrypt, `internal` — CA самого Caddy (CI, локально) |
| `DJANGO_SECRET_KEY` | ключ разработки | обязателен | без него при `DEBUG=False` приложение не стартует |
| `POSTGRES_PASSWORD` | — | обязателен | пароль БД в compose |
| `POSTGRES_DB` / `POSTGRES_USER` | `tasks` / `tasks` | | |
| `DJANGO_DEBUG` | `True` | `False` | |
| `DJANGO_ADMIN_ENABLED` / `DJANGO_ADMIN_URL` | как `DEBUG` / `admin/` | `0` | у входа в админку нет лимита попыток: только за VPN/allowlist |
| `DJANGO_LOG_LEVEL` | `INFO` | | |
| `DJANGO_CONN_MAX_AGE` | `60` | | жизнь постоянного соединения с БД, с |
| `DJANGO_DB_STATEMENT_TIMEOUT_MS` | `5000` | | `statement_timeout` PostgreSQL; `0` — без лимита (так работает `migrate`) |
| `JWT_ACCESS_TOKEN_MINUTES` / `JWT_REFRESH_TOKEN_DAYS` | `15` / `7` | | |
| `DJANGO_SECURE_HTTPS` | `0` | `1` | редирект на HTTPS, secure-cookies, HSTS |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | `0` | `1` | доверять `X-Forwarded-Proto` (Caddy всегда его перезаписывает) |
| `DJANGO_SECURE_HSTS_SECONDS` | `31536000` | | |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` / `_PRELOAD` | `0` | | решение владельца домена |
| `NUM_PROXIES` | `0` | `1` | прокси перед приложением; IP клиента — последний адрес в `X-Forwarded-For` |
| `THROTTLE_ANON_RATE` / `THROTTLE_USER_RATE` | `100/hour` / `1000/hour` | | общие лимиты |
| `THROTTLE_AUTH_RATE` | `10/min` | | регистрация, токен, refresh, logout — на IP |
| `THROTTLE_AUTH_ACCOUNT_RATE` | `20/hour` | | выдача токена — на имя пользователя, с любых IP |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` / `SENTRY_TRACES_SAMPLE_RATE` | пусто / `production` / `0` | | пустой DSN — Sentry выключен |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | `min(2·CPU+1, 4)` / `4` | | |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | | чьим `X-Forwarded-*` доверяет сам gunicorn |
| `PROMETHEUS_MULTIPROC_DIR` | задан в образе | | файлы метрик воркеров; очищается при старте gunicorn |

## Деплой

### Первый запуск

```bash
cp .env.example .env
# DJANGO_SECRET_KEY, POSTGRES_PASSWORD; DOMAIN=tasks.example.com; CADDY_TLS=acme
docker compose up -d --build --wait
deploy/smoke.sh tasks.example.com        # сквозная проверка через Caddy
```

Домен должен указывать на хост, порты 80 и 443 открыты (HTTP-01/TLS-ALPN проверки
Let's Encrypt). Порядок старта: `db`, `redis` → `migrate` (завершился с кодом 0) → `web`
(healthy) → `caddy`.

### Обновление

```bash
git pull   # или git archive новой версии в тот же каталог
docker compose build
docker compose up -d --wait              # migrate отработает до перезапуска web
```

Миграции пишутся совместимыми со старым кодом (новые колонки — с `db_default`), поэтому
старые реплики продолжают работать, пока `migrate` меняет схему. Индексы на больших живых
таблицах создавать через `AddIndexConcurrently` в отдельной миграции.

### Остановка

```bash
docker compose down        # без -v!
```

`down -v` удаляет тома, в том числе `caddy_data` с сертификатами и ACME-аккаунтом, и
`postgres_data` с данными. Сертификат после этого будет выпущен заново, а у Let's Encrypt
лимит — 5 одинаковых сертификатов в неделю, см. ниже.

### Переход со старой схемы (web на `:8000`, миграции в entrypoint)

1. Бэкап: `docker compose exec -T db pg_dump -U tasks tasks | gzip > backup.sql.gz`,
   копия `.env`.
2. Выложить новую версию в тот же каталог (удалённые файлы тоже убрать: `docker/`).
3. Собрать `.env` из нового `.env.example`, перенеся `DJANGO_SECRET_KEY` и
   **тот же** `POSTGRES_PASSWORD` (БД в томе инициализирована с ним). Задать `DOMAIN`,
   `CADDY_TLS=acme`. `DJANGO_MIGRATE`, `HTTP_PORT`, `DJANGO_ALLOWED_HOSTS`,
   `DJANGO_CSRF_TRUSTED_ORIGINS` больше не нужны.
4. `docker compose build && docker compose up -d --remove-orphans --wait`. Контейнер `web`
   пересоздаётся без публикации порта, порт 8000 на хосте закрывается.
5. `deploy/smoke.sh $DOMAIN`, проверить выпуск сертификата: `docker compose logs caddy`.

Откат: `docker compose down` (без `-v`), вернуть прежний каталог и `.env`,
`docker compose up -d`. Схема после новых миграций совместима со старым кодом.

## TLS и Let's Encrypt

- `deploy/Caddyfile`: сайт `{$DOMAIN}`; при `CADDY_TLS=acme` Caddy сам получает и
  продлевает сертификат Let's Encrypt, при `CADDY_TLS=internal` — выпускает его своим CA
  (браузер и curl ему не доверяют: `curl -k`).
- HTTP → HTTPS (308) делает Caddy. HSTS, `nosniff`, `X-Frame-Options`, `Referrer-Policy`
  Caddy ставит только там, где их не поставил Django (ответы 413/502 самого Caddy), CSP —
  всегда. CSP рассчитан на Swagger UI, Redoc и browsable API: скрипты и стили только свои
  (`drf-spectacular-sidecar`), инлайн-стили и шрифты Google для Redoc.
- Сертификаты и ACME-аккаунт — в томе `caddy_data`. Лимиты Let's Encrypt: 5 сертификатов
  на один набор имён в неделю, 5 неудачных проверок на имя в час. Поэтому том не удалять,
  а при отладке DNS/портов переключаться на `CADDY_TLS=internal`.
- `*.sslip.io` (стенд) — общий домен многих пользователей: если в логах Caddy появится
  `rateLimited`, дождаться окна или временно перейти на `CADDY_TLS=internal`.

## Масштабирование и база данных

**Реплики.** `docker compose up -d --scale web=N`. `web` без состояния, без
`container_name` и портов; Caddy находит реплики через DNS Docker (`dynamic a web 8000`,
обновление раз в 5 с), балансирует `least_conn`, повторяет запрос на другой реплике при
ошибке соединения (для GET — при любой) в течение 5 с и выводит реплику из ротации после
5 ошибок за 10 с. Активных health-check Caddy для динамических upstream не делает — живость
реплик проверяет `HEALTHCHECK` образа. Keepalive Caddy→gunicorn 3 с, меньше, чем у gunicorn
(5 с), чтобы прокси не отправлял запрос в соединение, которое приложение уже закрыло.

На одном хосте реплики имеют смысл, пока есть свободные ядра: воркеров по умолчанию
`min(2·CPU+1, 4)` на реплику. Дальше — несколько хостов с управляемыми PostgreSQL и Redis;
контейнер `web` для этого готов (конфигурация только из окружения, миграции — отдельный
шаг, liveness `/api/health/live/`, readiness `/api/health/`).

**Соединения с БД.** Каждый поток gunicorn держит постоянное соединение
(`DJANGO_CONN_MAX_AGE`, с проверкой перед использованием): всего
`реплики × воркеры × потоки` = `N × 4 × 4`. При `max_connections=100` у PostgreSQL это
до 5 реплик с запасом на `migrate`, админку и мониторинг.

**Почему без PgBouncer.** До ~5 реплик соединения укладываются в `max_connections`, а
PgBouncer в режиме `transaction` ломает то, на что опирается приложение:
`statement_timeout` передаётся стартовым параметром соединения (`options`), который
PgBouncer по умолчанию отвергает, а в режиме `transaction` не может закрепить за
клиентом; серверные курсоры Django (`.iterator()`) требуют
`DISABLE_SERVER_SIDE_CURSORS=True`. Режим `session` не экономит соединений при
`CONN_MAX_AGE`. Включать, когда `N × воркеры × потоки` приближается к `max_connections`
или реплик становится много: PgBouncer в `transaction`, `statement_timeout` —
через `ALTER ROLE … SET statement_timeout`, `DISABLE_SERVER_SIDE_CURSORS=True`,
`CONN_MAX_AGE=0` (или управляемый аналог: RDS Proxy, Cloud SQL connector).

**Запросы.** `statement_timeout` 5 с на каждое соединение приложения — зависший запрос
не держит поток и соединение. Число SQL-запросов каждого list/retrieve зафиксировано
тестами (`tests/test_query_counts.py`). Индексы (1 млн задач, PostgreSQL 17, ноутбук):

| Запрос | План | Время |
|---|---|---|
| список, первая страница | `task_newest_first_idx` | 0,1 мс |
| список, страница в середине (курсор) | `task_newest_first_idx` | 0,2 мс |
| `?assignee=` / `?author=` | `task_assignee_newest_idx` / `task_author_newest_idx` | 0,1 мс |
| `?search=` редкого слова | GIN pg_trgm по `UPPER(title/description)` | 0,1 мс (без индекса 730 мс) |

**Токены.** Каждый выданный refresh-токен — строка в `token_blacklist_outstandingtoken`.
Раз в сутки: `docker compose run --rm migrate python manage.py flushexpiredtokens`.

## Логи, метрики, ошибки

- **Логи** — JSON-строки в stdout (`docker compose logs web`): `timestamp`, `level`,
  `logger`, `process`, `message`, `request_id`; ошибки 5xx — с `exc_info`. Access-лог
  gunicorn — тоже JSON: `method`, `path`, `status`, `bytes`, `duration_ms`, `remote_addr`,
  `forwarded_for` (реальный IP клиента), `user_agent`, `request_id`. Caddy пишет свой
  JSON access-лог, в нём тот же `X-Request-ID` в заголовках ответа.
  Логи всех контейнеров ротируются Docker: 5 файлов по 20 МБ.
- **Request ID.** Берётся из `X-Request-ID`, если он соответствует
  `^[A-Za-z0-9._-]{1,64}$`, иначе генерируется (uuid4 hex). Возвращается в ответе,
  попадает во все записи лога этого запроса и в тег Sentry.
- **Метрики.** `GET /metrics` (django-prometheus): запросы, статусы и латентность по вьюхам,
  исключения. Воркеры gunicorn пишут метрики в `PROMETHEUS_MULTIPROC_DIR`, ответ собирает
  их вместе. Отдаётся только адресам loopback и частных сетей (по адресу сокета, без
  доверия `X-Forwarded-For`); снаружи Caddy отвечает 404. Сборщик в той же сети compose
  обращается к `http://web:8000/metrics` с `Host`, входящим в `ALLOWED_HOSTS`
  (например `localhost`); при `--scale` — к каждой реплике (DNS-SD `web`).
- **Sentry** включается `SENTRY_DSN`; `send_default_pii=False` — тела запросов, cookies и
  данные пользователя не отправляются. `SENTRY_TRACES_SAMPLE_RATE` — доля трассировок.

## Health-check

| Путь | Что проверяет | Кто использует |
|---|---|---|
| `GET /api/health/live/` | процесс отвечает; зависимости не трогает | `HEALTHCHECK` образа, `compose --wait` |
| `GET /api/health/` | `SELECT 1` и запрос в Redis: `200 ok`, `200 degraded` (нет Redis), `503 error` (нет БД) | мониторинг, внешний балансировщик |

Оба без аутентификации и троттлинга, исключены из редиректа на HTTPS (проверки идут по
HTTP внутри сети). Подробности ошибок только в логе.

## Троттлинг и деградация без Redis

| Лимит | Ключ | Без Redis |
|---|---|---|
| `anon` 100/час | IP | пропускает (fail-open) |
| `user` 1000/час | пользователь | пропускает (fail-open) |
| `auth` 10/мин — регистрация, токен, refresh, logout | IP | счётчик в памяти процесса |
| `auth_account` 20/час — выдача токена | sha256 от нормализованного имени | счётчик в памяти процесса |

Счётчики лежат в Redis, общем для всех процессов и реплик. Если Redis недоступен, общие
лимиты пропускают запросы — доступность API важнее, — а лимиты входа продолжают считать
в памяти каждого процесса gunicorn (`LOCAL_CACHE` в `config/throttling.py`). Каждое такое
событие пишет `WARNING` в лог, readiness отвечает `degraded`.

**Эффективный лимит в деградации** — лимит × число процессов, по которым Caddy
распределяет запросы: `rate × GUNICORN_WORKERS × реплики`. По умолчанию (4 воркера):

| Реплик | `auth` на IP | `auth_account` на имя |
|---|---|---|
| 1 | до 40/мин | до 80/час |
| 2 | до 80/мин | до 160/час |
| N | до 40·N/мин | до 80·N/час |

Потоки одного процесса делят счётчик. Тест `test_auth_limits_count_in_process_memory_when_the_cache_is_down`
проверяет, что без Redis лимит в процессе соблюдается точно.

`auth_account` защищает от подбора пароля одного аккаунта с многих IP. Обратная сторона —
злоумышленник может исчерпать лимит чужого аккаунта; вход для него откроется, когда
старые попытки выйдут из часового окна.

## Нагрузочный тест

Данные (на стенде, один раз; `migrate` запускается без `statement_timeout`):

```bash
docker compose run --rm migrate python manage.py seed_bulk \
    --tasks 1000000 --users 1000 --password "$LOAD_PASSWORD" --seed 42
```

Пользователи `load00000…load00999` с паролем `$LOAD_PASSWORD`, задачи с комментариями;
`comments_count` согласован. Локально 1 млн задач — около 1,5 минуты.

На время теста поднять лимиты (все запросы идут с одного IP) в `.env` и применить
`docker compose up -d --wait`, после — вернуть:

```
THROTTLE_ANON_RATE=100000/hour
THROTTLE_USER_RATE=1000000/hour
THROTTLE_AUTH_RATE=1000/min
THROTTLE_AUTH_ACCOUNT_RATE=1000/hour
```

Запуск с машины вне стенда:

```bash
k6 run -e BASE_URL=https://$DOMAIN -e PASSWORD="$LOAD_PASSWORD" \
    -e USERS=50 -e RATE=50 -e DURATION=5m \
    --summary-export loadtest/results/$(date +%F)-rate50.json loadtest/tasks.js
```

Сценарий `loadtest/tasks.js` — постоянная интенсивность `RATE` итераций в секунду: 60% —
список (первая страница и следующая по курсору) и одна задача, 25% — создание и
`complete`, 15% — комментарий к одной из новых задач. Пороги: ошибок < 1%, p95 списка,
создания, `complete` и комментария < 500 мс, задачи < 300 мс. `DURATION` держать меньше
жизни access-токена (15 мин). Прочие параметры: `USER_PREFIX`, `INSECURE=1` (для
`CADDY_TLS=internal`), `HOST_IP` (адрес вместо DNS).

## Зависимости и проверки безопасности

- Прямые зависимости — `requirements.in` и `requirements-dev.in`, зафиксированные с
  хешами — `requirements.txt` и `requirements-dev.txt`:

  ```bash
  pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file=requirements.txt requirements.in
  pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file=requirements-dev.txt requirements-dev.in
  pip-sync requirements-dev.txt
  ```

  Образ ставит только готовые wheels с проверкой хешей (`--require-hashes --only-binary`).
- CI (`security`): `pip-audit` по обоим lock-файлам, `bandit -c pyproject.toml -r .`,
  `gitleaks git` по всей истории (`.gitleaksignore` — тестовый пароль фабрики), Trivy по
  собранному образу (HIGH/CRITICAL с доступным исправлением — ошибка). Действие Trivy
  закреплено по коммиту: теги были скомпрометированы в марте 2026 (GHSA-69fq-xp46-6x23).

## Runbook

| Симптом | Что смотреть | Что делать |
|---|---|---|
| readiness `degraded`, в логах `WARNING config.throttling` | `docker compose ps redis`, `logs redis` | `docker compose restart redis`; пока Redis нет — лимиты см. выше |
| readiness `503`, API отвечает 500 | `docker compose ps db`, `logs db`, диск | поднять БД; контейнеры web перезапускать не нужно |
| 502/503 от Caddy, `no upstreams available` | `docker compose ps web`, `logs web` | реплики не healthy или все выведены после ошибок; `docker compose up -d --wait` |
| рост 5xx | `logs web` по `request_id` из ответа, Sentry | |
| `canceling statement due to statement timeout` | запрос в логе, `EXPLAIN ANALYZE` | индекс или ограничение запроса; разово — поднять `DJANGO_DB_STATEMENT_TIMEOUT_MS` |
| сертификат не выпускается | `logs caddy` (`acme`, `rateLimited`) | DNS → хост, порты 80/443, не удалять `caddy_data`; временно `CADDY_TLS=internal` |
| `migrate` завершился с ошибкой, web не стартует | `docker compose logs migrate` | исправить миграцию/БД, `docker compose up -d --wait` |
| таблица outstanding-токенов растёт | `SELECT count(*) FROM token_blacklist_outstandingtoken` | `manage.py flushexpiredtokens` по расписанию |
| смена `DJANGO_SECRET_KEY` | | все JWT и сессии станут недействительны: `up -d` в окно обслуживания |
