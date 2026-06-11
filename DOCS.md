# Marshrutka — архитектура и эксплуатация

> Personal-use orchestration cockpit для контентных pipeline-проектов.
> Дата: 2026-06-10 | Версия: 0.8 (YouTube Publishing)

---

## 1. Что такое Marshrutka

Marshrutka — это внутренний personal-use control panel для запуска и мониторинга контентных pipeline-проектов.

**Не является:**
- публичным SaaS-продуктом
- multi-tenant платформой
- no-code системой для внешних пользователей

**Является:**
- config-first orchestration tool
- agent-friendly системой (настройка через JSON/агентами, UI — тонкая оболочка)
- control panel для одного оператора/владельца
- включает встроенного AI-агента Маршал для работы с проектами, текстами и поиском информации

---

## 2. Source of truth

| Сущность | Source of truth | Хранилище |
|---|---|---|
| Проекты | `projects/*.json` | JSON-файлы в проектной директории |
| Подключенные pipeline-запуски | **Сервер проекта** (external API) | Удалённый `GET /jobs/<id>` |
| Локальные launch-записи Marshrutka | `data/runs.json` | JSON-файл |
| Статус выполнения pipeline | **Сервер проекта** (remote job status) | Получается через `GET /jobs/<id>` |
| Queue items | `data/queues/<project_id>.json` | Per-project JSON-файлы |
| Scheduling | `data/schedules.json` | JSON-файл + APScheduler |
| Профили публикации | `data/publish_profiles.json` | JSON-файл |
| Запросы на публикацию | `data/publish_requests.json` | JSON-файл |
| User profile (имя, preferences) | `data/agent/user_profile.json` | JSON-файл |
| User facts (долгая память) | `data/agent/user_facts.json` | JSON-файл |
| Project knowledge (долгая память) | `data/agent/project_memory.json` | JSON-файл |
| Decisions log | `data/agent/decisions_log.jsonl` | JSONL-файл |
| Research cache | `data/agent/research_cache.json` | JSON-файл |
| Agent auto-tasks | `data/agent/agent_jobs.json` | JSON-файл |
| Frontend state backup | `data/agent/states/<id>.json` | JSON-файл |
| Session chat history | `data/agent/sessions/<session_id>.json` | Per-session JSON-файл |
| Content Memory (dedupe) | `data/content_memory.json` | JSON-файл (FileStore[ContentRecord]) |

**Canonical execution ID для pipeline — это server job id проекта**, а не локальный launch id Marshrutka.

---

## 3. Модель данных

### 3.1. Проект (`Project`)

Обязательные поля: `project_id`, `display_name`.
Опциональные: `description`, `input_fields`, `jobs`, `integration`, `publish_bindings`, `config`, `defaults`, `primary_artifact`.

Проекты хранятся в `projects/<project_id>.json`.

```json
{
  "project_id": "story-to-video",
  "display_name": "Story to Video",
  "description": "...",
  "integration": {
    "api_url": "http://141.136.44.9:8001",
    "jobs_list_endpoint": "/jobs",
    "job_detail_endpoint": "/jobs/{job_id}",
    "artifacts_endpoint": "/jobs/{job_id}/artifacts/{key}",
    "auto_sync": true
  },
  "publish_bindings": [
    { "profile_id": "pub_abc", "enabled": true, "is_default": true }
  ],
  "defaults": {
    "input_values": {},
    "publish_profile_id": "",
    "queue_title_template": ""
  },
  "primary_artifact": {
    "artifact_key": "final_video",
    "label": "Финальное видео",
    "expected_extension": "mp4"
  }
}
```

Новые поля в версии 0.5:
- `defaults` (`ProjectDefaults`) — значения по умолчанию для input полей, профиль публикации, шаблон названия элемента очереди
- `primary_artifact` (`PrimaryArtifactConfig`) — конфигурация главного финального артефакта

Поле `ProjectInputField` расширено:
- `helper_text` — подсказка под полем в форме
- `visible` — если `false`, поле не отображается в quick launch / add to queue форме. Не равноценно удалению: поле продолжает существовать в config и может участвовать в defaults/payload. Задаётся через чекбокс «показывать в форме»
- `supports_default` — если `true`, для поля можно задать project-level default в `ProjectDefaults.input_values`. В UI называется «проектное значение по умолч.»
- `deprecated` — поле устарело (визуально затемняется в редакторе)

**Важно:** флаг `visible` реально влияет на рендер формы. Если `visible = false`, поле не показывается в quick launch / add to queue UI, но его значение может быть передано через defaults или явно в queue item payload.

### 3.2. QueueItem — first-class сущность

Очередь проекта — это набор подготовленных к запуску launch items.

**Хранилище:** `data/queues/<project_id>.json` (per-project файлы).

Поля:

| Поле | Тип | Описание |
|---|---|---|
| `queue_item_id` | str | Префикс `q_` |
| `project_id` | str | Ссылка на проект |
| `title` | str | Человекочитаемое название |
| `payload` | dict | Входные данные для запуска |
| `status` | QueueItemStatus | draft / queued / launching / launched / failed / paused / archived |
| `position` | int | Порядок в очереди |
| `source` | QueueItemSource | manual / agent / api / imported |
| `notes` | str | Произвольные заметки |
| `labels` | list[str] | Метки/теги |
| `default_publish_profile_id` | str | Профиль публикации по умолчанию |
| `publish_artifact_key_override` | str | Переопределение primary artifact для этого item |
| `created_at` | datetime | Время создания |
| `updated_at` | datetime | Время последнего обновления |
| `last_launch_at` | datetime | Время последнего запуска |
| `last_run_id` | str | ID последнего Run |
| `last_remote_job_id` | str | ID последнего remote job |
| `last_error` | str | Текст последней ошибки |
| `launch_history` | list[dict] | История запусков (run_id, remote_job_id, launched_at, remote_status, trigger) |

