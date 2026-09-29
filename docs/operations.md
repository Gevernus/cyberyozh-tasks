# Эксплуатация

## Переменные окружения

Читаются в `config/settings.py` и `gunicorn.conf.py`. В `.env.example` — только
обязательные и отличающиеся от значений по умолчанию. Compose сам задаёт `DATABASE_URL`,
`REDIS_URL`, `DJANGO_ALLOWED_HOSTS` (`$DOMAIN,localhost,127.0.0.1`) и
`DJANGO_CSRF_TRUSTED_ORIGINS` (`https://$DOMAIN`).

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DOMAIN` | обязательна | публичное имя: сертификат, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` |
| `CADDY_TLS` | `acme` | `acme` — Let's Encrypt, `internal` — CA самого Caddy (CI, локально) |
| `DJANGO_SECRET_KEY` | ключ разработки | обязателен при `DJANGO_DEBUG=False` |
| `POSTGRES_PASSWORD` | обязателен | пароль БД в compose, только URL-безопасные символы |
| `POSTGRES_DB`, `POSTGRES_USER` | `tasks` | |
| `DATABASE_URL` | SQLite `db.sqlite3` | вне compose |
| `REDIS_URL` | пусто: кэш в памяти процесса | вне compose |
| `DJANGO_DEBUG` | `True` | |
| `DJANGO_ADMIN_ENABLED` | как `DJANGO_DEBUG` | у входа в админку нет лимита попыток: включать только за VPN или allowlist |
| `DJANGO_ADMIN_URL` | `admin/` | |
| `DJANGO_LOG_LEVEL` | `INFO` | |
| `DJANGO_CONN_MAX_AGE` | `60` | время жизни постоянного соединения с БД, с |
| `DJANGO_DB_STATEMENT_TIMEOUT_MS` | `5000` | `statement_timeout` PostgreSQL; `0` — без лимита (`migrate`, `flush-tokens`) |
| `JWT_ACCESS_TOKEN_MINUTES` | `15` | |
| `JWT_REFRESH_TOKEN_DAYS` | `7` | |
| `DJANGO_SECURE_HTTPS` | `0` | редирект на HTTPS, secure-cookies, HSTS |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | `0` | доверять `X-Forwarded-Proto` от прокси |
| `DJANGO_SECURE_HSTS_SECONDS` | `31536000` | |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_SECURE_HSTS_PRELOAD` | `0` | решение владельца домена |
| `NUM_PROXIES` | `0` | прокси перед приложением; клиент — последний адрес `X-Forwarded-For` |
| `THROTTLE_ANON_RATE`, `THROTTLE_USER_RATE` | `100/hour`, `1000/hour` | |
| `THROTTLE_AUTH_RATE` | `10/min` | |
| `THROTTLE_AUTH_ACCOUNT_IP_RATE`, `THROTTLE_AUTH_ACCOUNT_RATE` | `10/hour`, `100/hour` | |
| `SENTRY_DSN` | пусто: Sentry выключен | |
| `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE` | `production`, `0` | |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | `min(2·CPU+1, 4)`, `4` | |

## Деплой

### Первый запуск

```bash
cp .env.example .env
# DJANGO_SECRET_KEY, POSTGRES_PASSWORD; DOMAIN=tasks.example.com, CADDY_TLS=acme
docker compose up -d --build --wait
deploy/smoke.sh tasks.example.com
```

Домен указывает на хост, порты 80 и 443 открыты. Порядок старта: `db`, `redis` →
`migrate` (код 0) → `web` (healthy) → `caddy`.

### Обновление

```bash
git pull
docker compose build
docker compose up -d --wait
docker compose run --rm migrate python manage.py reconcile_comments_count
```

`up --wait` возвращается, когда все реплики `web` заменены. После этого
`reconcile_comments_count` досчитывает комментарии, которые успел добавить код без
счётчика. Команда идёт пачками по 1000 задач, каждая — короткая транзакция, записывает
только расходящиеся счётчики и печатает их число. Безопасна на живой базе; на 200 тыс.
задач — около 2 с.

### Остановка

`docker compose down` без `-v`: в томах `caddy_data` сертификаты и ACME-аккаунт,
в `postgres_data` — данные. Let's Encrypt выпускает не больше 5 одинаковых сертификатов в
неделю.

## Миграции

Миграции совместимы со старым кодом (новые колонки — с `db_default`), поэтому старые
реплики работают, пока `migrate` меняет схему. Индексы на существующих таблицах строятся и
удаляются `CONCURRENTLY`, заполнение новых колонок идёт короткими пачками; такие миграции
неатомарны (`atomic = False`) и повторяемы. Если `migrate` упал — исправить причину и
запустить снова (`docker compose up -d --wait`). `migrate --fake` не применять: пропущенное
заполнение никто не доделает. `migrate` работает без `statement_timeout`.

## TLS

При `CADDY_TLS=acme` Caddy сам получает и продлевает сертификат, при `internal` выпускает
его своим CA (`curl --insecure`). HTTP → HTTPS (308) делает Caddy. При ошибках выпуска
(`rateLimited` в `docker compose logs caddy`) временно переключиться на `internal`.

## Токены

Каждый выданный refresh-токен — строка в `token_blacklist_outstandingtoken`. Сервис
`flush-tokens` удаляет истёкшие при старте и раз в сутки. После успешной чистки он
обновляет `/tmp/flushed`; если файлу больше 25 часов, сервис `unhealthy`. Запуск дольше
часа прерывается, после ошибки сервис ждёт 5 минут и перезапускается. Healthcheck
использует `start_interval` (Docker Engine 25+).

## Наблюдаемость

- **Логи** — JSON в stdout: `level`, `logger`, `message`, `request_id`. Access-лог
  gunicorn: `method`, `path`, `status`, `duration_ms`, `forwarded_for` (IP клиента),
  `request_id`. Docker ротирует логи: 5 файлов по 20 МБ.
- **Request ID** берётся из `X-Request-ID`, если он из `[A-Za-z0-9._-]{1,64}`, иначе
  генерируется; возвращается в ответе и попадает в логи и Sentry.
- **Метрики** — `GET /metrics` (django-prometheus) только для адресов частных сетей:
  `http://web:8000/metrics` с `Host` из `ALLOWED_HOSTS`, при `--scale` — каждая реплика.
