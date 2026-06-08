# AI-агент Маршал — документация

> Версия: 2.0 | Последнее обновление: 2026-06-08

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
- **голосовой ввод**: push-to-talk через браузерный API

---

## 2. Архитектура

### 2.1. Схема взаимодействия

```
Браузер (vanilla JS)                     FastAPI backend
┌──────────────────────┐    SSE stream    ┌──────────────────────┐
│  agent-chat.js        │ ◄────────────── │  agent/router.py     │
│  (marked.js рендер)   │   event: token  │                      │
│  (localStorage кэш)   │   event: tool_* │  agent/harness.py    │
│  (Web Speech API)     │   event: done   │  (tool loop)         │
└──────────────────────┘                 └──────┬───────────────┘
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
├── memory.py         # MemoryManager, все типы памяти, system prompt
├── models.py         # Pydantic: SSEEvent, ToolDefinition, ChatRequest, memory tools
├── router.py         # FastAPI routes: /chat, /context, /memory, /state, /transcribe
├── session.py        # session_id validation
├── tools.py          # Tool implementations + TOOLS dict + TOOL_DEFINITIONS
├── web_tools.py      # search_web, search_youtube via SerpApi
├── research.py       # fetch_url, research_topic — чтение и анализ веб-страниц
├── file_tools.py     # read/write project files, search, propose/apply patches
├── operator_tools.py # analyze_projects, suggest_schedules, create_followup_task
└── voice.py          # Audio transcription via RouterAI Whisper

static/
├── agent-chat.js     # Chat client: SSE, markdown, voice, persistence, modals
└── agent-chat.css    # Полные стили чата (markdown, tool events, voice, modals)

data/agent/
├── user_profile.json      # Глобальный профиль
├── user_facts.json        # Факты о пользователе (долгая память)
├── project_notes.json     # Заметки о проектах
├── project_memory.json    # Знания о проектах (долгая память)
├── decisions_log.jsonl    # Журнал решений
├── research_cache.json    # Кэш результатов исследований
├── agent_jobs.json        # Авто-задачи
├── sessions/              # Per-session chat history
└── states/                # Saved frontend state for reload resilience
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

Загрузить аудиофайл для распознавания речи. Возвращает `{"text": "..."}`.

### 3.8. DELETE /api/agent/history

Очистить историю сессии.

---

## 4. SSE протокол

Именованные события (event:) с JSON payload в data:.

### 4.1. Событие `session`
```
event: session
data: {"type": "session", "session_id": "abc123def456"}
```

### 4.2. Событие `message_start`
```
event: message_start
data: {"type": "message_start"}
```

### 4.3. Событие `token` (зарезервировано для streaming)
```
event: token
data: {"type": "token", "content": "Привет"}
```

### 4.4. Событие `tool_start`
```
event: tool_start
data: {"type": "tool_start", "tool_name": "count_words", "arguments": {"text": "..."}}
```

### 4.5. Событие `tool_result`
```
event: tool_result
data: {"type": "tool_result", "tool_name": "count_words", "result_summary": "5 слов, 25 символов", "duration_ms": 123}
```

### 4.6. Событие `message_done`
```
event: message_done
data: {"type": "message_done", "content": "Вот ваш текст..."}
```

### 4.7. Событие `error`
```
event: error
data: {"type": "error", "message": "Внутренняя ошибка. Попробуйте ещё раз."}
```

### 4.8. Событие `done`
```
event: done
data: {"type": "done"}
```

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

---

## 6. Память (memory system)

### 6.1. Типы памяти

| Тип | Файл | Назначение |
|---|---|---|
| ProfileMemory | user_profile.json | Имя, предпочтения |
| UserFactsMemory | user_facts.json | Факты о пользователе (долгая) |
| ProjectNotesMemory | project_notes.json | Заметки о проектах |
| ProjectMemoryStore | project_memory.json | Знания о проектах (долгая) |
| DecisionsLog | decisions_log.jsonl | Журнал решений агента |
| ResearchCache | research_cache.json | Кэш результатов исследований |
| SessionMemory | sessions/\<id\>.json | Per-session история диалога |

### 6.2. MemoryManager

Центральный класс, объединяет все типы памяти.

**Методы:**
- `get_session()` — получить/создать сессию
- `build_system_prompt()` — собрать system prompt из всех источников
- `remember_fact(key, value)` — запомнить факт
- `remember_project_note(project_id, key, value)` — запомнить о проекте
- `list_memories(scope)` — показать воспоминания
- `search_memories(query)` — поиск по памяти

---

## 7. UI: устойчивость к reload

Правая панель Маршала переживает обновление страницы благодаря:

1. **localStorage persistence**: sessionId, messages[], eventTrace[], draft, panel open/closed
2. **Серверный state backup**: `/api/agent/state/save` и `/api/agent/state/load`
3. **Client-side navigation**: SPA-like переходы между страницами не задевают AI панель
4. **Markdown rendering**: через marked.js с безопасным HTML, подсветкой кода

---

## 8. Voice mode

Push-to-talk через Web Speech API (браузерный MediaRecorder).

Flow:
1. Нажать кнопку 🎤 — начать запись
2. Повторное нажатие — остановить
3. Аудио отправляется на `/api/agent/transcribe`
4. Backend использует RouterAI Whisper для распознавания
5. Распознанный текст отправляется в чат

---

## 9. Self-edit / Project assist

Controlled flow для редактирования файлов:

1. Агент вызывает `propose_file_patch(path, instruction)` — показывает текущее содержимое
2. Пользователь видит предложение в чате
3. После подтверждения агент вызывает `apply_file_patch(path, patch)` — применяет изменения

Никаких молчаливых изменений.

---

## 10. Добавление нового инструмента

1. Написать функцию в соответствующем файле (`tools.py`, `file_tools.py`, `research.py`, `operator_tools.py`)
2. Добавить в словарь `TOOLS` в `tools.py`
3. Добавить `ToolDefinition` в список `TOOL_DEFINITIONS` в `tools.py`
4. Если нужно читаемое summarization — добавить кейс в `_summarize_result()` в `harness.py`
5. Обновить `BASE_SYSTEM_PROMPT` в `memory.py`
6. Перезапустить сервер

---

## 11. Известные ограничения

- **Tool calls** — нестриминговые. При большом количестве шагов пользователь ждёт.
- **Markdown rendering** — использует marked.js (CDN). Без интернета библиотека недоступна, будет plain text.
- **Voice** — зависит от Web Speech API (Chrome/Edge). В Firefox/Safari может быть недоступен.
- **Web search** — зависит от SerpApi. Без API ключа поиск недоступен.
- **Файловая память** — без БД. При сотнях сессий может быть медленной запись на диск.
- **Нет векторного поиска** — только keywoard matching в памяти.
