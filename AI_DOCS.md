# AI-агент Маршал — документация

> Версия: 1.0 | Последнее обновление: 2026-06-08

---

## 1. Обзор

Маршал — встроенный AI-ассистент Marshrutka. Работает в правой панели интерфейса на всех страницах, использует OpenAI-compatible function calling через RouterAI.

**Возможности:**
- написание и редактирование текстов с автоматической проверкой длины
- работа с проектами Marshrutka (список, статусы, запуск пайплайнов)
- управление расписаниями
- поиск информации в интернете (SerpApi)
- поиск YouTube-видео
- multi-step reasoning — может выполнять несколько инструментов подряд для решения сложных запросов

---

## 2. Архитектура

### 2.1. Схема взаимодействия

```
Браузер (vanilla JS)                     FastAPI backend
┌─────────────────┐     SSE stream      ┌──────────────────────┐
│  agent-chat.js   │ ◄──────────────── │  agent/router.py     │
│  (EventSource)   │    event: token    │                      │
│                  │    event: tool_*   │  agent/harness.py    │
│  agent-chat.css  │    event: done     │  (tool loop)         │
└─────────────────┘                    └──────┬───────────────┘
                                              │
                                    ┌─────────▼──────────────┐
                                    │  OpenAI-compatible API  │
                                    │  (RouterAI)             │
                                    └────────────────────────┘
```

### 2.2. Файловая структура

```
agent/
├── __init__.py      # Re-exports: MemoryManager, run_harness, agent_router
├── harness.py       # Tool-calling loop, LLM calls, SSE event generation
├── memory.py        # MemoryManager, SessionMemory, ProfileMemory, system prompt
├── models.py        # Pydantic: SSEEvent, ToolDefinition, ChatRequest
├── router.py        # FastAPI routes: POST /chat, GET /context, POST /memory, DELETE /history
├── session.py       # session_id validation (regex allowlist)
├── tools.py         # Tool implementations + TOOLS dict + TOOL_DEFINITIONS
└── web_tools.py     # search_web, search_youtube via SerpApi

static/
├── agent-chat.js    # Chat client: SSE handling, copy dialog/trace, tool display
└── agent-chat.css   # Chat-specific styles (messages, tool events, buttons)

data/agent/
├── user_profile.json    # Global user profile (name, preferences, notes)
├── project_notes.json   # Shared project notes
└── sessions/            # Per-session chat history (*.json)
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

**Ошибки:**
- 422 — невалидный `session_id` (не подходит под формат `[a-zA-Z0-9_-]{8,64}`)
- 422 — сообщение длиннее 8000 символов

### 3.2. GET /api/agent/context

Получить контекст системы и сессии.

**Query parameters:**
- `session_id` — опционально. Если передан и валиден, возвращает историю сессии.

**Response (без session_id):**
```json
{
  "session_id": null,
  "user_context": { "name": "", "preferences": [], "notes": [] },
  "history_count": 0,
  "project_count": 2,
  "projects": [
    { "project_id": "story-to-video", "display_name": "Story to Video", "enabled": true }
  ]
}
```

**Response (с session_id):**
```json
{
  "session_id": "abc123def456",
  "user_context": { ... },
  "history_count": 5,
  "project_count": 2,
  "projects": [ ... ]
}
```

### 3.3. POST /api/agent/memory

Обновить user profile (глобально).

**Request:**
```json
{
  "key": "name",
  "value": "Александр"
}
```

### 3.4. DELETE /api/agent/history

Очистить историю конкретной сессии + сбросить in-memory cache.

**Query parameters:**
- `session_id` — обязательный.

**Ошибки:**
- 422 — `session_id` не передан
- 422 — невалидный `session_id`

---

## 4. SSE протокол

Именованные события (event:) с JSON payload в data:.

### 4.1. Событие `session`

Первое событие в стриме. Содержит ID сессии.

```
event: session
data: {"type": "session", "session_id": "abc123def456"}
```

### 4.2. Событие `message_start`

Сигнализирует начало формирования ответа.

```
event: message_start
data: {"type": "message_start"}
```

### 4.3. Событие `token`

Отдельный токен стриминга (зарезервировано для будущего token-by-token streaming).

```
event: token
data: {"type": "token", "content": "Привет"}
```

### 4.4. Событие `tool_start`

Агент вызывает инструмент. Появляется перед выполнением.

```
event: tool_start
data: {"type": "tool_start", "tool_name": "count_words", "arguments": {"text": "..."}}
```

### 4.5. Событие `tool_result`

Результат выполнения инструмента.

```
event: tool_result
data: {"type": "tool_result", "tool_name": "count_words", "result_summary": "5 слов, 25 символов", "duration_ms": 123}
```

Поля:
- `tool_name` — имя инструмента
- `result_summary` — человекочитаемый результат для UI
- `duration_ms` — время выполнения в миллисекундах

### 4.6. Событие `message_done`

Финальный полный ответ ассистента.

```
event: message_done
data: {"type": "message_done", "content": "Вот ваш текст про кофейню..."}
```

### 4.7. Событие `error`

Ошибка. Без traceback, только безопасное сообщение.

```
event: error
data: {"type": "error", "message": "Внутренняя ошибка. Попробуйте ещё раз."}
```

### 4.8. Событие `done`

Завершение стрима. Всегда последнее.

```
event: done
data: {"type": "done"}
```

### 4.9. Формат в SSE (raw wire)

```
event: session
data: {"type": "session", "session_id": "abc123"}

