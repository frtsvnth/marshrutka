# AI-агент Маршал — документация

> Версия: 2.2 | Последнее обновление: 2026-06-08

---

## 1. Обзор

Маршал — встроенный AI-оператор Marshrutka. Работает в правой панели интерфейса на всех страницах, использует OpenAI-compatible function calling через RouterAI.

**Возможности:**
- написание и редактирование текстов с автоматической проверкой длины
- работа с проектами Marshrutka (список, статусы, запуск пайплайнов)
- управление расписаниями
- поиск информации в интернете (SerpApi) + чтение страниц (fetch_url, research_topic)
- поиск YouTube-видео
- multi-step reasoning — может выполнять несколько инструментов подряд
- **долговременная память**: факты о пользователе, заметки о проектах, журнал решений
- **режим оператора**: анализ проектов, рекомендации, авто-задачи
- **редактирование файлов**: чтение, поиск, предложение и применение патчей
- **голосовой ввод**: через faster-whisper (push-to-talk, в разработке)
- **reply suggestions**: после вопросов и разветвлений диалога показывает кнопки с быстрыми ответами
- **удаление запусков**: фильтрация по проекту/статусам с двухшаговым подтверждением (preview → confirm)

---

## 2. Архитектура

### 2.1. Схема взаимодействия

```
Браузер (vanilla JS)                     FastAPI backend
┌──────────────────────────┐  SSE stream  ┌──────────────────────┐
│  agent-chat.js            │ ◄────────── │  agent/router.py     │
│  (marked.js рендер)       │  event: *   │                      │
│  (localStorage persistence)│             │  agent/harness.py    │
│  (step container ordering) │             │  (tool loop)         │
└──────────────────────────┘             └──────┬───────────────┘
                                                │
                                      ┌─────────▼──────────────┐
                                      │  OpenAI-compatible API  │
                                      │  (RouterAI)             │
                                      └────────────────────────┘
```

### 2.2. Файловая структура

```
agent/
├── __init__.py       # Re-exports
├── harness.py        # Tool-calling loop, LLM calls, SSE event generation
├── memory.py         # MemoryManager, все типы памяти, system prompt builder
├── models.py         # Pydantic: SSEEvent, ToolDefinition, ChatRequest, MemoryToolRequest, StateSaveRequest
├── router.py         # FastAPI routes: /chat, /context, /memory, /state, /transcribe, /memory-tool
├── session.py        # session_id validation (regex allowlist)
├── tools.py          # Tool implementations + TOOLS dict + TOOL_DEFINITIONS (24 tools)
├── web_tools.py      # search_web, search_youtube via SerpApi
├── research.py       # fetch_url, research_topic — чтение и анализ веб-страниц
├── file_tools.py     # read/write project files, search code, propose/apply patches
├── operator_tools.py # analyze_projects, suggest_schedules, create_followup_task, list_auto_tasks, delete_runs
└── voice.py          # Audio transcription via STT_HTTP_URL (faster-whisper)

static/
├── agent-chat.js     # Chat client: SSE, markdown (marked.js), step containers, suggestion buttons, localStorage persistence, clipboard
└── agent-chat.css    # Full chat styles: textarea, markdown, tool events, step containers, suggestion buttons, voice, transcript modal

data/agent/
├── user_profile.json      # Глобальный профиль (имя, preferences, notes)
├── user_facts.json        # Факты о пользователе (долгая память)
├── project_notes.json     # Заметки о проектах
├── project_memory.json    # Знания о проектах (долгая память)
├── decisions_log.jsonl    # Журнал решений агента
├── research_cache.json    # Кэш результатов исследований
├── agent_jobs.json        # Авто-задачи
├── sessions/              # Per-session chat history (*.json)
└── states/                # Saved frontend state для восстановления при reload
```

---

## 3. API endpoints

Все маршруты смонтированы под `/api/agent/`.

### 3.1. POST /api/agent/chat

Отправить сообщение агенту. Response — SSE stream.

**Request:**
```json
{
  "message": "напиши текст про кофейню на 160 слов",
  "session_id": "abc123def456"
}
```

- `message` — строка, обязательное. Максимум 8000 символов.
- `session_id` — опционально. Если не указан, сервер генерирует новый.

**Response:** `text/event-stream`

SSE протокол описан в разделе 4.

### 3.2. GET /api/agent/context

Получить контекст системы и сессии (включая user_facts и project_memories).

### 3.3. POST /api/agent/memory

Обновить user profile (глобально).

### 3.4. POST /api/agent/memory-tool

Доступ к инструментам долговременной памяти:
- `remember_fact` — запомнить факт о пользователе
- `remember_project_note` — запомнить заметку о проекте
- `list_memories` — список всех воспоминаний
- `search_memories` — поиск по воспоминаниям

### 3.5. POST /api/agent/state/save

Сохранить состояние фронтенда (messages, eventTrace, draft) на сервер.

### 3.6. GET /api/agent/state/load

Загрузить сохранённое состояние фронтенда.

### 3.7. POST /api/agent/transcribe