Статусы QueueItem:

| Статус | Описание |
|---|---|
| `draft` | Черновик, не готов к запуску |
| `queued` | В очереди, готов к запуску |
| `launching` | Запускается (идет отправка) |
| `launched` | Успешно запущен |
| `failed` | Ошибка при запуске |
| `paused` | Приостановлен (временно исключён) |
| `archived` | В архиве |

### 3.3. PrimaryArtifactConfig

Конфигурация главного финального артефакта проекта.

```python
class PrimaryArtifactConfig(BaseModel):
    artifact_key: str = "final_video"     # ключ артефакта на сервере
    label: str = "Финальное видео"         # человекочитаемое название
    expected_extension: str = "mp4"        # ожидаемое расширение
```

**Где задаётся:** в `projects/<project_id>.json` → `primary_artifact`.

**Как резолвится на уровне run:**
1. Берётся `primary_artifact_key` из конфигурации проекта
2. Если queue item имеет `publish_artifact_key_override` — используется он
3. Проверяется наличие артефакта с этим ключом в `RemoteJobDetails.artifacts`
4. Если найден — помечается как `is_primary = true`
5. Если не найден и есть ровно один video artifact — fallback с пометкой
6. Если fallback неочевиден — primary artifact считается неопределённым

**Использование в publish:** PublishRequest по умолчанию ссылается на primary artifact.
Publish adapters в будущем будут получать уже resolved artifact reference.

### 3.4. ProjectDefaults

```python
class ProjectDefaults(BaseModel):
    input_values: dict[str, Any] = {}        # значения по умолчанию для полей
    publish_profile_id: str = ""             # профиль публикации по умолчанию
    queue_title_template: str = ""           # шаблон названия элемента очереди
    last_used_values: dict[str, Any] = {}    # последние использованные значения
```

**Приоритет значений:**
1. explicit queue item payload
2. значения из текущей формы
3. project defaults (`input_values`)
4. field default / empty

### 3.5. Интеграция (`ProjectIntegration`)

Конфигурация endpoint-ов сервера проекта:
- `api_url` — базовый URL сервера
- `jobs_list_endpoint` — `GET {api_url}{endpoint}` → список jobs
- `job_detail_endpoint` — `GET {api_url}{endpoint}` с `{job_id}` → детали job
- `artifacts_endpoint` — `GET {api_url}{endpoint}` с `{job_id}` и `{key}` → скачивание артефакта
- `job_cancel_endpoint` — `POST {api_url}{endpoint}` с `{job_id}` → отмена job
- `auto_sync` — автоматическая синхронизация после запуска

### 3.6. Локальный запуск (`Run`)

Префикс ID: `launch_`.

Новое поле: `queue_item_id` — ссылка на QueueItem, если запуск был из очереди.

Поля:
- `run_id` — локальный launch ID (Marshrutka)
- `project_id` — ссылка на проект
- `queue_item_id` — ссылка на QueueItem (опционально)
- `orchestration_status` — статус оркестрации Marshrutka
- `remote_status` — статус выполнения на сервере проекта
- `remote_job_id` — canonical execution ID
- `input` — снимок входных данных
- `submit_response` — ответ сервера на POST /jobs
- `last_sync_at`, `sync_error` — статус синхронизации

### 3.7. Удалённый job (`RemoteJobRef`, `RemoteJobDetails`)

Кэшированные данные с сервера проекта:
- `external_job_id` — ID job на сервере
- `remote_status` — строка статуса от сервера
- `steps`, `artifacts`, `metadata`, `logs`, `warnings`
- `job_response` — полный raw JSON ответ сервера
- `last_synced_at` — время последней синхронизации

### 3.8. Профиль публикации (`PublishProfile`)

Префикс ID: `pub_`.

- `display_name` — название профиля
- `platform` — youtube / instagram / vk_video / rutube
- `credentials` — JSON с учётными данными
- `channel_title`, `channel_id` — данные канала
- `privacy_defaults`, `title_defaults`, `description_defaults`, `tags_defaults`, `shorts_defaults` — настройки по умолчанию
- `is_ready` — признак готовности профиля

### 3.9. Запрос на публикацию (`PublishRequest`)

Префикс ID: `pubreq_`.
Связывает `run_id`, `profile_id`, `platform` с конкретным запросом публикации.

### 3.10. Расписание (`Schedule`)

Префикс ID: `sched_`.
Cron-выражение + `project_id`.

**Изменения в версии 0.5:** у Schedule больше нет поля `input`.
Расписания больше не запускают фиксированный payload напрямую.
Они запускают первый элемент из очереди проекта.

---

## 4. Как работает запуск проекта

### 4.1. Ручной запуск (Launch now)

1. Пользователь заполняет форму на странице проекта
2. Выбирает действие «Запустить сейчас»
3. Marshrutka создаёт `Run` со статусом `orchestration_status = submitting`
4. Отправляет `POST {api_url}{run_endpoint}` с input-данными
5. Если сервер вернул `job_id`:
   - `orchestration_status → linked`, `remote_job_id` сохраняется
