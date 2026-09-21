# Архитектура проекта «Учебный тренажер 112»

**Версия:** 0.3  
**Статус:** WORKING BASELINE  
**Дата:** 21.09.2026

## Архитектурный стиль

Модульный монолит.

```text
React
  │ REST + Socket.IO
  ▼
FastAPI
  ├── identity
  ├── organizations
  ├── training
  ├── incidents
  ├── response
  ├── assessment
  ├── virtual112
  ├── realtime
  └── integrations
        │
        ▼
    PostgreSQL
```

## Стек

Backend:

- Python 3.12+;
- FastAPI;
- Pydantic / pydantic-settings;
- SQLAlchemy 2;
- Alembic;
- PostgreSQL;
- python-socketio;
- pytest / pytest-asyncio;
- Ruff.

Frontend:

- JavaScript;
- React + Vite;
- React Router;
- MUI + CSS Modules;
- TanStack Query;
- React Hook Form;
- Zod для сложных форм;
- socket.io-client;
- Playwright.

## Основные модули

### incidents

Учебные карточки, статусы ДДС, комментарии, `available_actions`, история действий.

### response

Виртуальные группы реагирования и их назначения.

Предварительные сущности:

```text
ResponseUnit
ResponseAssignment
ResponseMessage
```

`ResponseUnit` описывает идентичность виртуальной группы. Runtime-состояние конкретного выезда хранится в `ResponseAssignment` и не является статусом карточки.

### virtual112

Имитация внешней для ДДС части Системы-112:

- формирование готовой учебной карточки;
- доставка карточки;
- имитация внешних изменений и других служб;
- позднее — маршрутизация через классификатор/территорию/подчинённость.

### training

`TrainingSession`, `TrainingRun`, `TrainingScenario`, `TrainingScenarioEvent`.

## Почему TrainingScenario, а не Scenario

В исходной системе термин «сценарий реагирования» уже используется как техническое понятие. Чтобы избежать неоднозначности, учебные сценарии продукта именуются `TrainingScenario`.

## Двойное состояние реагирования

Ключевое архитектурное правило:

```text
ResponseAssignment state Incident/DDS status
------------------      -------------------
EN_ROUTE                может всё ещё быть ACCEPTED
ARRIVED                 обучаемый должен сам выбрать ARRIVAL
WORKING                 обучаемый должен сам выбрать WORK_IN_PROGRESS
COMPLETED               обучаемый должен сам завершить карточку
```

Изменение состояния `ResponseAssignment` создаёт сообщение/событие, но не выполняет доменную команду от имени обучаемого.

## Чат виртуальной группы

Первый MVP использует текстовый realtime-канал, который имитирует телефонную коммуникацию.

Сообщения хранятся в БД и доставляются через Socket.IO.

```text
ResponseMessage
- id
- response_assignment_id
- sender_type: DISPATCHER | RESPONSE_UNIT | SYSTEM
- body
- created_at
```

REST остаётся каноническим источником истории. Socket.IO только уведомляет о новом сообщении.

## Поведение виртуальной группы

Первый вариант — детерминированный движок на основе `TrainingScenarioEvent`.

Пример:

```text
+00:20 ACKNOWLEDGED
+01:00 EN_ROUTE
+04:00 ARRIVED
+05:00 WORKING
+10:00 COMPLETED
```

Событие может:

- изменить состояние `ResponseAssignment`;
- создать сообщение от старшего группы;
- ожидать инициативного запроса обучаемого;
- добавить осложнение.

AI не нужен для первого vertical slice.

## Маршрутизация

Будущий `RoutingEngine` должен позволять учитывать:

```text
classification
+
service area
+
object affiliation
→ notification targets
```

Не реализовывать полный routing до отдельной задачи. Первый MVP может использовать заранее подготовленный список оповещения в `TrainingScenario`.

## Workflow карточки

Backend — единственный источник правил.

Предполагаемое расположение:

```text
backend/app/modules/incidents/workflow.py
```

Ответ API включает `available_actions`.

Точная универсальная state machine не должна зашиваться в frontend.

## История действий

`IncidentAction` хранит минимум:

```text
CARD_OPENED
PRIMARY_STATUS_CHANGED
COMMENT_ADDED
RESPONSE_UNIT_ASSIGNED
RESPONSE_TASK_SENT
RESPONSE_MESSAGE_READ
STATUS_CHANGED
CARD_COMPLETED
```

Оценивание строится на хронологии действий и событий.

## REST и realtime

REST:

- текущее состояние;
- команды пользователя;
- восстановление после reconnect;
- история сообщений и действий.

Socket.IO:

```text
incident.delivered
incident.updated
response.message_created
response.state_changed
session.started
session.finished
assessment.completed
```

После reconnect frontend обязательно повторно запрашивает server state.

## Время

Backend/PostgreSQL — UTC. API — ISO 8601.

Для карточки отдельно хранить:

```text
delivered_at
opened_at
primary_status_at
```

Для ResponseUnit и сообщений — серверные временные метки.

## Оценивание

Детерминированная часть сравнивает фактический мир сценария с действиями обучаемого.

Пример:

```text
ResponseUnit EN_ROUTE at 14:04:00
Trainee set START_RESPONSE at 14:04:18
reaction_delay = 18 seconds
```

Это позволяет оценивать несвоевременные и неправильные действия без AI.

## Интеграции

```text
AIProvider
TelephonyProvider
ClassifierImporter
```

Чат не должен быть жёстко связан с телефонией. Позднее `TelephonyProvider` сможет заменить или дополнить учебный канал без переделки `ResponseAssignment` и `ResponseUnit`.

## Локальная разработка

До первого полного Compose:

```text
PostgreSQL → Docker
Backend → local hot reload
Frontend → Vite dev server
```

Контрольный воспроизводимый запуск позднее:

```text
docker compose up --build
```

## Непрерывность разработки

Состояние проекта хранится в Git:

- долговременные знания — `docs/`;
- состояние `main` — `docs/current-state.md`;
- состояние активной ветки — `tasks/UT112-xxx.md`;
- правила агента — `AGENTS.md`;
- воспроизводимые workflows — `.agents/skills/`;
- project-level Codex config — `.codex/config.toml`.

Чат агента не является источником истины.

## Не добавлять без отдельного решения

- микросервисы;
- Redis;
- Kafka/RabbitMQ;
- Celery;
- Kubernetes;
- обязательный cloud AI;
- полноценную SIP-инфраструктуру;
- отдельный workflow для каждой реальной ДДС в первом MVP.
