# DATABASE.md

## Схема базы данных ChatList

Приложение использует постоянную базу данных `SQLite` для хранения промтов, списка моделей, сохранённых результатов и настроек. Временная таблица результатов существует только в памяти приложения и в базу не записывается до нажатия пользователем кнопки сохранения.

## Общие принципы
- Основная база данных: `SQLite`
- Доступ к базе данных должен быть инкапсулирован в модуле `db.py`
- API-ключи не хранятся в базе данных
- В таблице `models` хранится имя переменной окружения, в которой лежит API-ключ
- Сами ключи должны храниться в файле `.env`

## Таблица `prompts`

Назначение: хранение введённых и сохранённых пользователем промтов.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Уникальный идентификатор промта |
| `created_at` | TEXT NOT NULL | Дата и время создания промта |
| `prompt_text` | TEXT NOT NULL | Текст промта |
| `tags` | TEXT | Теги промта, например строка с разделителями или JSON |

### Рекомендуемый SQL
```sql
CREATE TABLE prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    tags TEXT
);
```

## Таблица `models`

Назначение: хранение списка доступных нейросетей и параметров подключения.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Уникальный идентификатор модели |
| `name` | TEXT NOT NULL UNIQUE | Отображаемое название модели |
| `api_url` | TEXT NOT NULL | URL API сервиса |
| `api_id` | TEXT NOT NULL | Идентификатор модели в API |
| `api_key_env` | TEXT NOT NULL | Имя переменной окружения с API-ключом |
| `is_active` | INTEGER NOT NULL DEFAULT 1 | Признак активности модели: `1` - включена, `0` - выключена |

### Рекомендуемый SQL
```sql
CREATE TABLE models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    api_url TEXT NOT NULL,
    api_id TEXT NOT NULL,
    api_key_env TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
```

## Таблица `results`

Назначение: хранение только тех результатов, которые пользователь отметил и сохранил.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Уникальный идентификатор результата |
| `prompt_id` | INTEGER NOT NULL | Ссылка на промт из таблицы `prompts` |
| `model_id` | INTEGER NOT NULL | Ссылка на модель из таблицы `models` |
| `response_text` | TEXT NOT NULL | Текст ответа модели |
| `saved_at` | TEXT NOT NULL | Дата и время сохранения результата |

### Рекомендуемый SQL
```sql
CREATE TABLE results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL,
    model_id INTEGER NOT NULL,
    response_text TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id),
    FOREIGN KEY (model_id) REFERENCES models(id)
);
```

## Таблица `settings`

Назначение: хранение настроек программы.

Так как состав настроек может расширяться, удобно использовать универсальную схему ключ-значение.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Уникальный идентификатор записи |
| `key` | TEXT NOT NULL UNIQUE | Имя настройки |
| `value` | TEXT | Значение настройки |
| `updated_at` | TEXT | Дата и время последнего изменения |

### Рекомендуемый SQL
```sql
CREATE TABLE settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    updated_at TEXT
);
```

## Временная таблица результатов в памяти

По спецификации результаты первичного запроса не должны сразу сохраняться в `SQLite`. Для этого в приложении нужна временная структура в памяти, например список объектов или строк таблицы интерфейса.

Рекомендуемые поля временной записи:

| Поле | Тип | Назначение |
|---|---|---|
| `model_id` | INTEGER | Идентификатор модели |
| `model_name` | TEXT | Название модели |
| `response_text` | TEXT | Полученный ответ |
| `selected` | BOOLEAN / INTEGER | Выбран ли результат для сохранения |
| `error_text` | TEXT | Текст ошибки, если запрос не удался |

Эта структура:
- очищается перед новым запросом
- заново заполняется после получения ответов
- используется только для отображения в интерфейсе
- переносится в `results` только для строк, где `selected = True`

## Связи между таблицами

- Один промт из `prompts` может иметь много сохранённых результатов в `results`
- Одна модель из `models` может иметь много сохранённых результатов в `results`
- Таблица `results` связывает конкретный промт и конкретную модель
- Таблица `settings` не требует внешних ключей

## Рекомендуемые индексы

```sql
CREATE INDEX idx_prompts_created_at ON prompts(created_at);
CREATE INDEX idx_models_is_active ON models(is_active);
CREATE INDEX idx_results_prompt_id ON results(prompt_id);
CREATE INDEX idx_results_model_id ON results(model_id);
CREATE INDEX idx_results_saved_at ON results(saved_at);
```

## Переменные окружения

Пример хранения ключей в `.env`:

```env
OPENAI_API_KEY=your_openai_key
DEEPSEEK_API_KEY=your_deepseek_key
GROQ_API_KEY=your_groq_key
```

Пример записи в таблице `models`:

| name | api_url | api_id | api_key_env | is_active |
|---|---|---|---|---|
| OpenAI GPT | https://api.openai.com/v1/chat/completions | gpt-4o-mini | OPENAI_API_KEY | 1 |

## Итог

Постоянно в `SQLite` хранятся:
- `prompts`
- `models`
- `results`
- `settings`

Временно в памяти хранятся:
- результаты текущего запроса до нажатия кнопки сохранения