event: message_start
data: {"type": "message_start"}

event: tool_start
data: {"type": "tool_start", "tool_name": "count_words", "arguments": {"text": "..."}}

event: tool_result
data: {"type": "tool_result", "tool_name": "count_words", "result_summary": "5 слов", "duration_ms": 42}

event: message_done
data: {"type": "message_done", "content": "Готово!"}

event: done
data: {"type": "done"}
```

---

## 5. Инструменты (tools)

### 5.1. Marshrutka tools

Определены в `agent/tools.py`. Все инструменты синхронные (кроме `run_pipeline`).

| Tool | Описание | Параметры | Результат |
|---|---|---|---|
| `count_words` | Подсчёт слов, символов, предложений в тексте | `text: str` | `{word_count, char_count, sentence_count, status}` |
| `get_projects` | Список всех проектов | — | `{projects: [...], count}` |
| `get_recent_runs` | Последние запуски | `project_id: str?`, `limit: int?` | `{runs: [...], count}` |
| `run_pipeline` | Запуск пайплайна (async) | `project_id: str`, `input_data: dict?` | `{run_id, status, project_id}` |
| `create_schedule` | Создание cron-расписания | `project_id: str`, `cron_expression: str`, `title: str?` | `{schedule_id, project_id, cron, status}` |
| `get_schedules` | Список расписаний | `project_id: str?` | `{schedules: [...], count}` |

### 5.2. Web search tools

Определены в `agent/web_tools.py`. Используют SerpApi (Google Search).

#### search_web

```python
def search_web(query: str, num_results: int = 5) -> dict
```

Поиск информации в интернете.

- `query` — поисковый запрос
- `num_results` — количество результатов, 1-10 (по умолчанию 5)

**Успешный ответ:**
```json
{
  "query": "openai function calling",
  "results": [
    {
      "title": "OpenAI Function Calling",
      "url": "https://example.com/...",
      "snippet": "Function calling позволяет модельям..."
    }
  ]
}
```

**Без API key:**
```json
{"error": "SerpApi не настроен"}
```

**Ошибка сети/сервера:**
```json
{"error": "Ошибка интернет-поиска"}
```

#### search_youtube

```python
def search_youtube(query: str, num_results: int = 5) -> dict
```

Поиск YouTube-видео через `site:youtube.com/watch` в Google Search.

- `query` — поисковый запрос
- `num_results` — количество результатов, 1-10

Фильтрует только ссылки на `youtube.com/watch` и `youtu.be/`, исключая каналы, плейлисты и shorts.

**Успешный ответ:**
```json
{
  "query": "turtle documentary",
  "results": [
    {
      "title": "Turtles – The Fascinating World Beneath the Shell",
      "url": "https://www.youtube.com/watch?v=XrkNC2ixjL8",
      "snippet": "A documentary about sea turtles..."
    }
  ]
}
```

### 5.3. Регистрация инструментов

Каждый инструмент регистрируется в двух местах:

1. **Словарь `TOOLS`** (`agent/tools.py`) — для вызова по имени из `execute_tool()`
2. **Список `TOOL_DEFINITIONS`** (`agent/tools.py`) — OpenAI-compatible schema для function calling

```python
TOOLS = {
    "search_web": search_web,  # функция
    ...
}

