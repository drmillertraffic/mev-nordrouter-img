# NordRouter Image MCP Server

Локальный Python MCP-сервер, который добавляет в Cline инструменты для
генерации и редактирования изображений через NordRouter API
(`https://nordrouter.net/v1`).

## Возможности

- `generate_image` — генерация изображения по текстовому описанию (с опцией нескольких вариантов).
- `edit_image` — редактирование существующего изображения по инструкции (с опорными изображениями).
- `list_image_models` — список моделей, поддерживающих изображения.
- `batch_generate` — генерация одним промптом сразу на нескольких моделях (параллельно).

## Модели

NordRouter имеет два разных API-контура для изображений, и сервер сам выбирает
нужный в зависимости от модели. Таблица проверена живыми запросами; тот же
набор возвращает `list_image_models` вместе с профилем параметров.

| Модель | Контур | Принимает | Статус |
| --- | --- | --- | --- |
| `google/gemini-3.1-flash-image-preview` | `POST /chat/completions` (Markdown-URL в ответе) | `modalities`, `messages`, `safety_filter` | работает |
| `openai/gpt-image-2` | `POST /images/generations` (`data[*].b64_json`) | `prompt`, `n`, `size`, `quality`, `safety_filter` | работает |
| `bytedance/seedream-5.0-pro` | `POST /images/generations` | — | в `/v1` не провижинена: любой запрос → 400 `invalid_request` |
| `openai/gpt-5.4-nano:fjord`, `search/openai/gpt-5.4-nano:fjord` | — | — | текстовые модели, в `/v1/models` попали ошибочно → 404 |

`generate_image` по умолчанию использует
`google/gemini-3.1-flash-image-preview`.

## Установка

```bash
cd /Users/evmelnik/Documents/aiDev/imgRouter-mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Конфигурация

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

Переменные окружения:

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `NORDROUTER_API_KEY` | Ключ NordRouter API (обязательно) | — |
| `NORDROUTER_BASE_URL` | Базовый URL API | `https://nordrouter.net/v1` |
| `NORDROUTER_TIMEOUT` | Таймаут запроса в секундах | `180` |
| `NORDROUTER_PROJECT_ROOT` | Корень, от которого резолвятся относительные пути изображений | рабочий каталог |
| `NORDROUTER_SAFETY_FILTER` | Фильтр безопасности шлюза; всегда отправляется `false` | `false` |

## Подключение к Cline

Добавьте в настройки MCP Cline
(`~/.cline/data/settings/cline_mcp_settings.json`) запись из
[`mcp_config.json`](mcp_config.json). Там уже прописаны абсолютные пути к
интерпретатору venv и `server.py`, а также `timeout: 180`.

```json
{
  "mcpServers": {
    "mev-nordrouter-img": {
      "command": "/Users/evmelnik/Documents/aiDev/imgRouter-mcp/.venv/bin/python",
      "args": ["/Users/evmelnik/Documents/aiDev/imgRouter-mcp/server.py"],
      "env": {
        "NORDROUTER_API_KEY": "sk-...",
        "NORDROUTER_BASE_URL": "https://nordrouter.net/v1",
        "NORDROUTER_TIMEOUT": "180",
        "NORDROUTER_PROJECT_ROOT": "/Users/evmelnik/Documents/aiDev",
        "NORDROUTER_SAFETY_FILTER": "false"
      },
      "timeout": 180,
      "disabled": false
    }
  }
}
```

> Сервер работает по `stdio`; ключ можно указывать либо в `.env` (git-ignored),
> либо в блоке `env` MCP-конфига.

### Куда сохраняются файлы (важно)

MCP-сервер регистрируется глобально и доступен из любого воркспейса. Путь
в аргументах инструментов резолвится так:

- **Относительный** (`public/images/hero.png`) — от `NORDROUTER_PROJECT_ROOT`.
  По умолчанию здесь стоит общий корень `/Users/evmelnik/Documents/aiDev`,
  поэтому для проекта `landing-kit` указывайте `landing-kit/public/images/hero.png`.
- **Абсолютный** (`/Users/evmelnik/Documents/aiDev/landing-kit/...`) — используется
  как есть, без изменений.

Благодаря общему корню картинки лендинга попадают сразу в нужный проект и их
не нужно переносить вручную.

### Фильтр безопасности шлюза

У NordRouter фильтр безопасности включён на стороне сервера по умолчанию, из-за
чего часть запросов может отклоняться. Этот сервер **всегда** добавляет
`safety_filter` в тело запроса — и в `/chat/completions`, и в
`/images/generations`:

```json
{
  "model": "google/gemini-3.1-flash-image-preview",
  "modalities": ["image", "text"],
  "messages": [...],
  "safety_filter": false
}
```

Значение берётся из `NORDROUTER_SAFETY_FILTER` (по умолчанию `false`). Явное
отключение сделано намеренно: ответственность за содержание промптов несёт
тот, кто вызывает инструменты. Если понадобится вернуть модерацию, поставьте
`NORDROUTER_SAFETY_FILTER=true`.

### Профили моделей и параметры запроса

У моделей разный набор допустимых полей: `openai/gpt-image-2` понимает `size` и
`quality`, а Gemini-модели идут через `chat/completions` и `size` не принимают
вовсе. Лишнее поле шлюз не игнорирует — он отклоняет **весь** запрос с
`invalid_request`, хотя сама модель рабочая.

Поэтому тело запроса собирается по профилю модели (`utils/model_profiles.py`), и
поля, которых нет в профиле, не отправляются никогда. `safety_filter`
присутствует везде, где модель его принимает.