Загрузить аудиофайл для распознавания речи. Использует STT_HTTP_URL (faster-whisper).

**Request:** `multipart/form-data` с полем `file`
**Response:**
```json
{"text": "распознанный текст", "language": "ru", "duration": 1.0}
```

### 3.8. DELETE /api/agent/history

Очистить историю сессии + сбросить in-memory cache.

---

## 4. SSE протокол

Именованные события (event:) с JSON payload в data:.

### 4.1. Событие `session`
```
event: session
data: {"type": "session", "session_id": "abc123def456"}
```
Первое событие в стриме. Содержит ID сессии.

### 4.2. Событие `message_start`
```
event: message_start
data: {"type": "message_start"}
```
Сигнализирует начало формирования ответа.

### 4.3. Событие `token`
```
event: token
data: {"type": "token", "content": "Привет"}
```
Отдельный токен стриминга (зарезервировано для будущего token-by-token streaming).

### 4.4. Событие `tool_start`
```
event: tool_start
data: {"type": "tool_start", "tool_name": "count_words", "arguments": {"text": "..."}}
```
Агент вызывает инструмент. Появляется перед выполнением.

### 4.5. Событие `tool_result`
```
event: tool_result
data: {"type": "tool_result", "tool_name": "count_words", "result_summary": "5 слов, 25 символов", "duration_ms": 123}
```
Результат выполнения инструмента.

### 4.6. Событие `message_done`
```
event: message_done
data: {"type": "message_done", "content": "Удалить все failed? Или только один?", "suggestions": ["Удалить все failed", "Удалить только один", "Покажи все"]}
```
Финальный полный ответ ассистента. Опциональное поле `suggestions` — массив строк (0–4) для быстрых ответов-кнопок. Генерируется моделью, когда ассистент задаёт уточняющий вопрос или предлагает выбор.

### 4.7. Событие `error`
```
event: error
data: {"type": "error", "message": "Внутренняя ошибка. Попробуйте ещё раз."}
```
Ошибка. Без traceback, только безопасное сообщение.

### 4.8. Событие `done`
```
event: done
data: {"type": "done"}
```
Завершение стрима. Всегда последнее.

### Порядок событий в UI

Фронтенд рендерит события в правильном порядке:
1. `message_start` — UI готовится к приёму
2. `tool_start` / `tool_result` — цепочка tool-вызовов (рендерится в `.ai-step-tools`)
3. `message_done` — финальный ответ рендерится ПОСЛЕ tool-блока в том же `.ai-step`

---

## 5. Инструменты (tools)

### 5.1. Marshrutka core tools
| Tool | Описание |
|---|---|
| `count_words` | Подсчёт слов, символов, предложений |
| `get_projects` | Список всех проектов |
| `get_recent_runs` | Последние запуски |
| `run_pipeline` | Запуск пайплайна (async) |
| `create_schedule` | Создание cron-расписания |
| `get_schedules` | Список расписаний |

### 5.2. Web search tools
| Tool | Описание |
|---|---|
| `search_web` | Поиск в интернете через SerpApi |
| `search_youtube` | Поиск YouTube-видео |
| `fetch_url` | Загрузить и извлечь текст веб-страницы |
| `research_topic` | Комбинированный: поиск + чтение нескольких страниц |

### 5.3. Memory tools
| Tool | Описание |
|---|---|
| `remember_fact` | Запомнить факт о пользователе |
| `remember_project_note` | Запомнить заметку о проекте |
| `list_memories` | Просмотр сохранённой информации |
| `search_memories` | Поиск по памяти |

### 5.4. File tools
| Tool | Описание |
|---|---|
| `read_project_file` | Чтение файла/директории проекта |
| `search_project_code` | Поиск текста в файлах проекта |
| `propose_file_patch` | Показать текущее содержимое + инструкцию (без изменений) |
| `apply_file_patch` | Применить патч (только после подтверждения) |
| `update_config` | Обновить .env переменную |

### 5.5. Operator tools
| Tool | Описание |
|---|---|
| `analyze_projects` | Анализ проектов: проблемы, рекомендации |
| `suggest_schedules` | Предложить расписания для проектов без них |
| `create_followup_task` | Создать followup-задачу |
| `list_auto_tasks` | Список созданных задач |
| `delete_runs` | Удаление запусков по фильтрам (project_id, статусы, ID) с двухшаговым подтверждением |

---

## 6. Память (memory system)

### 6.1. Типы памяти

| Тип | Файл | Назначение |
|---|---|---|
| ProfileMemory | user_profile.json | Имя, предпочтения |
| UserFactsMemory | user_facts.json | Факты о пользователе (долгая) |
| ProjectNotesMemory | project_notes.json | Заметки о проектах (глобальные) |
| ProjectMemoryStore | project_memory.json | Знания о проектах (долгая, структурированная) |
| DecisionsLog | decisions_log.jsonl | Журнал решений агента |
| ResearchCache | research_cache.json | Кэш результатов исследований |
| SessionMemory | sessions/\<id\>.json | Per-session история диалога |

### 6.2. MemoryManager

Центральный класс, объединяет все типы памяти.

