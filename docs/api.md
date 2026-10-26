# Описание API

Интерактивная спецификация: **http://localhost:8000/docs** (Swagger UI) и `/openapi.json`. Статическая копия — `docs/openapi.json` (обновляется командой `make openapi`). Коллекция запросов — [postman_collection.json](postman_collection.json): импортируйте её в Postman или Bruno и запустите папки по порядку; токены сохраняются в переменные коллекции автоматически.

## Общие правила

Аутентификация — заголовок `Authorization: Bearer <token>`, токен выдаёт `POST /api/auth/login`. Суммы — целые рубли. Даты — ISO 8601 в UTC.

Ошибки возвращаются в едином формате `application/problem+json`:

```json
{"code": "validation_failed", "message": "Проверьте поля заявки",
 "details": [{"field": "amount", "code": "out_of_range", "message": "Сумма по продукту «Экспресс-кредит» — от 100 000 ₽ до 5 000 000 ₽"}],
 "request_id": "6f1c2a9b0d3e4f51"}
```

| HTTP | code | Когда |
|---|---|---|
| 401 | `unauthorized` | Нет токена, токен истёк или неверный |
| 403 | `forbidden` | Роль не позволяет действие |
| 404 | `not_found` | Нет объекта или он принадлежит другой компании |
| 409 | `invalid_transition` | Действие не предусмотрено текущим статусом |
| 409 | `version_mismatch` | Заявку одновременно изменили (оптимистическая блокировка) |
| 409 | `already_assigned` | Заявку ведёт другой аналитик |
| 422 | `validation_failed` | Ошибки полей, в `details` — по каждому полю |

`Idempotency-Key` в `POST /api/applications` гарантирует, что повтор запроса (двойной клик, ретрай сети) не создаст вторую заявку. Повторная отправка `submit` тоже безопасна. Каждый ответ содержит `X-Request-ID` для поиска в логах.

## Эндпоинты

| Метод и путь | Роль | Назначение |
|---|---|---|
| `POST /api/auth/login` | — | Вход, выдаёт JWT и профиль |
| `POST /api/auth/register` | — | Регистрация клиента по ИНН: реквизиты из ЕГРЮЛ/ЕГРИП, сразу выдаёт JWT. 409 — email и/или компания уже зарегистрированы (все такие ошибки — в одном ответе), 422 — неверный формат полей или компании нет в реестре, 503 — реестр недоступен |
| `GET /api/auth/me` | любая | Текущий пользователь и компания |
| `GET /api/catalog` | — | Продукты, цели финансирования, типы документов |
| `POST /api/calculator` | — | Предварительный платёж по минимальной ставке |
| `POST /api/assistant/suggest` | любая | Подбор продукта по цели или свободному тексту |
| `GET /api/assistant/status` | любая | Доступна ли языковая модель |
| `GET /api/applications` | клиент | Заявки компании |
| `POST /api/applications` | клиент | Создать черновик |
| `GET /api/applications/{id}` | клиент | Карточка: статус простым языком, доступные действия, предложение, объяснение решения |
| `PATCH /api/applications/{id}` | клиент | Изменить черновик (`version` — для оптимистической блокировки) |
| `POST /api/applications/{id}/submit` | клиент | Отправить в банк |
| `POST /api/applications/{id}/documents` | клиент | Загрузить документ (multipart: `doc_type`, `file`) |
| `GET /api/applications/{id}/documents/{doc_id}` | клиент | Скачать документ |
| `DELETE /api/applications/{id}/documents/{doc_id}` | клиент | Удалить ошибочно загруженный документ: только в черновике и при дозапросе (иначе 409). Запись об удалении остаётся в журнале |
| `POST /api/applications/{id}/info-response` | клиент | Ответить на дозапрос, заявка возвращается в конвейер |
| `POST /api/applications/{id}/accept` | клиент | Принять предложение, формируется договор |
| `POST /api/applications/{id}/sign` | клиент | Подписать (`confirmation_inn`, `agree: true`), запускается выдача |
| `POST /api/applications/{id}/cancel` | клиент | Отменить |
| `GET /api/applications/{id}/events?after_id=` | клиент | История заявки (без внутренних событий) |
| `GET /api/feed` | клиент | Блок «Ваши заявки и предложения»: действия, события, персональные предложения, советы по заявке |
| `GET /api/analyst/queue?scope=manual\|active\|all` | аналитик, риск | Очередь заявок |
| `GET /api/analyst/applications/{id}` | аналитик, риск | Полная карточка: данные источников, скоринг, лимиты, рекомендация, журнал |
| `POST /api/analyst/applications/{id}/assign` | аналитик | Взять в работу |
| `POST /api/analyst/applications/{id}/decision` | аналитик | Решение: `APPROVED` / `COUNTER_OFFER` / `REJECTED` + комментарий для клиента |
| `POST /api/analyst/applications/{id}/request-info` | аналитик | Запросить документы у клиента |
| `GET /api/analyst/stats` | аналитик, риск | Показатели конвейера, доля автоматических решений |
| `GET /api/admin/audit` | аналитик, риск | Журнал событий с номером заявки, компанией и исполнителем; `hidden_only=true` — только внутренние события |
| `GET /api/admin/jobs` | аналитик, риск | Состояние очереди, упавшие задачи |
| `GET /api/admin/policy` | аналитик, риск | Действующая политика, скоринговая карта, продукты, отраслевой риск, диаграмма состояний |
| `GET\|POST /api/admin/integrations/chaos` | аналитик, риск | Симуляция сбоев внешних источников |
| `GET /health/live`, `/health/ready` | — | Проверки живости и готовности |

## Контракты внешних источников (симулятор)

| Источник | Метод | Что возвращает |
|---|---|---|
| ЕГРЮЛ/ЕГРИП | `GET /egrul/{inn}` | статус (`ACTIVE`, `LIQUIDATING`, `BANKRUPT`), дата регистрации, ОГРН, ОКВЭД, руководитель и признак дисквалификации, учредители, адрес |
| ФНС «Прозрачный бизнес» | `GET /fns/transparent-business/{inn}` | выручка по годам, недоимка, адрес массовой регистрации, численность, налоговый режим |
| БКИ | `GET /bki/{inn}/report` | обязательства: остаток, платёж, максимальная просрочка за 12 мес., текущая просрочка; число запросов за 30 дней |

Некорректный ИНН → 404. Для корректного ИНН вне демо-набора данные генерируются детерминированно. `POST /_admin/chaos {"fail_rate": 0..1, "latency_ms": N}` включает сбои.

## Пример: заявка от черновика до решения

```bash
TOKEN=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"bakery@demo.ru","password":"demo12345"}' | jq -r .access_token)
APP=$(curl -s localhost:8000/api/applications -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H "Idempotency-Key: $(uuidgen)" \
  -d '{"product_code":"WORKING_CAPITAL","purpose":"inventory","amount":3000000,"term_months":24,
       "revenue_last_year":48000000,"revenue_prev_year":41000000,"monthly_debt_payments":80000}' | jq -r .id)
curl -s -X POST localhost:8000/api/applications/$APP/submit -H "Authorization: Bearer $TOKEN" | jq .status
sleep 8
curl -s localhost:8000/api/applications/$APP -H "Authorization: Bearer $TOKEN" | jq '{status: .status.title, offer, decision}'
```