6. Если сервер не вернул `job_id`: `orchestration_status → detached`
7. Если сетевая ошибка: `orchestration_status → sync_error`
8. Выполняется `fetch_remote_jobs` для обновления списка

### 4.2. Добавление в очередь (Add to queue)

1. Пользователь заполняет форму
2. Выбирает «+ В очередь»
3. Создаётся `QueueItem` со статусом `queued`
4. Payload сохраняется в item
5. Пользователь перенаправляется на страницу проекта

### 4.3. Сохранение черновика (Save draft)

1. Пользователь заполняет форму
2. Выбирает «Черновик»
3. Создаётся `QueueItem` со статусом `draft`
4. Payload сохраняется в item
5. Пользователь перенаправляется на страницу проекта

### 4.4. Запуск из очереди (Launch queue item)

1. Пользователь нажимает ▶ на элементе очереди
2. Item → `launching`
3. Создаётся Run через `run_project()` с указанием `queue_item_id`
4. После успеха: item → `launched`, сохраняются `last_run_id`, `last_remote_job_id`
5. История запуска добавляется в `launch_history`
6. При ошибке: item → `failed` с `last_error`

### 4.5. Статусы оркестрации

| Статус | Значение |
|---|---|
| `draft` | Черновик, запуск ещё не отправлен |
| `submitting` | Отправка запроса на сервер проекта |
| `linked` | Успешно связан с remote job |
| `sync_pending` | Ожидает синхронизации |
| `sync_error` | Ошибка при синхронизации с сервером |
| `detached` | Remote job больше не найден на сервере |
| `cancelled_locally` | Отменён локально |

---

## 5. Linkage: локальный launch ↔ remote job

### Принципы

1. **Server job id — canonical execution ID.** Все status/details/artifacts/cancel запросы идут по нему.
2. **Локальный launch id — служебный.** Используется для UI и локальной оркестрации.
3. **Два независимых статуса.** OrchestrationStatus показывает состояние Marshrutka, RemoteExecutionStatus — состояние на сервере.
4. **Ошибка оркестрации ≠ ошибка pipeline.** Marshrutka может упасть, а pipeline на сервере продолжит работу.

### Механизм синхронизации (`_link_local_runs`)

При каждом `fetch_remote_jobs()`:
1. Получаем список всех remote jobs с сервера
2. Для каждого локального `Run` с `remote_job_id`:
   - Если remote job найден → обновляем `remote_status`, очищаем `sync_error`
   - Если remote job не найден → `orchestration_status → detached`
3. Remote jobs без локальной привязки отображаются в списке как `source = remote`

---

## 6. Очереди проектов

### 6.1. Структура

Очереди хранятся в `data/queues/<project_id>.json`.
Это per-project JSON-файлы, легко читаемые и редактируемые человеком или агентом.

Внешний агент может:
- открыть JSON очереди
- понять item structure
- добавить item руками
- изменить статус / notes / payload
без необходимости лезть в сложную БД или миграционную систему

### 6.2. Queue Item Detail / Edit

С версии 0.5 (corrective) каждый queue item имеет отдельную страницу detail/edit.

**URL:** `/projects/{project_id}/queue/{queue_item_id}`

**На странице:**
- Summary: title, status, position, source, timestamps
- Payload: полный JSON payload с человекочитаемым preview
- Publish intent: primary artifact проекта, выбранный профиль публикации, override artifact key
- Launch history: таблица всех запусков с run_id, remote_job_id, временем, триггером
- Actions: сохранить изменения, запустить сейчас, вернуться к проекту

**Редактируемые поля:**
- title, status, notes
- payload (редактируется как JSON)
- default_publish_profile_id
- publish_artifact_key_override
- status (draft / queued / paused / archived)

### 6.3. Queue API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/projects/{id}/queue` | Получить очередь проекта |
| GET | `/api/projects/{id}/queue/summary` | Сводка по очереди |
| GET | `/api/projects/{id}/queue/{qiid}` | Получить queue item |
| POST | `/api/projects/{id}/queue` | Создать queue item |
| PUT | `/api/projects/{id}/queue/{qiid}` | Обновить queue item |
| POST | `/api/projects/{id}/queue/{qiid}/status` | Сменить статус |
| POST | `/api/projects/{id}/queue/{qiid}/launch` | Запустить item |
| DELETE | `/api/projects/{id}/queue/{qiid}` | Удалить item |
| POST | `/api/projects/{id}/queue/{qiid}/move` | Переместить item |
| POST | `/api/projects/{id}/queue/{qiid}/duplicate` | Дублировать item |

### 6.3. Queue-driven schedules

С версии 0.5 schedules больше не хранят `input` и не запускают фиксированный payload.

**Новая модель:**
1. Schedule привязан к проекту
2. При срабатывании schedule ищет первый `queued` item в очереди проекта
3. Сортировка по `position`
4. Если найден — запускает его (аналогично ручному launch)
5. Если очередь пуста — no-op (schedule остаётся healthy)
6. Если payload невалиден — item → `failed`, schedule не идёт дальше в той же итерации

**Политика обработки:**
1. Schedule trigger берёт первый `queued` item по `position`
2. Валидирует payload
3. Если payload валиден:
   - создаёт новый local run
   - делает submit
   - queue item → `launching`, затем `launched`
   - сохраняет `last_run_id`, `last_remote_job_id`, `last_launch_at`