**Методы:**
- `get_session()` — получить/создать сессию
- `build_system_prompt()` — собрать system prompt из profile + facts + project notes + project memory
- `remember_fact(key, value)` — запомнить факт
- `remember_project_note(project_id, key, value)` — запомнить о проекте
- `list_memories(scope)` — показать воспоминания (user/projects/decisions/all)
- `search_memories(query)` — поиск по памяти (keyword match)

---

## 7. UI: устойчивость к reload

Правая панель Маршала переживает обновление страницы благодаря трём механизмам:

1. **localStorage persistence:** при каждом изменении `state.messages`, `state.eventTrace`, `state.sessionId`, draft — пишется snapshot в `marshrutka_agent_state`. При загрузке страницы восстанавливается.
2. **Серверный state backup:** `sendBeacon` на `/api/agent/state/save` при `beforeunload`. При старте опционально загружается с сервера через `/api/agent/state/load`.
3. **Client-side navigation:** SPA-like переходы между страницами не перезагружают AI панель.

### Восстанавливается:
- история сообщений (messages[])
- eventTrace[]
- sessionId
- draft текста в input (если был)
- open/closed состояние панели
- **suggestions**: кнопки быстрых ответов (если не были использованы); после клика `suggestionsUsed = true` и кнопки не восстанавливаются

---

## 8. Voice mode

### Текущее состояние: stub

Кнопка 🎤 в панели показывает toast "Voice mode coming soon". Полноценная реализация требует настройки STT_HTTP_URL в `.env`.

### Бэкенд

`POST /api/agent/transcribe` — принимает `multipart/form-data` с полем `file`, отправляет на `STT_HTTP_URL` (faster-whisper), возвращает `{"text": "...", "language": "ru", "duration": 1.0}`.

### Планируемый flow
1. Нажать 🎤 — начать запись (MediaRecorder API)
2. Повторное нажатие — остановить
3. Аудио отправляется на `/api/agent/transcribe`
4. Распознанный текст отправляется в чат

---

## 9. Self-edit / Project assist

Controlled flow для редактирования файлов:

1. Агент вызывает `propose_file_patch(path, instruction)` — показывает текущее содержимое
2. Пользователь видит предложение в чате
3. После подтверждения агент вызывает `apply_file_patch(path, patch)` — применяет изменения

**Правило:** агент НЕ может применять патчи без явного шага подтверждения. Это контролируется на уровне system prompt и инструментов.

---

## 10. Markdown rendering

Ответы ассистента рендерятся через Marked.js (CDN).

**Поддерживается:**
- `**жирный**`, `*курсив*`
- заголовки h1-h4
- маркированные и нумерованные списки
- `inline code` и code blocks с pre
- ссылки
- blockquote
- таблицы (GFM)
- горизонтальные разделители

**Fallback:** если marked.js не загружен (offline), рендеринг как plain text через textContent.

---

## 11. Добавление нового инструмента

1. Написать функцию в соответствующем файле (`tools.py`, `file_tools.py`, `research.py`, `operator_tools.py`)
2. Добавить в словарь `TOOLS` в `tools.py`
3. Добавить `ToolDefinition` в список `TOOL_DEFINITIONS` в `tools.py`
4. Если нужно читаемое summarization — добавить кейс в `_summarize_result()` в `harness.py`
5. Обновить `BASE_SYSTEM_PROMPT` в `memory.py`
6. Перезапустить сервер

---

## 12. Конфигурация

Переменные окружения (`.env`):

```bash
# LLM (обязательно)
ROUTERAI_BASE_URL=https://routerai.ru/api/v1
ROUTERAI_API_KEY=sk-your-key
ROUTERAI_MODEL=deepseek/deepseek-v4-flash

# Web search (опционально — без ключа поиск возвращает "не настроен")
SERPAPI_API_KEY=your_serpapi_key

# STT (опционально — без ключа голосовой ввод не работает)
STT_HTTP_URL=http://141.136.44.9:9000/transcribe
```

---

## 13. Известные ограничения

- **Tool calls** — нестриминговые. При большом количестве шагов пользователь ждёт.
- **Финальный ответ** — отдаётся целиком (message_done), без token-by-token стриминга.
- **Suggestions генерируются отдельным LLM-вызовом** — добавляет 1–3 с латентности к каждому ответу. В будущем можно заменить на быстрый эвристический триггер.
- **delete_runs** — двухшаговое подтверждение на уровне инструмента, без дополнительной авторизации.
- **Markdown rendering** — использует marked.js (CDN). Без интернета библиотека недоступна, будет plain text.
- **Voice** — в разработке (stub). После настройки STT_HTTP_URL будет работать через faster-whisper.
- **Web search** — зависит от SerpApi. Без API ключа поиск недоступен.
- **Файловая память** — без БД. При сотнях сессий может быть медленной запись на диск.
- **Нет векторного поиска** — только keyword matching в памяти.
- **Memory tools (remember_fact и др.)** — не в `TOOLS` dict, а в `MEMORY_TOOLS`, обрабатываются отдельно в `execute_tool`.
