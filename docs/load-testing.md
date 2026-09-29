# Нагрузочное тестирование

## Данные

На стенде, один раз:

```bash
docker compose run --rm migrate python manage.py seed_bulk \
    --tasks 1000000 --users 1000 --password "$LOAD_PASSWORD" --seed 42
```

Пользователи `load00000…load00999` с паролем `$LOAD_PASSWORD`, задачи с комментариями и
согласованным `comments_count`. Контейнер `migrate` работает без `statement_timeout`.

Все запросы теста идут с одного IP, поэтому на время теста лимиты поднимаются в `.env`
(и применяются `docker compose up -d --wait`), после — возвращаются:

```
THROTTLE_ANON_RATE=100000/hour
THROTTLE_USER_RATE=1000000/hour
THROTTLE_AUTH_RATE=1000/min
THROTTLE_AUTH_ACCOUNT_IP_RATE=1000/hour
THROTTLE_AUTH_ACCOUNT_RATE=1000/hour
```

## Запуск

```bash
k6 run -e BASE_URL=https://$DOMAIN -e PASSWORD="$LOAD_PASSWORD" \
    -e USERS=50 -e RATE=50 -e DURATION=2m \
    loadtest/tasks.js | tee loadtest/results/$(date +%F)-rate50.txt
```

`loadtest/tasks.js` держит постоянную интенсивность `RATE` итераций в секунду: 60 % —
первая страница списка, следующая по курсору и одна задача; 25 % — создание задачи и
`complete`; 15 % — комментарий к одной из новых задач. Пороги: ошибок меньше 1 %, p95
списка, создания, `complete` и комментария меньше 500 мс, задачи — меньше 300 мс.
`DURATION` должна быть меньше жизни access-токена (15 минут). Прочие параметры:
`USER_PREFIX`, `INSECURE=1` для `CADDY_TLS=internal`, `HOST_IP` — адрес вместо DNS.

## Результаты

Стенд: 2 vCPU, 1,9 ГБ RAM, compose на одном хосте с одной репликой `web`, 1 млн задач и
761 тыс. комментариев, HTTPS через Caddy, по 2 минуты на ступень. k6 запущен на том же
хосте и занимал 8–24 % CPU, поэтому цифры — нижняя оценка. Сводки k6 —
`loadtest/results/2026-09-29-staging-rate*.txt`.

| Итераций/с | Запросов/с | p50 | p95 | p99 | Ошибок |
|---|---|---|---|---|---|
| 25 | 57 | 15–20 мс | 37–62 мс | 110–430 мс | 0 из 7 802 |
| 50 | 72 | 3,6–4,2 с | 11 с | 13 с | 4 из 10 787 |
| 100 | 66 | 9,8–11 с | 25 с | 26 с | 5 из 10 788 |

Задержки — разброс по типам запросов. Потолок одной реплики — около 70 запросов/с, дальше
растёт очередь. Упирается `web` (130–155 % из 200 % CPU), а не база: PostgreSQL занят на
15–24 %, Caddy — около 10 %. Пропускная способность растёт репликами `web` и ядрами, см.
[architecture.md](architecture.md#масштабирование).