4. Если payload невалиден:
   - queue item → `failed`
   - trigger не идёт дальше по очереди в ту же итерацию
   - пишет понятную причину ошибки
5. Если очередь пуста:
   - no-op log
   - schedule остаётся healthy

---

## 7. Синхронизация remote jobs

### `fetch_remote_jobs(integration, project_id)`

- GET `{api_url}{jobs_list_endpoint}`
- Парсит ответ
- Маппит в `RemoteJobSummary`
- Вызывает `_link_local_runs()` для обновления статусов локальных запусков
- Возвращает `SyncSnapshot`

### `sync_run_status(run, integration)`

- GET `{api_url}{job_detail_endpoint}` с `remote_job_id`
- Обновляет `run.remote_status`, `run.last_sync_at`
- Возвращает `RemoteJobRef`

### `fetch_remote_job_details(integration, project_id, remote_job_id)`

- GET деталей job
- Возвращает `RemoteJobDetails` (steps, progress, artifacts, logs, metadata)

---

## 8. Артефакты и Primary Artifact

### 8.1. Общая схема

Артефакты живут на сервере проекта и запрашиваются по remote job id.
Marshrutka проксирует их, но не хранит локально.

### 8.2. Primary / Final Artifact

С версии 0.5 у каждого проекта есть явно определённый **primary/final artifact**:

- **Где задаётся:** `projects/<project_id>.json` → `primary_artifact` → `artifact_key`
- **Что это:** ключ артефакта, который считается основным результатом pipeline
- **Зачем:** publish preparation знает, какой artifact основной, не угадывая по расширениям

**На уровне run:**
1. При загрузке `RemoteJobDetails` Marshrutka проверяет `artifacts` на наличие ключа
2. Если найден — помечается как `is_primary = true`
3. Артефакт визуально выделяется в UI (зелёный фон, badge ★ Primary)

**Fallback:**
- Если явно заданный key не найден и есть ровно один video artifact — он предлагается как fallback candidate с пометкой `fallback`
- Если fallback неочевиден — показывается, что primary artifact не определён

**На уровне queue item:**
- Можно задать `publish_artifact_key_override` для переопределения на конкретный запуск

### 8.3. Normalization artifact filename (приоритет):

1. Server value — если сервер проекта вернул filename в значении артефакта
2. Known mapping — `ARTIFACT_FILENAME_MAP` + `PROJECT_ARTIFACT_OVERRIDES`
3. Fallback — ключ артефакта с расширением `.bin`

### 8.4. Поддерживаемые проекты

**Story-to-video:**
- Артефакты: audio.mp3, transcript.json, queries.json, media_manifest.json, subtitles.srt, final.mp4, run.log
- Primary: `final_video` → `final.mp4`

**Ежу понятно:**
- Артефакты: transcript.json, scenes_raw.json, scenes_normalized.json, tts_timeline.json, subtitles.srt/.ass, summary_video_*.mp4, mixed_audio.wav, telegram_publish.json
- Primary: `final_video` → `summary_video_final.mp4`

### 8.5. UI для артефактов

На странице run details отображается структурированный список артефактов.

Primary artifact:
- отображается первым в списке
- имеет зелёный фон (`#f0fdf4`)
- badge «★ Primary artifact»
- отдельный блок «Primary publish artifact» с полной информацией:
  - artifact key, filename, extension
  - статус: доступен / fallback / missing
  - источник: правило проекта / override / fallback
  - кнопки скачивания и preview
- если primary artifact не найден — блок с жёлтой рамкой и списком причин

### 8.6. Primary artifact в publish block

В publish block на странице run details:
- явно показано, какой artifact будет опубликован
- указаны filename и ключ
- доступна кнопка скачивания
- если primary artifact не определён — предупреждение
- publish flow по умолчанию использует этот artifact

---

## 9. Публикация

### Архитектура публикации

- `PublishProfile` — настраиваемый профиль с credentials и defaults
- `ProjectPublishBinding` — привязка профиля к проекту
- `PublishRequest` — запрос на публикацию конкретного run
- **Primary artifact** — определяет, какой artifact считается основным media payload
- **`youtube_adapter.py`** — адаптер публикации для YouTube Data API v3

PublishRequest по умолчанию использует primary artifact.

### YouTube publishing flow

1. Создаётся PublishProfile с платформой `youtube`
2. В credentials сохраняются `client_id` и `client_secret`
3. Пользователь проходит OAuth 2.0 flow (prompt=consent + access_type=offline)
4. После OAuth получается список каналов через `youtube.channels.list(mine=true)`
5. Привязывается конкретный канал (channel_id + channel_title)
6. При публикации: `POST /publish/execute/{request_id}` скачивает primary artifact с сервера проекта и загружает в YouTube через `videos.insert` (resumable upload)

### OAuth endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| API | `GET /api/publish/youtube/oauth/url?profile_id=` | Получить URL для OAuth |
| API | `GET /api/publish/youtube/oauth/channels?profile_id=` | Получить список каналов после OAuth |
| API | `POST /api/publish/youtube/oauth/select-channel` | Выбрать канал |
| API | `POST /api/publish/execute/{request_id}` | Выполнить публикацию |
| UI | `GET /publish/youtube/auth/{profile_id}` | Начать OAuth (редирект в Google) |
| UI | `GET /publish/youtube/callback` | Callback OAuth |
| UI | `POST /publish/youtube/select-channel` | Выбор канала (форма) |
| UI | `POST /publish/execute/{request_id}` | Выполнить публикацию (форма) |

