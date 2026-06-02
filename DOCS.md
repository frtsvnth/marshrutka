# Marshrutka — архитектура и эксплуатация

> Personal-use orchestration cockpit для контентных pipeline-проектов.
> Дата: 2026-06-01 | Версия: 0.2

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

---

## 2. Source of truth

| Сущность | Source of truth | Хранилище |
|---|---|---|
| Проекты | `projects/*.json` | JSON-файлы в проектной директории |
| Подключенные pipeline-запуски | **Сервер проекта** (external API) | Удалённый `GET /jobs/<id>` |
| Локальные launch-записи Marshrutka | `data/runs.json` | JSON-файл |
| Статус выполнения pipeline | **Сервер проекта** (remote job status) | Получается через `GET /jobs/<id>` |
| Scheduling | `data/schedules.json` | JSON-файл + APScheduler |
| Профили публикации | `data/publish_profiles.json` | JSON-файл |
| Запросы на публикацию | `data/publish_requests.json` | JSON-файл |

**Canonical execution ID для pipeline — это server job id проекта**, а не локальный launch id Marshrutka.

---

## 3. Модель данных

### 3.1. Проект (`Project`)

Обязательные поля: `project_id`, `display_name`.
Опциональные: `description`, `input_fields`, `jobs`, `integration`, `publish_bindings`, `config`.

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
    "job_cancel_endpoint": "/jobs/{job_id}/cancel",
    "auto_sync": true
  },
  "publish_bindings": [
    { "profile_id": "pub_abc", "enabled": true, "is_default": true }
  ]
}
```

### 3.2. Интеграция (`ProjectIntegration`)

Конфигурация endpoint-ов сервера проекта:
- `api_url` — базовый URL сервера
- `jobs_list_endpoint` — `GET {api_url}{endpoint}` → список jobs
- `job_detail_endpoint` — `GET {api_url}{endpoint}` с `{job_id}` → детали job
- `artifacts_endpoint` — `GET {api_url}{endpoint}` с `{job_id}` и `{key}` → скачивание артефакта
- `job_cancel_endpoint` — `POST {api_url}{endpoint}` с `{job_id}` → отмена job
- `auto_sync` — автоматическая синхронизация после запуска

### 3.3. Локальный запуск (`Run`)

Префикс ID: `launch_` (не `run_`, чтобы явно отличать от server job id).

Поля:
- `run_id` — локальный launch ID (Marshrutka)
- `project_id` — ссылка на проект
- `orchestration_status` — статус оркестрации Marshrutka (draft/submitting/linked/sync_error/detached)
- `remote_status` — статус выполнения на сервере проекта (pending/running/success/failed/cancelled/unknown)
- `remote_job_id` — canonical execution ID (ID job на сервере проекта)
- `input` — снимок входных данных
- `submit_response` — ответ сервера на POST /jobs
- `last_sync_at`, `sync_error` — статус синхронизации

### 3.4. Удалённый job (`RemoteJobRef`, `RemoteJobDetails`)

Кэшированные данные с сервера проекта:
- `external_job_id` — ID job на сервере
- `remote_status` — строка статуса от сервера
- `steps`, `artifacts`, `metadata`, `logs`, `warnings`
- `job_response` — полный raw JSON ответ сервера
- `last_synced_at` — время последней синхронизации

### 3.5. Профиль публикации (`PublishProfile`)

Префикс ID: `pub_`.

- `display_name` — название профиля
- `platform` — youtube / instagram / vk_video / rutube
- `credentials` — JSON с учётными данными
- `channel_title`, `channel_id` — данные канала
- `privacy_defaults`, `title_defaults`, `description_defaults`, `tags_defaults`, `shorts_defaults` — настройки по умолчанию
- `is_ready` — признак готовности профиля

### 3.6. Запрос на публикацию (`PublishRequest`)

Префикс ID: `pubreq_`.
Связывает `run_id`, `profile_id`, `platform` с конкретным запросом публикации.

### 3.7. Расписание (`Schedule`)

Префикс ID: `sched_`.
Cron-выражение + `project_id` + фиксированный input.

---

## 4. Как работает запуск проекта

### Flow ручного запуска

1. Пользователь нажимает «Запустить» на странице проекта
2. Marshrutka создаёт `Run` со статусом `orchestration_status = submitting`
3. Отправляет `POST {api_url}{run_endpoint}` с input-данными
4. Если сервер вернул `job_id`:
   - `orchestration_status → linked`
   - `remote_job_id` сохраняется
   - `remote_status` маппится из ответа сервера
5. Если сервер не вернул `job_id`:
   - `orchestration_status → detached`
   - `sync_error` заполняется
6. Если сетевой таймаут / ошибка:
   - `orchestration_status → sync_error`
7. Управление возвращается немедленно (без ожидания завершения pipeline)
8. Выполняется `fetch_remote_jobs` для обновления списка

**Runner не делает polling.** Мониторинг статуса — через `remote_sync.sync_run_status()`.

### Статусы оркестрации

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

### Кейс «Marshrutka упала, а job на сервере жив»

1. При следующем `fetch_remote_jobs()` remote job будет обнаружен в списке
2. Если у `Run` уже есть `remote_job_id` → статус восстановится в `linked`
3. Если `Run` не создан (сбой до сохранения) → remote job отобразится в списке как `source = remote`

---

## 6. Синхронизация remote jobs

### `fetch_remote_jobs(integration, project_id)`

- GET `{api_url}{jobs_list_endpoint}`
- Парсит ответ:
  - `{items: [...], total, offset, limit}` — paginated (story-to-video, ezhu-ponyatno)
  - `[{...}]` — плоский массив
  - `{jobs: [...]}` — legacy формат
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
- Поле `progress` содержит текущий шаг пайплайна: `{step, current, total, message}`

---

## 7. Артефакты

### `fetch_artifact(integration, remote_job_id, artifact_key)`

- GET `{api_url}{artifacts_endpoint}` с `{job_id}` и `{key}`
- Возвращает `(bytes, content_type)`
- Используется UI-роутами `/runs/{run_id}/artifacts/{key}` и `/runs/{run_id}/artifacts/{key}/preview`

### Поддерживаемые проекты

**Story-to-video** (`http://141.136.44.9:8001`):
- `GET /jobs/<job_id>/artifacts/<key>`
- Артефакты: audio.mp3, transcript.json, queries.json, media_manifest.json, subtitles.srt, final.mp4, run.log