TOOL_DEFINITIONS = [
    ToolDefinition(
        name="search_web",
        description="...",
        parameters={"type": "object", "properties": {...}},
    ),
    ...
]
```

---

## 6. Tool-calling loop (harness)

`agent/harness.py` — `run_harness()`

### 6.1. Алгоритм

```
1. Загрузить проекты → build_system_prompt
2. Получить историю сессии → messages = [system, ...history, user_message]
3. yield message_start

4. for step in range(max_steps=5):
    5. call_llm(messages, tools=TOOL_DEFS)
    6. If model вернула tool_calls:
       - Добавить assistant message с tool_calls
       - Для каждого tool_call:
         - yield tool_start
         - execute_tool() + замерить duration_ms
         - yield tool_result
         - Добавить tool message
       - Повторить шаг 4
    7. Если model не вернула tool_calls → final_content = content, break
   else:
     final_content = "(агент не смог сформировать ответ)"

8. yield message_done {content: final_content}
9. Сохранить user + assistant в session memory
```

### 6.2. LLM calls

**call_llm** — нестриминговый вызов с tools. Используется для tool-calling loop.
```python
msg = await call_llm(messages, tools=TOOL_DEFS, stream=False)
# msg == {"content": "...", "tool_calls": [...]}
```

**call_llm_stream** — стриминговый вызов без tools (зарезервирован для будущего token-by-token streaming).
```python
async for token in call_llm_stream(messages):
    yield SSEEvent(type="token", data={"content": token})
```

### 6.3. Summarize result

`_summarize_result(result)` — преобразует tool result в короткую строку для UI:

| Тип результата | Пример summarization |
|---|---|
| error | `"ошибка: ..."` |
| word_count | `"5 слов, 25 символов"` |
| projects | `"2 проектов"` |
| runs | `"3 запусков"` |
| run_id | `"запуск launch_abc — linked"` |
| schedule_id | `"расписание sched_123"` |
| schedules | `"2 расписаний"` |
| results (search) | `"найдено 5 результатов по запросу «turtle»"` |
| прочее | `"выполнено"` |

---

## 7. Память (memory system)

### 7.1. Структура

```
MemoryManager
├── ProfileMemory     → data/agent/user_profile.json     (глобальный)
├── ProjectNotesMemory → data/agent/project_notes.json   (глобальный)
└── _sessions (OrderedDict[str, SessionMemory])
    └── SessionMemory → data/agent/sessions/<id>.json    (per-session)
```

### 7.2. ProfileMemory

Глобальный профиль пользователя. Хранится в `data/agent/user_profile.json`.

```json
{
  "name": "Александр",
  "preferences": ["лаконичные ответы", "cильные заголовки"],
  "notes": ["использует проект story-to-video для новостей"]
}
```

Методы:
- `get_context_text()` — форматирует в текст для system prompt
- `update(key, value)` — сохраняет атомарно (temp file + replace)

### 7.3. SessionMemory

Per-session история диалога. Хранится в `data/agent/sessions/<session_id>.json`.

```json
{
  "messages": [
    {"role": "user", "content": "напиши текст", "timestamp": "..."},
    {"role": "assistant", "content": "Вот текст...", "timestamp": "..."}
  ],
  "created_at": "2026-06-08T12:00:00"
}
```

Параметры:
- `MAX_HISTORY = 20` — максимальное количество сохраняемых сообщений
- `RECENT_WINDOW = 10` — сколько последних сообщений отдаётся модели

Методы:
- `add_message(role, content)` — добавить + атомарно сохранить + обрезать до MAX_HISTORY
- `get_recent(n=10)` — последние n сообщений для контекста модели
- `clear()` — очистить историю

### 7.4. ProjectNotesMemory

Глобальные заметки о проектах. Хранится в `data/agent/project_notes.json`.

```json
{
  "story-to-video": "Пайплайн для новостей",
  "ezhu-ponyatno": "Пайплайн для YouTube-разборов"
}
```

### 7.5. MemoryManager

Центральный класс-менеджер.

**Методы:**

| Метод | Описание |
|---|---|
| `get_session(session_id=None)` | Получить (или создать) SessionMemory по ID. Если ID не указан — генерирует новый. |
| `drop_session(session_id)` | Удалить in-memory cache сессии |
| `build_system_prompt(projects)` | Собрать system prompt из всех источников |

**Кэширование:** OrderedDict с LRU eviction, максимум 100 кэшированных сессий.
При превышении evict-ится самая давно неиспользованная.

**System prompt builder** собирает:
1. `BASE_SYSTEM_PROMPT` — базовые инструкции
2. Список проектов (id, display_name, enabled)
3. User profile (если есть)
4. Project notes (если есть)

---

## 8. System prompt

Базовый system prompt находится в `agent/memory.py:BASE_SYSTEM_PROMPT`.

```
Ты — Маршал, AI-ассистент инструмента Marshrutka для запуска контентных пайплайнов.