### Publish flow (двухшаговый)

Публикация состоит из двух шагов:

**Шаг 1: Создание запроса** (`POST /publish/request`)
- Пользователь выбирает профиль, заполняет заголовок/описание
- Создаётся `PublishRequest` со статусом `pending`
- Видео ещё не загружается

**Шаг 2: Выполнение** (`POST /publish/execute/{request_id}`)
- На странице run появляется кнопка **▶ Выполнить**
- Кнопка одноразовая: при нажатии блокируется и показывает спиннер
- Marshrutka скачивает primary artifact с сервера проекта через `fetch_artifact`
- Создаёт resumable upload сессию к `https://www.googleapis.com/upload/youtube/v3/videos`
- Загружает видео, обновляет `PublishRequest.status` (published / failed) и `PublishRequest.result`
- При ошибке под кнопкой появляется блок **подробнее** с текстом ошибки от YouTube API

### Управление credentials в профиле

Поле `credentials` в PublishProfile — свободный JSON-объект. При сохранении формы:
- Если введён валидный JSON — он сохраняется как есть
- Если JSON невалиден — сохраняется в `{"_raw_input": "...", "_parse_error": true}`, в форме показывается красное предупреждение
- Если в credentials есть ключ `raw` (старый формат) — форма показывает его содержимое для исправления

### Несколько каналов на одном Google-аккаунте

Marshrutka использует `prompt=consent`, поэтому каждый OAuth-заход выдаёт новый refresh token.
Каждый профиль хранит собственный refresh_token и selected_channel_id.

### UI

- **Профили:** `/publish/profiles` — CRUD, фильтр по платформам, статус готовности (готов / требуется OAuth / выберите канал / требует настройки)
- **Guides:** `/publish/guide/{platform}` — пошаговая инструкция для каждой платформы
- **Публикация из run:** после успешного pipeline, на странице run details
  - Показывается какой artifact будет опубликован
  - Если primary artifact не определён — предупреждение
  - Кнопка «Создать запрос» → кнопка «Выполнить»

---

## 10. Dashboard

**Главная страница приложения:** `/` → dashboard.

Dashboard — это operational cockpit, а не второй список проектов.

**Назначение:** отвечать на вопросы:
- где сейчас есть очередь к запуску
- где есть проблемы (failed items)
- где есть активные расписания
- где давно не было запусков (stale > 7 дней)
- какой проект требует внимания

**Сортировка карточек:** по приоритету внимания:
1. Проекты с failed queue items
2. Проекты без запусков > 7 дней (stale)
3. Проекты с очередью к запуску
4. Остальные

**В каждой карточке:**
- название и описание
- attention-индикаторы (failed, stale, queued)
- queue summary (total, queued, draft, failed)
- schedule summary (активные расписания)
- последний запуск + статус
- primary artifact info
- быстрые действия: открыть проект, запустить следующий из очереди, создать запуск

**Чем отличается от `/projects`:**
- `/` (dashboard) — operational: фокус на том, что требует действий
- `/projects` (реестр) — management: настройки, параметры, primary artifact, дефолты, привязки

### Страница реестра проектов (`/projects`)

Страница проектов — это реестр/management view.

Отличия от dashboard:
- более компактный list view
- показывает queue summary, schedule summary, primary artifact
- editable defaults summary
- прямые ссылки на редактирование
- без operational attention indicators (stale, failed alerts) — это роль dashboard

---

## 11. User Interface

### Навигация (sidebar)

- **Дашборд** (`/`) — оперативная сводка
- **Проекты** (`/projects`) — список проектов
- **Расписания** (`/schedules`) — cron-расписания (queue-driven)
- **Публикация** (`/publish/profiles`) — управление профилями публикации

### Страница проекта (`/projects/{id}`)

Приоритет блоков (сверху вниз):

1. **Очередь проекта** — список queue items с действиями
2. **Быстрый запуск / Добавить в очередь / Черновик** — единая форма
3. **Расписания** — queue-driven cron с пресетами
4. **Последние запуски** — merged-список с фильтрами
5. **Публикация** — привязанные профили + primary artifact info
6. **Задачи и конфигурация** — под details (низкий приоритет)

### Страница запуска (`/runs/{id}`)

1. Два статусных блока
2. Remote job ID + queue item ID (если есть)
3. Input payload
4. Данные с сервера: прогресс, шаги, артефакты (с primary artifact подсветкой), логи, метаданные
5. Ответ сервера на submit
6. Блок публикации (с primary artifact инфо)

### Расписания — cron presets

Вместо голого cron input:
- Пресеты: каждый день, по будням, раз в неделю, каждые N часов
- Advanced mode: raw cron expression
- Человекочитаемое описание правила
- Показывается связанная очередь проекта

### Часовой пояс

Все времена в UI отображаются в `Europe/Moscow` (MSK, UTC+3).

---

## 12. Seed-проекты

Story-to-video (`http://141.136.44.9:8001`), Ежу понятно (`http://141.136.44.9:8000`) и Зад Пегаса (`http://141.136.44.9:8002`).