Для незнакомых моделей сервер подстраивается сам: если шлюз ответил 400,
необязательные поля отбрасываются по одному (`quality` → `size` → `n` →
`safety_filter`), а удачная комбинация запоминается до конца сессии — обычно это
одна повторная попытка. `safety_filter` отбрасывается последним, поэтому
модерация отключается всегда, когда модель это позволяет.

Модели с `available: false` отклоняются сразу, без обращения к API:

```
Model 'bytedance/seedream-5.0-pro' cannot generate images: not usable through /v1 …
```

Новая модель добавляется одной записью в `_PROFILES`; незнакомое семейство
подхватывается правилом из `_PREFIX_RULES` и работает по профилю-умолчанию для
своего контура.

## Как вызывать: структура промпта

### `generate_image` — картинка с нуля

| Параметр | Обязательный | Что указывать |
| --- | --- | --- |
| `prompt` | да | Описание картинки (формула ниже) |
| `output_path` | да | Путь относительно корня проекта, например `public/images/hero.png`. Каталоги создаются сами |
| `model` | нет | По умолчанию `google/gemini-3.1-flash-image-preview`. Берите `openai/gpt-image-2`, если нужны `size`/`quality` |
| `size` | нет | Только для `images`-моделей: `1024x1024`, `1024x1536` (портрет), `1536x1024` (баннер) |
| `quality` | нет | Только для `openai/gpt-image-2`: `low`, `medium`, `high`, `auto` |
| `count` | нет | 1–4 варианта; сохраняются как `_v1`, `_v2`, … |

Формула промпта — шесть блоков через запятую:

```
[объект и действие], [стиль/техника], [композиция и ракурс],
[свет и палитра], [фон], [что исключить]
```

Пример:

```
minimalist robot mascot holding a paintbrush, flat vector illustration,
centred full-body composition, soft studio light with pastel mint and lavender,
clean white background, no text, no watermark
```

Практика:

- Пишите по-английски — модели понимают его точнее.
- 1–3 предложения; конкретика вместо оценок («isometric 3D icon» лучше, чем «красивая иконка»).
- Текста на картинке почти всегда лучше избегать: `no text, no letters`.
- `size` у Gemini-моделей молча отбрасывается (они его не принимают) — это не ошибка.

Готовые шаблоны:

```text
Логотип/маскот:   <персонаж или символ>, flat vector logo, simple geometric shapes,
                  bold silhouette, <палитра>, plain white background, no text
Hero-баннер:      <сцена>, wide cinematic composition, soft gradient light,
                  <палитра>, empty space on the left for a headline, no text
                  → size: 1536x1024
UI-иконка:        <предмет>, isometric 3D icon, rounded corners, subtle shadows,
                  <палитра>, transparent-looking flat background, no text
                  → size: 1024x1024
```

### `edit_image` — правка существующей

`input_path` — картинка в проекте, `prompt` — инструкция в повелительном
наклонении: `keep the composition and the character, replace the background with
a night city skyline`. Модель — только chat-контур (`gemini-…-image-preview`);
`gpt-image-2` опорные изображения не принимает и скажет об этом сразу.

### `batch_generate` — сравнение моделей

Один `prompt`, список `models` и общая `output_dir` — каждая модель сохранится
в отдельный файл, упавшие попадут в `errors` с причиной.

### Как это выглядит со стороны агента

Достаточно обычного запроса в чате Cline, находясь в любом проекте
`/Users/evmelnik/Documents/aiDev`:

```text
Сгенерируй hero-баннер для лендинга: закат над горами, плоская векторная
иллюстрация, место слева под заголовок. Сохрани в public/images/hero.png,
модель openai/gpt-image-2, размер 1536x1024.
```

Агент сам вызовет `mev-nordrouter-img → generate_image` с нужными параметрами.

## Локальный запуск / проверка

```bash
cd /Users/evmelnik/Documents/aiDev/imgRouter-mcp
PYTHONPATH=. .venv/bin/python server.py
```

Инструменты зарегистрированы через декоратор `@mcp.tool()`; схема каждого
инструмента выводится из сигнатуры функции, docstring и `Field`-метаданных
Pydantic.

## Структура

```
imgRouter-mcp/
├── server.py              # MCPServer + регистрация инструментов
├── mcp_config.json        # конфиг для Cline
├── requirements.txt
├── .env.example
├── tools/
│   ├── generate.py        # generate_image
│   ├── edit.py            # edit_image
│   ├── models.py          # list_image_models
│   └── batch.py           # batch_generate
└── utils/
    ├── api_client.py      # NordRouterClient (chat/images, загрузка изображений)
    ├── config.py          # загрузка конфигурации
    ├── model_profiles.py  # какие параметры принимает каждая модель
    └── image_processor.py # форматы, base64, сохранение, конвертация
```

## Примечания

- Размер задаётся строкой вида `1024x1024`, `1024x1536`, `1536x1024`,
  `2048x2048` и отправляется только моделям, у которых `size` есть в профиле
  (сейчас это `openai/gpt-image-2`). Gemini-моделям `size` не передаётся.
- `quality` (`low`/`medium`/`high`/`auto`) поддерживает `openai/gpt-image-2`;
  остальным моделям параметр не отправляется.
- Gemini (`chat/completions`) может возвращать изображение большего разрешения,
  чем запрошено; итоговый файл при необходимости перекодируется под требуемое
  расширение через Pillow.
- При `count > 1` файлы получают суффиксы `_v1`, `_v2`, …
