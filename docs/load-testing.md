# Нагрузочное тестирование

## Данные

На стенде, один раз:

```bash
docker compose run --rm migrate python manage.py seed_bulk \
    --tasks 1000000 --users 1000 --password "$LOAD_PASSWORD" --seed 42
```

Пользователи `load00000…load00999` с паролем `$LOAD_PASSWORD`, задачи с комментариями и
согласованным `comments_count`.

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

На хосте стенда, k6 в контейнере:

```bash
docker run --rm --network host -v "$PWD/loadtest:/lt" grafana/k6 run \
    -e BASE_URL=https://$DOMAIN -e PASSWORD="$LOAD_PASSWORD" \
    -e USERS=50 -e RATE=50 -e DURATION=2m \
    /lt/tasks.js | tee loadtest/results/$(date +%F)-staging-rate50.txt
```

С внешней машины — `k6 run` с теми же `-e` и `loadtest/tasks.js`.

`loadtest/tasks.js` держит постоянную интенсивность `RATE` итераций в секунду: 60 % —
первая страница списка, следующая по курсору и одна задача; 25 % — создание задачи и
`complete`; 15 % — комментарий к одной из новых задач. Пороги: ошибок меньше 1 %, p95
списка, создания, `complete` и комментария меньше 500 мс, задачи — меньше 300 мс.
`DURATION` должна быть меньше жизни access-токена (15 минут). Прочие параметры:
`USER_PREFIX`, `INSECURE=1` для `CADDY_TLS=internal`, `HOST_IP` — адрес вместо DNS.

## Результаты

Стенд: compose на одном хосте с одной репликой `web`, 1 млн задач и 761 тыс. комментариев,
HTTPS через Caddy, k6 на том же хосте, по 2 минуты на ступень. Сводки k6 —
`loadtest/results/2026-09-29-staging-rate*.txt`.

| Цель, итераций/с | Выполнено / отброшено | Запросов/с | p50 | p95 | p99 | Ошибок |
|---|---|---|---|---|---|---|
| 25 | 3 001 / 0 | 57 | 14–20 мс | 37–62 мс | 110–430 мс | 0 из 7 802 |
| 50 | 4 131 / 1 870 | 72 | 3,6–4,2 с | 11 с | 13 с | 4 из 10 787 |
| 100 | 4 110 / 7 891 | 66 | 9,8–11 с | 25 с | 26 с | 5 из 10 788 |

Задержки — разброс по типам запросов. При 50 и 100 k6 упёрся в `maxVUs` и отбрасывал
итерации. Потолок одной реплики — около 70 запросов/с, дальше растёт очередь.

По `docker stats` во время прогона (в результатах не сохранено): хост — 2 vCPU и 1,9 ГБ
RAM; `web` — 130–155 % из 200 % CPU, PostgreSQL — 15–24 %, Caddy — около 10 %, k6 —
8–24 %. Упирается `web`, а не база; k6 делит с ним CPU, поэтому цифры — нижняя оценка.
Как масштабировать — [architecture.md](architecture.md#масштабирование).