Особенности Зад Пегаса:
- Run endpoint: `POST /run` (отдельный от `GET /jobs`)
- Основное поле ввода: `text` (не `news_text`)
- Флаг публикации: `post_to_telegram` (не `publish_to_telegram`)
- Primary artifact: `finalwithaudio.mp4`

Проекты обновлены в версии 0.5:
- добавлен `primary_artifact` блок
- добавлен `defaults` блок

---

## 13. Конфигурация

Переменные окружения (`.env`):

```bash
ROUTERAI_BASE_URL=https://routerai.ru/api/v1
ROUTERAI_API_KEY=your_key
ROUTERAI_MODEL=deepseek/deepseek-v4-flash
SERPAPI_API_KEY=your_serpapi_key
STT_HTTP_URL=http://141.136.44.9:9000/transcribe
```

---

## 14. Сознательные упрощения (версия 0.5)

- **Config-first** — проекты редактируются как JSON, UI — тонкая оболочка
- **Queue storage: per-project files** — `data/queues/<project_id>.json` вместо единого файла
- **Queue reorder: position-based** — move up/down вместо drag-and-drop
- **Schedules: queue-driven** — убрано поле `input` из Schedule, schedules работают через очередь
- **Primary artifact: project-level** — override на уровне queue item опционален
- **Fallback: single video heuristic** — только если ровно один video artifact
- **YouTube publish adapter** — реализован (youtube_adapter.py), OAuth + videos.insert
- **Остальные платформы (Instagram/VK/Rutube)** — UI есть, адаптеров нет
- **Нет multi-tenancy** — один оператор
- **Нет vault-системы** — credentials в JSON профиля + env-backed secrets
- **Нет event-platform** — scheduling только cron
- **Нет observability subsystem** — structured run details вместо телеметрии
- **Нет background workers** — APScheduler в том же процессе
- **Нет сложного reconciliation** — status sync через fetch + link + display
- **UI не покрывает 100%** — сложные настройки редактируются вручную в JSON

---

## 15. Как поддерживать

### Принципы

1. Любое существенное изменение архитектуры, моделей данных, интеграций или ключевых пользовательских сценариев должно сопровождаться обновлением DOCS.md.
2. Новые модели Pydantic добавляются в `models.py` с полными type hints и default-значениями.
3. JSON-хранилища обратно совместимы: новые поля — опциональные, с default.
4. При добавлении новой интеграции: endpoint-ы в `ProjectIntegration`, маппинг в `remote_sync.py`.
5. При добавлении новой платформы публикации: `PublishPlatform` enum + guide в `publish_guide.html`.
6. Runner — только submit, polling в remote_sync.

### Добавление новой платформы публикации

1. Добавить значение в `PublishPlatform` enum
2. Добавить в `PLATFORM_LABELS` и `PLATFORM_SHORT_CAPABLE`
3. Создать секцию в `templates/publish_guide.html`
4. Профиль автоматически доступен через `/publish/profiles/new`

---

## 16. Изменения в версии 0.5 / 2.2 (agent update)

### Что добавлено в AI-агенте (v2.2)

1. **Reply suggestions** — AI-агент генерирует кнопки быстрых ответов после уточняющих вопросов. SSE `message_done` теперь содержит опциональное поле `suggestions: string[]`. Фронтенд рендерит pill-кнопки под сообщением, клик отправляет текст как обычный user message. Состояние suggestions (с флагом `suggestionsUsed`) сохраняется в localStorage и восстанавливается при reload.
2. **Улучшенный fallback** — при исчерпании лимита шагов без контента агент делает упрощённый LLM-вызов без инструментов вместо немедленного `(агент не смог сформировать ответ)`. Жёсткий fallback — только если и упрощённый вызов не дал результата.
3. **delete_runs tool** — новый инструмент для удаления запусков по фильтрам (project_id, статусы через запятую, ID через запятую). Двухшаговый паттерн: preview → confirm — модель показывает, что будет удалено, и только после подтверждения пользователя выполняет удаление. Зарегистрирован в `TOOLS` и `TOOL_DEFINITIONS`.

1. **QueueItem** — first-class сущность для очередей проектов
2. **QueueStore** — per-project JSON storage в `data/queues/`
3. **Queue API** — полный CRUD + launch + move + duplicate
4. **Quick launch 3-mode** — Launch now / Add to queue / Save draft
5. **Dashboard** — новая главная страница
6. **PrimaryArtifactConfig** — явная модель главного артефакта
7. **ProjectDefaults** — defaults model для проекта
8. **Schedules help page** — `/schedules/help`
9. **Cron presets** — удобные пресеты вместо голого cron input
10. **Enhanced ProjectInputField** — helper_text, visible, supports_default, deprecated
11. **Launch next** — кнопка запуска первого элемента очереди
12. **Duplicate queue item** — дублирование элемента очереди
13. **Queue item history** — `launch_history` с информацией о запусках
14. **Primary artifact в UI** — визуальное выделение, badge, publish block info

### Что изменено (corrective iteration)