**Ежу понятно** (`http://141.136.44.9:8000`):
- `GET /jobs/<job_id>/artifacts/<key>`
- Артефакты: transcript.json, scenes_raw.json, scenes_normalized.json, tts_timeline.json, subtitles.srt/.ass, summary_video_*.mp4, mixed_audio.wav, telegram_publish.json

### UI для артефактов

На странице run details отображается структурированный список артефактов. Каждый элемент содержит:

| Поле | Описание |
|---|---|
| **Filename** | Отображаемое имя файла с расширением (primary label) |
| **Extension tag** | Тип файла (расширение) |
| **Artifact key** | Технический идентификатор артефакта (secondary, меньшим шрифтом) |
| **Preview** | Кнопка открытия inline preview (только для поддерживаемых типов) |
| **Download** | Кнопка скачивания |

#### Normalization artifact filename (приоритет):

1. **Server value** — если сервер проекта вернул filename в значении артефакта, используется он
2. **Known mapping** — иначе проверяется `ARTIFACT_FILENAME_MAP` + `PROJECT_ARTIFACT_OVERRIDES` в `models.py`
3. **Fallback** — если ни сервер, ни mapping не дали имени, используется ключ артефакта с расширением `.bin`

#### Download naming convention

При скачивании файла имя формируется как:

```
<remote_job_id>_<artifact_filename>
```

Примеры:
- `abc123_final.mp4`
- `abc123_transcript.json`
- `abc123_summary_video_final.mp4`

Используется canonical `remote_job_id`, а не локальный `run_id`.
Filename санитизируется (пробелы → `_`, удаляются опасные символы).

#### Route definitions