Твои возможности:
- Отвечать на вопросы про контент (написать текст, придумать тему, проверить длину)
- Работать с проектами: смотреть список, последние запуски, статусы
- Запускать пайплайны проектов через инструменты
- Создавать расписания для проектов
- Проверять результаты своей работы через инструменты (харнесс-цикл)
- Искать информацию в интернете через search_web
- Искать видео на YouTube через search_youtube

ВАЖНО:
- Когда нужно выполнить действие — используй инструменты.
- После генерации текста вызови count_words, убедись в правильности длины.
- Если длина не совпадает — скорректируй текст и проверь снова.
- Не выдумывай информацию о проектах — используй get_projects для получения актуальных данных.
- Не говори "у меня нет доступа в интернет" — у тебя есть search_web и search_youtube.
- Если пользователь просит найти ссылки, статьи, новости, референсы — используй search_web.
- Если просит найти YouTube видео — используй search_youtube.
- Не выдумывай ссылки. Используй только реальные результаты из инструментов.
```

Runtime-контекст добавляется динамически:
- список проектов
- user profile
- project notes

---

## 9. Session ID validation

`agent/session.py`

```
Формат: ^[a-zA-Z0-9_-]{8,64}$
```

- только латиница, цифры, дефис, подчёркивание
- длина от 8 до 64 символов
- rejects: `/`, `\`, `..`, пробелы, юникод, пустая строка

**Функции:**
- `validate_session_id(sid)` — возвращает sid или raises ValueError
- `is_valid_session_id(sid)` — возвращает bool

---

## 10. Фронтенд (chat client)

### 10.1. agent-chat.js

Vanilla JS, IIFE. Основной файл логики чата.

**Состояние:**
- `sessionId` — текущий ID сессии
- `isStreaming` — флаг активного запроса (защита от double-send)
- `eventTrace[]` — массив всех SSE событий для debug trace
- `messages[]` — массив {role, content} для копирования диалога

**Функции:**

| Функция | Описание |
|---|---|
| `sendMessage(text)` | Основной цикл: fetch POST → читает SSE stream → рендерит события |
| `sendCurrentMessage()` | Взять текст из textarea, очистить, вызвать sendMessage |
| `copyDialog()` | Сформатировать `messages[]` как `[user]/[assistant]` транскрипт → clipboard |
| `copyTrace()` | Сформатировать `eventTrace[]` + `messages[]` как JSON → clipboard |
| `aiSendQuick(el)` | Отправить quick chip (из ai-chips) |
| `addToolEvent(name, summary)` | Добавить tool event в DOM |
| `showError(message)` | Показать ошибку в DOM |
| `handleOneEvent(type, data)` | SSE event handler (inline в sendMessage) |

**SSE парсинг:**
```javascript
// Чтение именованных SSE событий
while (true) {
  var readResult = await reader.read();
  sseBuffer += decoder.decode(...);
  // парсинг event:/data: пар
  if (line.startsWith('event: ')) eventType = line.slice(7).trim();
  if (line.startsWith('data: ')) handleOneEvent(eventType, line.slice(6));
}
```

**Отображение tool событий:**
- `search_youtube` → иконка ▶
- `search_web` → иконка 🌐
- остальные → иконка ⚙
- строка: `▶ search_youtube найдено 5 результатов по запросу «turtle»`
- если есть `duration_ms` → `(42ms)`

**Защита:**
- input disabled во время active запроса
- `catch` — отображает ошибку в DOM, не прерывает работу
- `lastMessageDone` — если `message_done` получен, не показывать fallback error

### 10.2. agent-chat.css

| Селектор | Назначение |
|---|---|
| `.ai-message` | Контейнер сообщения (user/assistant) |
| `.ai-message .bubble` | Пузырёк сообщения |
| `.ai-message .bubble.streaming::after` | Мигающий курсор (▋) |
| `.ai-tool-event` | Строка tool event |
| `.ai-tool-event .tool-icon` | Иконка инструмента (⚙/🌐/▶) |
| `.ai-error` | Блок ошибки |
| `.ai-actions` | Контейнер action-кнопок |
| `.ai-action-btn` | Кнопка копирования диалога/trace |

### 10.3. HTML-шаблон (base.html)

Правая панель AI-редактора:

```html
<aside class="ai-panel" id="aiPanel">
  <div class="ai-panel-header">
    <div class="title">AI-редактор</div>
    <button onclick="toggleAiPanel()">✕</button>
  </div>
  <div class="ai-panel-body" id="aiChatMessages">
    <!-- welcome + chips -->
  </div>
  <div class="ai-panel-footer">
    <div class="ai-actions">
      <button id="copyDialogBtn" onclick="copyDialog()">📋 Копировать диалог</button>
      <button id="copyTraceBtn" onclick="copyTrace()">🔍 Debug trace</button>
    </div>
    <div class="ai-composer">
      <textarea rows="1" placeholder="Спроси Маршала…"></textarea>
      <button>➤</button>
    </div>
  </div>