- **Health-check**: `/api/health/live/` — процесс жив (healthcheck образа);
  `/api/health/` — `200 ok`, `200 degraded` без Redis, `503 error` без БД. Оба без
  аутентификации, троттлинга и редиректа на HTTPS.

## Без Redis

Общие лимиты пропускают запросы, лимиты входа считаются в памяти каждого процесса, в лог
пишется `WARNING core.throttling`, readiness отвечает `degraded`. Лимит входа при этом
умножается на число процессов: `rate × GUNICORN_WORKERS × реплики`, по умолчанию до
`40·N` попыток в минуту с IP и до `400·N` в час на аккаунт при `N` репликах.

## Массовые удаления

Удаление комментариев в админке — один запрос, но админка загружает выбранные объекты, а
запрос ограничен `statement_timeout`. Крупные чистки — из одноразового контейнера без
таймаута:

```bash
docker compose run --rm migrate python manage.py shell -c \
    "from apps.tasks.models import Comment; print(Comment.objects.filter(author__username='spammer').delete())"
```

## Зависимости

Прямые зависимости — `requirements.in` и `requirements-dev.in`, lock-файлы с хешами:

```bash
pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file=requirements.txt requirements.in
pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file=requirements-dev.txt requirements-dev.in
```

## Runbook

| Симптом | Что смотреть | Что делать |
|---|---|---|
| readiness `degraded`, `WARNING core.throttling` | `docker compose ps redis`, `logs redis` | `docker compose restart redis` |
| readiness `503` | `docker compose ps db`, `logs db`, диск | поднять БД; `web` перезапускать не нужно |
| `502`/`503` от Caddy | `docker compose ps web`, `logs web` | `docker compose up -d --wait` |
| рост 5xx | `logs web` по `request_id`, Sentry | |
| `WARNING Account throttled` | поле `account` — sha256 имени: `printf %s alice \| sha256sum`; `forwarded_for` в access-логе | закрыть адреса в Caddy или файрволе |
| `canceling statement due to statement timeout` | запрос в логе, `EXPLAIN ANALYZE` | индекс или ограничение запроса |
| сертификат не выпускается | `logs caddy` | DNS, порты 80/443, том `caddy_data`; временно `CADDY_TLS=internal` |
| `migrate` упал, `web` не стартует | `logs migrate` | исправить причину, `docker compose up -d --wait` |
| `comments_count` не совпадает с числом комментариев | `SELECT count(*) FROM tasks_comment WHERE task_id = …` | `reconcile_comments_count` |
| растёт `token_blacklist_outstandingtoken` | `docker compose ps flush-tokens`, `logs flush-tokens` | `docker compose restart flush-tokens` |
| смена `DJANGO_SECRET_KEY` | | все JWT станут недействительны: менять в окно обслуживания |