1. **Dashboard** — переработан как operational cockpit с attention indicators (failed, stale, queued priority). Сортировка по urgency, а не по алфавиту. Отличается от `/projects` по роли.
2. **Projects page** — переработана как registry/management view. Показывает queue summary, schedule summary, primary artifact, defaults, publish bindings. Без operational alerts.
3. **Queue item detail** — добавлена отдельная страница `/projects/{id}/queue/{qiid}` с полной информацией и редактированием. Прямая ссылка из queue list на project page.
4. **Field `visible`** — исправлена логика парсинга чекбокса. Теперь `visible = false` реально скрывает поле из quick launch/add to queue формы. Использован hidden+checkbox pattern для корректной передачи состояния.
5. **Field `supports_default`** — переименован в UI в «проектное значение по умолч.» с tooltip. Парсинг чекбокса также исправлен.
6. **Primary artifact** — перестал быть декоративным badge. На run details появился отдельный блок «Primary publish artifact» с: ключ, filename, тип, статус, источник (правило/override/fallback), кнопки скачивания и preview. Если не найден — жёлтое предупреждение с причинами.
7. **Publish block** — явно показывает какой artifact будет опубликован. Ссылка на скачивание прямо в блоке.
8. **Run details** — добавлена связь с queue item. Прямая ссылка на `/projects/{id}/queue/{qiid}`.

### Что упрощено

1. **Scheduling model** — убрана сложная схема с фиксированным input
2. **Field deletion** — вместо удаления полей используется `visible`/`deprecated`
3. **Reorder queue** — position-based move up/down вместо drag-and-drop
4. **Fallback for primary artifact** — только single video heuristic
5. **Override at queue item** — опционально, не усложняет базовую модель

---

## 17. Content Memory / Dedupe DB (Planned Extension)

> ⚠ **Статус: DESIGN / PLACEHOLDER. Не активно.**
> Модель `ContentRecord` определена в `models.py`, но не используется в рантайме.

### 17.1. Назначение

Локальная duplicate-awareness layer для оператора.
Позволяет при добавлении в очередь проверять:
- не было ли уже похожей темы (по `topic_normalized`)
- не использовался ли тот же текст (по `source_text_hash`)
- не запускался ли похожий материал для этого проекта

### 17.2. Что НЕ является

- **НЕ source of truth for remote jobs** — статусы и данные pipeline живут на сервере проекта
- **НЕ полноценный CMS** — никакой системы управления контентом
- **НЕ embeddings / vector search** — без dense retrieval, без ANN индексов
- **НЕ требует PostgreSQL или внешней БД** — живёт в JSON-файле, как и всё в Marshrutka

### 17.3. Модель

```python
class ContentRecord(BaseModel):
    record_id: str                 # cr_<hex>
    project_id: str                # ссылка на проект
    title: str                     # оригинальный заголовок
    topic_normalized: str          # нормализованная тема (lowercase, без стоп-слов)
    source_text_hash: str          # SHA256/xxhash текста
    text_excerpt: str              # первые N символов текста для preview
    source_url: str                # исходный URL (если есть)
    queue_item_id: str             # ссылка на QueueItem
    run_id: str                    # ссылка на Run
    remote_job_id: str             # external job ID
    status: ContentRecordStatus    # draft / used / skipped / deprecated
    created_at: datetime           # когда записан
    matched_record_id: str | None  # если найден дубликат — ссылка на него
    match_reason: str              # причина совпадения (topic / hash / url)
```

### 17.4. Сценарии использования (будущие)

**При добавлении в очередь (enqueue):**
1. Вычислить `source_text_hash` от payload-текста
2. Проверить `data/content_memory.json` на совпадение хеша или `topic_normalized`
3. Если совпадение найдено — показать предупреждение: «Этот текст уже запускался для проекта X (run_id: ...)»
4. Оператор решает: добавить всё равно или отменить

**При создании schedule:**
1. Проверить очередь на дубликаты темы перед следующим запуском
2. Если в очереди есть элемент с той же темой, что уже запускался — оператор получает уведомление

**Просмотр истории:**
1. На странице queue item: блок «Похожие запуски» с ссылками
2. На странице проекта: «Контент, который уже публиковался»

### 17.5. Технические решения

- **Хранилище:** `data/content_memory.json` (единый JSON-файл, `FileStore[ContentRecord]`)
- **Хеширование:** `hashlib.sha256(text.encode()).hexdigest()` — без внешних библиотек
- **Нормализация темы:** lowercasing + удаление пунктуации + базовая токенизация
- **Поиск:** последовательный перебор (data < 10K записей, линейная сложность допустима)
- **Без индексов:** пока данных мало, индексы не нужны

### 17.6. Когда будет реализовано

1. Когда накопится достаточно запусков, чтобы дубликаты стали реальной проблемой
2. Когда оператор явно запросит эту функциональность
3. В рамках итерации, focused на content quality / duplicate management

---

## 18. Изменения в версии 0.6 (UX/Stability)

### Исправлено

1. **Schedule create flow** — починен Internal Server Error при создании cron-расписания:
   - **Root cause:** поле `enabled: bool = Form(True)` не обрабатывало значение `"on"`, которое браузер отправляет для отмеченных чекбоксов. Pydantic v2 отвергал `"on"` как невалидное значение для `bool`, вызывая ValidationError.
   - **Fix:** параметр изменён на `enabled: str = Form("off")` с ручной конвертацией (`enabled in ("on", "true", "1", "yes")`)
   - Добавлена валидация cron-выражения через regex (5 полей)
   - Добавлен try/except с `traceback.print_exc()` вокруг `add_schedule()`
   - Добавлены query-параметры `schedule_ok`/`schedule_error` для обратной связи пользователю
   - Страница проекта теперь отображает зелёное (успех) или красное (ошибка) сообщение

### Улучшено (UX/Semantics)

