# Руководство по получению доступа к API публикаций

> Marshrutka — publishing access setup.
> Для оператора, который хочет получить рабочие ключи и подключить публикацию.

---

## Содержание

1. [Общая схема](#1-общая-схема)
2. [YouTube](#2-youtube)
3. [Instagram](#3-instagram)
4. [VK Video](#4-vk-video)
5. [Rutube](#5-rutube)
6. [Проверка подключения](#6-проверка-подключения)
7. [Типовые ошибки](#7-типовые-ошибки)
8. [Сроки истечения и обновление](#8-сроки-истечения-и-обновление)
9. [Ограничения платформ](#9-ограничения-платформ)

---

## 1. Общая схема

Marshrutka не хранит ваши ключи где-то ещё, кроме локального `data/publish_profiles.json`.
Это personal-use инструмент — никакие credentials не уходят на внешние серверы (кроме прямых API-вызовов к платформам).

**Что нужно сделать в общем случае:**
1. Создать/настроить аккаунт на платформе
2. Зарегистрировать приложение в developer-консоли платформы
3. Получить credentials (client_id, client_secret, api_key, access_token)
4. Создать профиль публикации в Marshrutka (`/publish/profiles/new`)
5. Вставить credentials в поле `Credentials JSON`
6. Привязать профиль к проекту

**Статусы готовности в Marshrutka:**
- `✓ готово` — функциональность реализована и работает
- `скоро` — интерфейс есть, API-адаптер в разработке
- `вручную` — требуется ручная настройка на стороне платформы

---

## 2. YouTube

### 2.1. Какой аккаунт нужен

Аккаунт Google с активным YouTube-каналом.
Для загрузки Shorts нужен канал без ограничений (верификация через телефон).

### 2.2. Статус поддержки в Marshrutka

| Функция | Статус |
|---|---|
| UI профиля и настройки | `✓ готово` |
| Привязка к проекту | `✓ готово` |
| Создание publish request | `✓ готово` |
| OAuth-авторизация | `скоро` |
| Реальная загрузка видео через API | `скоро` |
| Настройка OAuth consent screen | `вручную` |

### 2.3. Пошаговая инструкция получения доступа

#### Шаг 1: Создать проект в Google Cloud Console

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект (или выберите существующий)
3. Перейдите в **APIs & Services > Library**
4. Найдите **YouTube Data API v3** и нажмите **Enable**

#### Шаг 2: Настроить OAuth consent screen

1. Перейдите в **APIs & Services > OAuth consent screen**
2. Выберите **External** (для личного использования)
3. Заполните:
   - App name: `Marshrutka` (или любое название)
   - User support email: ваш email
   - Developer contact email: ваш email
4. Нажмите **Save and Continue**
5. Scopes: нажмите **Add or Remove Scopes**, добавьте:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube`
   - `https://www.googleapis.com/auth/youtubepartner`
6. Нажмите **Save and Continue**
7. Test users: добавьте свой email
8. Нажмите **Save and Continue**

> Важно: для publishing статус приложения можно оставить **Testing**.
> В этом режиме до 100 тестовых пользователей могут использовать приложение без верификации.

#### Шаг 3: Создать OAuth 2.0 Client ID

1. Перейдите в **APIs & Services > Credentials**
2. Нажмите **Create Credentials > OAuth client ID**
3. Application type: **Desktop app** (или **Web application**)
4. Name: `Marshrutka YouTube`
5. Если выбрали Web application, добавьте:
   - Authorized redirect URIs: `http://localhost:9090` (если Marshrutka работает на локальном порту)
6. Нажмите **Create**
7. Нажмите **Download JSON** — сохраните файл

#### Шаг 4: Создать профиль в Marshrutka

1. Откройте `/publish/profiles/new`
2. Выберите платформу **YouTube**
3. Название: `YouTube — основной`
4. Откройте скачанный `client_secret.json` в текстовом редакторе
5. Скопируйте всё содержимое в поле **Credentials JSON**
6. Заполните **Channel title** (название канала) и **Channel ID** (можно найти в URL канала: `https://www.youtube.com/channel/UC...`)
7. Настройте шаблоны:
   - **Title template**: `{{ title }} — Marshrutka Shorts`
   - **Description template**: оригинальное описание
   - **Tags**: через запятую
   - **Visibility**: `public`, `unlisted` или `private`
8. Сохраните профиль

#### Шаг 5: Привязать к проекту

1. Откройте `/projects/{project_id}/edit`
2. В разделе **Publish profiles** выберите созданный профиль
3. Установите его как профиль по умолчанию, если нужно

### 2.4. Какие поля нужно вставить

| Поле профиля | Что вставлять |
|---|---|
| `display_name` | Любое удобное название |
| `platform` | `youtube` |
| `credentials` | Содержимое `client_secret.json` — JSON-объект с полями `web`/`installed`, `client_id`, `client_secret`, `redirect_uris` |
| `channel_title` | Название вашего YouTube-канала |
| `channel_id` | ID канала (начинается с `UC`) |
| `title_template` | Шаблон заголовка: `{{ title }}` |
| `description_template` | Шаблон описания |
| `tags_defaults` | Теги через запятую |

### 2.5. Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `invalid_client` | Неправильный client_id или client_secret | Проверьте credentials из скачанного JSON |
| `access_denied` | Пользователь не добавлен в test users | Добавьте email в OAuth consent screen > Test users |
| `quota_exceeded` | Превышена квота YouTube Data API | Квота: 10 000 единиц/день. Проверьте Usage в Google Cloud |
| `channel_not_found` | Неправильный channel_id | Проверьте URL канала |

### 2.6. Срок действия

- **OAuth client credentials**: не истекают (если не отозваны)
- **Refresh token**: истекает через 7 дней для непроверенных приложений. Для production (verified) — не истекает.
- **Access token**: 1 час. Marshrutka должна использовать refresh token для обновления.

---

## 3. Instagram

### 3.1. Какой аккаунт нужен

Профессиональный аккаунт Instagram (Business или Creator), связанный с Facebook-страницей.
Обычный личный аккаунт НЕ подходит.

### 3.2. Статус поддержки в Marshrutka

| Функция | Статус |
|---|---|
| UI профиля и настройки | `✓ готово` |
| UI для создания профиля Instagram | `✓ готово` |
| API-адаптер для публикации Reels | `скоро` |
| Настройка Meta-приложения и токенов | `вручную` |

### 3.3. Пошаговая инструкция получения доступа

#### Шаг 1: Перевести аккаунт в профессиональный

В Instagram: **Settings > Account > Switch to professional account**.
Выберите категорию (Creator или Business).

#### Шаг 2: Создать приложение в Meta for Developers

1. Откройте [Meta for Developers](https://developers.facebook.com/)
2. Нажмите **My Apps > Create App**
3. Выберите **Business** (для Instagram API)
4. Название: `Marshrutka Instagram`
5. Нажмите **Create App**

#### Шаг 3: Добавить Instagram Graph API

1. В панели приложения: **Add Product > Instagram Graph API > Set Up**
2. В разделе **Generate Access Token** нажмите **Generate Token**
3. Разрешите доступ (потребуется войти в Facebook)

#### Шаг 4: Получить долгоживущий токен

Краткосрочный токен (1 час) нужно обменять на долгоживущий (60 дней):

```
GET https://graph.facebook.com/v18.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={app_id}
  &client_secret={app_secret}
  &fb_exchange_token={short_lived_token}
```

Ответ:
```json
{
  "access_token": "long_lived_token",
  "token_type": "bearer",
  "expires_in": 5184000
}
```

#### Шаг 5: Получить Instagram Business Account ID

```
GET https://graph.facebook.com/v18.0/me/accounts
  ?access_token={long_lived_token}
```

Найдите страницу, связанную с Instagram, затем:

```
GET https://graph.facebook.com/v18.0/{page_id}?fields=instagram_business_account&access_token={long_lived_token}
```

Запишите `instagram_business_account.id`.

### 3.4. Какие поля нужно вставить

| Поле профиля | Что вставлять |
|---|---|
| `display_name` | `Instagram — Reels` |
| `platform` | `instagram` |
| `credentials` | `{"access_token": "...", "app_id": "...", "instagram_account_id": "..."}` |
| `channel_title` | Имя вашего Instagram-аккаунта |
| `channel_id` | Instagram Business Account ID (число) |

### 3.5. Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `Invalid OAuth 2.0 access token` | Токен истёк или невалиден | Обновите токен |
| `(#10) Application does not have permission for this action` | Не настроены права приложения | Проверьте продукты в Meta App |
| `(#100) Parameter error` | Неверный Instagram Account ID | Проверьте ID через Graph API Explorer |
| `Account not connected` | Instagram не связан с Facebook-страницей | Проверьте в настройках Instagram |

### 3.6. Срок действия

- **Краткосрочный токен**: 1 час
- **Долгоживущий токен**: 60 дней. Нужно обновлять каждые 60 дней.
- **App Secret**: не истекает.

---

## 4. VK Video

### 4.1. Какой аккаунт нужен

Аккаунт ВКонтакте. Для публикации в сообщество — права администратора/редактора.

### 4.2. Статус поддержки в Marshrutka

| Функция | Статус |
|---|---|
| Интерфейс профилей VK | `✓ готово` |
| UI для настройки | `✓ готово` |
| API video.save + video.get | `скоро` |
| Создание приложения и токен | `вручную` |

### 4.3. Пошаговая инструкция получения доступа

#### Шаг 1: Создать Standalone-приложение VK

1. Откройте [dev.vk.com](https://dev.vk.com/)
2. Нажмите **Create App**
3. **Название**: `Marshrutka Video`
4. **Платформа**: **Web** или **Standalone** (для получения токена через Implicit Flow)
5. Нажмите **Connect**

#### Шаг 2: Получить App ID

Сразу после создания — ID приложения (число) отображается в заголовке страницы.
Запишите его — это `app_id`.

#### Шаг 3: Получить Access Token (Implicit Flow)

Откройте в браузере:
```
https://oauth.vk.com/authorize
  ?client_id={app_id}
  &display=page
  &redirect_uri=https://oauth.vk.com/blank.html
  &scope=video,offline
  &response_type=token
  &v=5.199
```

После подтверждения — URL в адресной строке будет содержать `access_token`:

```
https://oauth.vk.com/blank.html#access_token=TOKEN&expires_in=0&user_id=...
```

**Важно:** `scope=video,offline` — `offline` даёт бессрочный токен.
`expires_in=0` означает, что токен не истекает (благодаря `offline` scope).

#### Шаг 4: Получить ID сообщества (если нужно)

Для публикации в группу:
```
https://api.vk.com/method/groups.getById
  ?group_id={group_short_name}
  &access_token={token}
  &v=5.199
```

ID сообщества будет отрицательным числом (например, `-12345678`).
Для публикации от имени пользователя передавайте `owner_id` = `user_id`.

### 4.4. Какие поля нужно вставить

| Поле профиля | Что вставлять |
|---|---|
| `display_name` | `VK — Клипы` |
| `platform` | `vk_video` |
| `credentials` | `{"access_token": "...", "app_id": 12345678, "owner_id": -12345678}` |
| `channel_title` | Название сообщества или страницы |
| `channel_id` | owner_id (отрицательное число для группы) |

### 4.5. Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `invalid_access_token` | Токен неправильный или отозван | Получите новый токен |
| `access_denied` | Нет прав video | Убедитесь, что scope включает video |
| `Flood control` | Слишком частые запросы | Подождите 1-2 секунды между запросами |
| `Not enough rights` | Нет прав на публикацию в сообществе | Проверьте права администратора |

### 4.6. Срок действия

- **Токен с `offline`**: бессрочный (не истекает)
- **Токен без `offline`**: 1 день
- **Ключ доступа приложения** (серверный): не истекает
- **VK API версии**: рекомендуется `5.199`

---

## 5. Rutube

### 5.1. Какой аккаунт нужен

Аккаунт на Rutube с подтверждённым каналом.

### 5.2. Статус поддержки в Marshrutka

| Функция | Статус |
|---|---|
| Интерфейс профилей Rutube | `✓ готово` |
| UI для настройки | `✓ готово` |
| API-адаптер | `скоро` |
| Получение API-ключа | `вручную` |

### 5.3. Пошаговая инструкция получения доступа

#### Шаг 1: Получить API-ключ Rutube

1. Войдите в аккаунт на [Rutube](https://rutube.ru/)
2. Перейдите в **Настройки канала**
3. Найдите раздел **API / Интеграции** (или **Доступ по API**)
4. Нажмите **Получить API-ключ**
5. Скопируйте ключ

Если раздел API не отображается:
- Канал должен быть подтверждён
- Нужно заполнить основные настройки канала
- Возможно, потребуется верификация

#### Шаг 2: Получить ID канала

ID канала обычно виден в URL канала:
```
https://rutube.ru/channel/{channel_id}/
```

Или:
1. Перейдите на страницу своего канала
2. Посмотрите в URL — это будет строка после `/channel/`

### 5.4. Какие поля нужно вставить

| Поле профиля | Что вставлять |
|---|---|
| `display_name` | `Rutube — Shorts` |
| `platform` | `rutube` |
| `credentials` | `{"api_key": "ваш_api_ключ"}` |
| `channel_title` | Название канала на Rutube |
| `channel_id` | ID канала (из URL) |

### 5.5. Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `Invalid API key` | Неправильный ключ | Проверьте ключ в настройках канала |
| `Access denied` | Ключ не активирован | Проверьте настройки API в канале |
| `Channel not found` | Неправильный channel_id | Проверьте URL канала |
| `Quota exceeded` | Превышен лимит запросов | Дождитесь сброса квоты (обычно 24 часа) |

### 5.6. Срок действия

- **API-ключ**: не истекает (если не отозван вручную)
- **Канал**: бессрочно
- **Ограничения**: могут быть изменены Rutube в любой момент

---

## 6. Проверка подключения

### 6.1. Через UI Marshrutka

1. Откройте `/publish/profiles`
2. Проверьте статус профиля:
   - `✓ готов к использованию` — база заполнена
   - `требует настройки` — не хватает данных
3. Если профиль готов — откройте его для редактирования, проверьте поля

### 6.2. Через health-проверку

Откройте `/api/health` — если приложение отвечает, всё работает.

### 6.3. Через тестовый publish request (когда API-адаптеры готовы)

1. Создайте тестовый run
2. На странице run details нажмите **Опубликовать**
3. Выберите профиль
4. Проверьте статус ответа

---

## 7. Типовые ошибки

### 7.1. Профиль не сохраняется

- Проверьте, что `display_name` не пустой
- Проверьте, что `platform` выбран из списка
- Credentials JSON должен быть валидным JSON

### 7.2. Статус профиля «требует настройки»

Профиль считается готовым (`is_ready = true`), если:
- Заполнен `channel_title` или
- Заполнены `credentials`

Если оба пусты — статус будет `требует настройки`.

### 7.3. Профиль не отображается в проекте

- Проверьте, что профиль привязан к проекту (`/projects/{id}/edit`)
- Проверьте, что профиль включён (`enabled = true`)

### 7.4. Publish request создаётся, но статус не меняется

- API-адаптеры ещё не реализованы — статус останется `pending`
- Следите за обновлениями Marshrutka

---

## 8. Сроки истечения и обновление

| Платформа | Что истекает | Срок | Как обновить |
|---|---|---|---|
| YouTube | Refresh token | 7 дней (testing) / бессрочно (verified) | Перенастроить OAuth |
| YouTube | Access token | 1 час | Автоматически через refresh token |
| Instagram | Long-lived token | 60 дней | Обновить до истечения |
| VK | Token без offline | 1 день | Получить новый с `offline` scode |
| VK | Token с offline | Бессрочно | Не требуется |
| Rutube | API key | Не истекает | Только если отозван |

### Как обновлять доступ

**YouTube:**
1. Если refresh token истёк — нужно заново пройти OAuth flow
2. В Marshrutka: отредактируйте профиль, обновите credentials

**Instagram:**
1. Обновляйте токен каждые 50-55 дней
2. Используйте `GET /oauth/access_token?grant_type=fb_exchange_token&client_id=...&client_secret=...&fb_exchange_token=...`
3. В Marshrutka: отредактируйте профиль, обновите credentials

**VK:**
1. Если токен без `offline` — получите новый через Implicit Flow
2. В Marshrutka: отредактируйте профиль, обновите credentials

**Rutube:**
1. Только если ключ отозван — получить новый в настройках канала
2. В Marshrutka: отредактируйте профиль, обновите credentials

---

## 9. Ограничения платформ

### YouTube

| Ограничение | Значение |
|---|---|
| Квота YouTube Data API | 10 000 единиц/день |
| Макс. размер видео | 256 ГБ |
| Макс. длина видео | 12 часов |
| Shorts макс. длина | 60 секунд (горизонталь) / 3 минуты (вертикаль) |
| Скорость загрузки | зависит от канала |
| Кол-во каналов на аккаунт | 50 |
| Кол-во плейлистов | 200 на канал |
| Кол-во тегов | 500 символов всего |

### Instagram

| Ограничение | Значение |
|---|---|
| Reels макс. длина | 90 секунд |
| Соотношение сторон | 9:16 (вертикаль) |
| Минимальное разрешение | 720p |
| Макс. размер | 650 МБ (MP4) |
| Хештеги | до 30 на пост |
| Токен обновление | каждые 60 дней |
| График публикаций | не более ~50/день |

### VK Video

| Ограничение | Значение |
|---|---|
| Макс. размер видео | 5 ГБ |
| Макс. длина | 12 часов |
| Поддерживаемые форматы | AVI, MP4, 3GP, MPG, MOV, WMV, FLV, MKV, WEBM |
| Клипы макс. длина | 60 секунд |
| Запросы к API | 3 запроса/сек (рекомендуется) |

### Rutube

| Ограничение | Значение |
|---|---|
| Макс. размер видео | 10 ГБ |
| Макс. длина | 6 часов |
| Поддерживаемые форматы | MP4, AVI, MOV, WMV |
| Кол-во видео в день | 50 (рекомендуется не более 10) |
| API-запросы | задокументированные лимиты уточняйте в документации Rutube |

---

> **Примечание:** Данное руководство актуально на дату: 2026-06-08.
> API платформ могут меняться. Если что-то не работает — проверьте актуальную документацию платформы.