| Route | Disposition | Purpose |
|---|---|---|
| `GET /runs/{run_id}/artifacts/{key}` | `attachment` | Download с `remote_job_id` в имени |
| `GET /runs/{run_id}/artifacts/{key}/preview` | `inline` | Inline preview для браузера |

### Preview behavior

Артефакты открываются в inline modal/overlay прямо на странице run details.
Поддерживаемые типы preview:

| Preview kind | Расширения | Поведение |
|---|---|---|
| **video** | mp4, webm, mov | `<video controls>` с preload=metadata, muted autoplay |
| **audio** | mp3, wav, m4a, ogg | `<audio controls>` с autoplay |
| **image** | png, jpg, jpeg, webp, gif | `<img>` с ограничением по размеру |
| **text** | json, txt, log, srt, ass, md | `<pre>` с scroll, JSON pretty-print если возможно |

#### Modal behavior
- Открывается по кнопке Preview без перезагрузки страницы
- Закрывается: клик вне окна / кнопка ✕ / Escape
- Media (video/audio) приостанавливаются при закрытии
- Ошибки загрузки показываются inline внутри modal
- Ошибка preview не ломает страницу run details

#### Unsupported types
- Кнопка Preview не показывается
- Доступна только кнопка Download
- Расширение отображается как `?`

### Модель данных артефакта в UI

```python
{
    "key": str,               # artifact key (from server)
    "filename": str,          # resolved display filename
    "extension": str,         # file extension (lowercase)
    "content_type": str,      # MIME type
    "previewable": bool,      # supports preview
    "preview_kind": str,      # "video" / "audio" / "image" / "text"
    "download_url": str,      # /runs/{run_id}/artifacts/{key}
    "preview_url": str,       # /runs/{run_id}/artifacts/{key}/preview
}
```

Нормализация выполняется функцией `_normalize_artifact_list()` в `ui.py` при каждом рендеринге страницы run details.

---

## 8. Публикация

### Архитектура публикации

- `PublishProfile` — настраиваемый профиль с credentials и defaults
- `ProjectPublishBinding` — привязка профиля к проекту
- `PublishRequest` — запрос на публикацию конкретного run

### UI

- **Профили:** `/publish/profiles` — CRUD, фильтр по платформам, статус готовности
- **Guides:** `/publish/guide/{platform}` — пошаговая инструкция для каждой платформы
- **Публикация из run:** после успешного pipeline, на странице run details

### Поддержка платформ

**Текущий статус:**

| Платформа | UI профиля | API-адаптер | OAuth | Short-video |
|---|---|---|---|---|
| YouTube | ✔ готово | stub (скоро) | manual setup | ✔ |
| Instagram | ✔ готово | stub (скоро) | manual setup | ✔ |
| VK Видео | ✔ готово | stub (скоро) | manual setup | ✔ |
| Rutube | ✔ готово | stub (скоро) | manual setup | ✔ |

Publish adapter: stub = интерфейс готов, реальная загрузка через API будет добавлена позже.

---

## 9. Seed-проекты

Оба проекта имеют одинаковую структуру API:
- `POST /jobs` — создать job (response: `{job_id, status, created_at}`)
- `GET /jobs` — список job (response: `{items: [...], total, offset, limit}`)
- `GET /jobs/{job_id}` — детали job
- `GET /jobs/{job_id}/artifacts/{name}` — скачать артефакт
- `POST /jobs/{job_id}/cancel` — отмена
- `DELETE /jobs/{job_id}` — удаление

Статусы: `queued` → `running` → `completed` | `failed` | `partial` | `cancelled`
Аутентификация: опционально `X-API-Key` header.

### Story to Video

- **Host:** `http://141.136.44.9:8001`
- **Input:** `news_text` (textarea, required), `queries` (text, optional), `publish_to_telegram` (checkbox, optional)
- **Pipeline:** 8 шагов: `tts → transcribe → extract_queries → media_search → media_download → subtitles → render → publish`
- **Артефакты:**