2. **Dashboard** — усилено позиционирование как operational cockpit:
   - Уточнено описание: "Оперативный пульт: что требует внимания прямо сейчас"
   - Добавлена кнопка быстрого перехода к реестру проектов
   - Убран сломанный Jinja2-цикл с разделением на attention/ok группы

3. **Project page** — уточнены роли блоков:
   - Раздел очереди: заголовок «Очередь запусков» с пояснением workflow
   - Раздел формы: заголовок «Новый запуск» с описанием действий (запустить/в очередь/черновик)
   - Helper text под формой поясняет workflow

4. **Queue item detail** — улучшена инспекция payload:
   - Payload preview открыт по умолчанию (details open)
   - Улучшено отображение ключ-значение с выравниванием
   - Добавлен блок «Defaults проекта» с подсветкой, какие defaults будут применены
   - Amber-подсветка для значений, которые будут применены из defaults
   - Зелёная метка для значений, переопределённых в payload

5. **Labels** — уточнены названия и helper text-ы для русскоязычного оператора

### Добавлено

6. **ContentRecord** — модель для future duplicate-aware content memory:
   - Модель в `models.py` с набором полей для record_id, хеша темы/текста, связей
   - Полное описание design в разделе 17 DOCS.md
   - ContentRecord НЕ используется в рантайме — только placeholder

7. **PUBLISHING_ACCESS_GUIDE.md** — отдельное руководство по получению доступа к API публикаций:
   - YouTube: OAuth, Google Cloud Console, client_secret
   - Instagram: Meta for Developers, Graph API, long-lived tokens
   - VK Video: Standalone app, Implicit Flow, access_token
   - Rutube: API-ключ из настроек канала
   - Для каждой платформы: пошаговая инструкция, поля профиля, типовые ошибки, сроки истечения
   - Общая таблица сроков действия для всех платформ
   - Секция с ограничениями платформ

---

## 19. Изменения в версии 0.7 (UX/Schedules/Content Memory Foundation)

### Исправлено

1. **Schedule create flow** — добавлен расчёт и сохранение `next_run_at`:
   - После создания расписания APScheduler возвращает `next_run_time`
   - `_persist_next_run()` сохраняет `next_run_at` в `Schedule` модель
   - Значение отображается в колонке «Следующий» на страницах проекта и списка расписаний

2. **Dashboard last run status** — исправлено отображение английского статуса:
   - Вместо raw `remote_status.value` теперь используется `REMOTE_STATUS_LABELS` (русские названия)

### Улучшено (UX/Semantics)

3. **Project page — очередь**:
   - Queue items теперь показывают source-теги: 🤖 (agent), API, импорт
   - Ручные элементы (manual) не маркируются (чище визуально)

4. **Schedules table** — добавлена колонка «Следующий запуск»:
   - На странице проекта и на `/schedules`
   - Показывает `next_run_at` из сохранённой модели
   - Если расписание только что создано — значение заполняется сразу

5. **Content Memory placeholder** — добавлен UI-блок на странице проекта:
   - Секция «Проверка дублей / история тем» (collapsed)
   - Показывает количество записей в `content_memory.json`
   - Описывает будущую функциональность duplicate-check

### Добавлено

6. **ContentMemoryStore** — FileStore для ContentRecord:
   - Хранилище: `data/content_memory.json`
   - Глобальный экземпляр: `content_memory_store`
   - Полностью готов к записи, но не интегрирован в flows (плановый future step)

7. **Schedule `next_run_at` persistence** — механизм сохранения следующего времени срабатывания:
   - Функция `_persist_next_run()` в `scheduler.py`
   - Вызывается из `schedule_job()` после регистрации в APScheduler
   - При рестарте приложения (`reload_schedules()`) значения обновляются

8. **Zad Pegasa project** — добавлен проект `projects/zad-pegasa.json`:
   - API: `http://141.136.44.9:8002`
   - Run endpoint: `POST /run`
   - Поля ввода: `text` (textarea), `tts_mode` (select), `post_to_telegram` (checkbox)
   - Primary artifact: `finalwithaudio.mp4`

## 20. Known limitations

- **YouTube публикация** — реализована (OAuth + videos.insert). Поддерживается загрузка primary artifact.
- **Instagram, VK, Rutube** — UI есть, адаптеров нет. Публикация работает только для YouTube.
- **YouTube OAuth refresh token** — может истечь при неиспользовании > 6 месяцев.
- **YouTube Data API квота** — 10 000 единиц/день. Одна загрузка ~1600 единиц.
- **Отмена запуска** — endpoint `POST /jobs/{id}/cancel` определён в модели, но UI-кнопка не реализована.
- **Primary artifact fallback** — только simple heuristic. Если видео несколько, fallback не срабатывает.
- **Queue reorder** — position-based, а не drag-and-drop.
- **Queue item validation** — перед enqueue проверяется только наличие payload, без глубокой валидации.
- **Одновременные запуски** — не блокируются, но runner выполняет submit последовательно.
- **Агент (v2.2)** — добавлены reply suggestions (быстрые ответы-кнопки), улучшен fallback текстовых ответов, добавлен инструмент `delete_runs` для управления запусками.
- **Web search** — зависит от SerpApi. Без ключа поиск недоступен.
- **Content Memory** — модель и хранилище определены, но не интегрированы в flows. Duplicate-check не активен.
- **Schedule next_run_at** — вычисляется при регистрации в APScheduler, но не обновляется в рантайме (только при перезагрузке schedules).