</aside>
```

---

## 11. Конфигурация

Переменные окружения (`.env`):

```bash
# LLM (обязательно)
ROUTERAI_BASE_URL=https://routerai.ru/api/v1
ROUTERAI_API_KEY=sk-your-key
ROUTERAI_MODEL=deepseek/deepseek-v4-flash

# Web search (опционально — без ключа поиск return "не настроен")
SERPAPI_API_KEY=your_serpapi_key
```

---

## 12. Добавление нового инструмента

1. Написать функцию в `agent/web_tools.py` или `agent/tools.py`:
   ```python
   def my_tool(param1: str, param2: int = 5) -> dict:
       try:
           return {"result": ...}
       except Exception as e:
           logger.exception(...)
           return {"error": "Ошибка инструмента"}
   ```

2. Добавить в словарь `TOOLS` в `agent/tools.py`:
   ```python
   TOOLS = { ..., "my_tool": my_tool }
   ```

3. Добавить `ToolDefinition` в список `TOOL_DEFINITIONS`:
   ```python
   ToolDefinition(
       name="my_tool",
       description="Описание для модели",
       parameters={...},  # JSON Schema
   )
   ```

4. Если нужно читаемое summarization — добавить кейс в `_summarize_result()` в `agent/harness.py`

5. Обновить `BASE_SYSTEM_PROMPT` в `agent/memory.py`, чтобы модель знала о новом инструменте

6. Перезапустить сервер — инструмент доступен как native function call

---

## 13. Обработка ошибок

| Ситуация | Клиент (SSE/UI) | Сервер (лог) |
|---|---|---|
| LLM не ответил | `error: Внутренняя ошибка` + `done` | `logger.exception` с traceback |
| Tool execution failed | `result_summary: ошибка: Ошибка инструмента` | `logger.exception` с именем и args |
| SerpApi не настроен | `result_summary: ошибка: SerpApi не настроен` | — |
| SerpApi timeout | `result_summary: ошибка: Ошибка интернет-поиска` | `logger.exception` с query |
| Невалидный session_id | HTTP 422 | — |
| Сообщение > 8000 символов | HTTP 422 | — |
| DELETE без session_id | HTTP 422 | — |
| Сетевая ошибка SSE | `❌ Ошибка соединения: {message}` (в DOM) | — |

---

## 14. Известные ограничения

- **Tool calls** — нестриминговые. Модель ждёт полного ответа, потом выполняет инструмент. При большом количестве шагов пользователь ждёт.
- **Финальный ответ** — отдаётся целиком (message_done), без token-by-token стриминга. Код стриминга (call_llm_stream + token events) зарезервирован, но не активен.
- **Web search** — зависит от SerpApi. Без API key поиск недоступен. Результаты не кэшируются.
- **YouTube search** — через Google Search (site:youtube.com/watch). Может пропускать видео, плохо индексированные Google.
- **Память** — только файловая, без БД. При высокой нагрузке (сотни сессий) может быть медленной запись на диск. LRU cache на 100 сессий.
- **Debug trace** — только на фронте (JS-массив). При перезагрузке страницы теряется. Запись на диск не реализована.
- **Quick chips** — очищают историю сообщений на фронте при новом запросе (`messages = []`). Это intentional — каждая быстрая подсказка начинает новый диалог.