| Ключ | Файл | Описание |
|---|---|---|
| `final_video` | `final.mp4` | Финальное видео 9:16 |
| `audio_mp3` | `audio.mp3` | Озвучка TTS |
| `subtitles_srt` | `subtitles.srt` | Субтитры SRT |
| `transcript_json` | `transcript.json` | Полная транскрипция |
| `queries_json` | `queries.json` | Поисковые запросы |
| `media_manifest_json` | `media_manifest.json` | Манифест медиа-ассетов |

- **Типичное время:** 1–10 минут (зависит от длины текста)
- **Polling interval:** 5–10 секунд

### Ежу понятно

- **Host:** `http://141.136.44.9:8000`
- **Input:** `url` (text, required — YouTube ссылка), `speech_rate` (text, опц., def: 1.2), `voice` (select: Tur_24000 / Nec_24000 / Bys_24000 / May_24000 / Ost_24000 / Pon_24000 / Kin_24000), `landscape` (checkbox), `telegram_enabled` (checkbox)
- **Pipeline:** 15 шагов: `download → extract_audio → transcribe → summarize → metadata_package → validate → tts → render → audio_mix → subtitles → burn → avatar_render → avatar_overlay → outro → telegram_publish`
- **Артефакты:**

| Ключ | Файл | Описание |
|---|---|---|
| `final_video` | `summary_video_final.mp4` | Финальное видео с аватаром, субтитрами, outro |
| `avatar_overlay_video` | `summary_video_with_avatar.mp4` | Видео с наложенным аватаром |
| `subtitled_video` | `summary_video_subtitled.mp4` | Видео с субтитрами (без аватара) |
| `preview_video` | `summary_video.mp4` | Базовое видео (без субтитров и аватара) |
| `subtitles_srt` | `subtitles.srt` | Субтитры SRT |
| `subtitles_ass` | `subtitles.ass` | Субтитры ASS |
| `transcript` | `transcript.json` | Полная транскрипция |
| `summary_text` | `summary_text.txt` | LLM-саммари |
| `metadata_package` | `metadata_package.json` | Метаданные для публикации |
| `tts_audio` | `summary_tts_master.wav` | Синтезированная речь TTS |
| `mixed_audio` | `mixed_audio.wav` | Финальный аудиотрек |
| `avatar_video` | `avatar_render.mp4` | Аватар на чистом фоне |
| `telegram_publish` | `telegram_publish.json` | Результат публикации в Telegram |
| `caption_quality_report` | `captions_quality_report.json` | Отчёт о качестве субтитров |

- **Типичное время:** 2–25 минут (зависит от длины видео)
- **Polling interval:** 5–10 секунд

---

## 10. Как добавить новый проект

### Через UI

1. Нажать «+ Добавить проект» на главной
2. Заполнить: ID, название, описание
3. API URL и endpoints интеграции
4. Поля ввода (key/label/type)
5. Профили публикации
6. Сохранить → создаётся `projects/<id>.json`

### Вручную (config-first)

Создать `projects/<project_id>.json`:

```json
{
  "project_id": "my-project",
  "display_name": "Мой проект",
  "description": "Описание",
  "input_fields": [
    { "key": "text", "label": "Текст", "type": "textarea", "required": true }
  ],
  "integration": {
    "api_url": "http://localhost:8000",
    "jobs_list_endpoint": "/jobs",
    "job_detail_endpoint": "/jobs/{job_id}",
    "artifacts_endpoint": "/jobs/{job_id}/artifacts/{key}"
  }
}
```

### Через API

```
POST /api/projects  с телом Project JSON
```

---

## 11. Структура проекта

```
marshrutka/
├── main.py              # FastAPI entry point, lifespan
├── config.py            # paths, URLs, constants
├── models.py            # Pydantic models
├── storage.py           # FileStore generic JSON CRUD
├── registry.py          # Project CRUD (projects/*.json)
├── runner.py            # Job submission (submit-first, no polling)
├── remote_sync.py       # Remote jobs sync, artifact proxy, link management
├── scheduler.py         # APScheduler cron engine
├── api.py               # REST API (/api/*)
├── ui.py                # HTML routes (/projects, /runs, /publish, /schedules)
├── DOCS.md              # Этот файл
├── projects/            # Project configs (*.json)
│   ├── story-to-video.json
│   └── ezhu-ponyatno.json
├── data/                # Persisted state
│   ├── runs.json        # Local launch records
│   ├── schedules.json   # Cron schedules
│   ├── publish_profiles.json
│   └── publish_requests.json
├── templates/           # Jinja2 templates
│   ├── base.html        # Layout: sidebar + content + AI panel
│   ├── projects.html    # Project list
│   ├── project.html     # Project detail (runs, run form, schedules)
│   ├── add_project.html # New project form
│   ├── edit_project.html
│   ├── run.html         # Run details (remote job data, artifacts, publish)
│   ├── schedules.html
│   ├── publish_profiles.html
│   ├── publish_profile_form.html
│   └── publish_guide.html
├── static/              # Static assets
├── requirements.txt     # fastapi, uvicorn, pydantic, jinja2, apscheduler, httpx
└── .venv/               # Virtual environment
```

---

## 12. UI: ключевые компоненты

### Навигация (sidebar)

- **Проекты** (`/`) — список проектов
- **Расписания** (`/schedules`) — cron-расписания
- **Публикация** (`/publish/profiles`) — управление профилями публикации

### Страница проекта (`/projects/{id}`)

Приоритет блоков (сверху вниз):

1. **Последние запуски** — основной блок на всю ширину
   - merged-список (локальные + remote jobs)
   - фильтры: все / активные / успешные / ошибки
   - строка поиска
   - источник: Marshrutka / сервер / связан
   - два статуса: orchestration + remote
2. **Ручной запуск** — компактная форма
3. **Расписание** — cron-задачи
4. **Задачи** — pipeline definition
5. **Публикация** — привязанные профили

### Страница запуска (`/runs/{id}`)

1. Два статусных блока: локальный (оркестрация) и удалённый (сервер)
2. Remote job ID — canonical, отображается крупно
3. Input payload
4. Данные с сервера: прогресс-бар (текущий шаг), шаги пайплайна, артефакты (с кнопками скачивания), логи, метаданные
5. Ответ сервера на submit (диагностика)
6. Блок публикации (для успешных запусков)

Прогресс-бар отображается только для активных запусков (remote_status = running/pending), показывает название шага и счётчик current/total.

### Часовой пояс

Все времена в UI отображаются в часовом поясе `Europe/Moscow` (MSK, UTC+3).
Используется Jinja2-фильтр `moscow_time(format)` в `ui.py:41-55`.
Наивные datetime (без tzinfo) интерпретируются как UTC, `None` отображается как «—».

---

## 13. Сознательные упрощения

Проект последовательно упрощается под personal-use:

- **Config-first** — проекты редактируются как JSON, UI — тонкая оболочка
- **Нет multi-tenancy** — один оператор, без разделения прав
- **Нет vault-системы** — credentials в JSON профиля + env-backed secrets
- **Нет event-platform** — scheduling только cron
- **Нет observability subsystem** — structured run details вместо телеметрии
- **Нет file manager** — артефакты проксируются с сервера проекта
- **Нет сложного reconciliation** — status sync через fetch + link + display
- **Publish adapters — stub** — интерфейс готов, API-заглушка до реализации
- **UI не покрывает 100%** — сложные настройки редактируются вручную в JSON

---

## 14. Как поддерживать

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

## 15. Known limitations

- **Publish adapters** — stub. Реальная загрузка через API не реализована ни для одной платформы.
- **Отмена запуска** — endpoint `POST /jobs/{id}/cancel` определён в модели, но UI-кнопка не реализована.
- **AI-панель** — не работает, заглушка в интерфейсе.
- **Повторная привязка** — если `Run` не сохранился до получения `remote_job_id`, автоматическая привязка невозможна. Remote job отобразится в списке как `source = remote` без локальной записи.
- **Артефакты** — скачивание через прокси Marshrutka, без потокового streaming для больших файлов (весь файл загружается в память).
- **Одновременные запуски** — не блокируются, но runner выполняет submit последовательно.
