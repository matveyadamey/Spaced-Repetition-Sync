# Spaced Repetition — сервис интервального повторения

Система для запоминания с Telegram-ботом, REST API и плагином Obsidian.

## Компоненты

| Компонент | Назначение |
|-----------|------------|
| Telegram-бот | Повторения, статистика, токены, настройки |
| FastAPI | REST API синхронизации и статуса |
| PostgreSQL | Пользователи, карточки, прогресс |
| Obsidian-плагин | Парсинг карточек и синхронизация с сервером |

Прогресс обучения хранится **только на сервере**. Плагин не записывает интервалы в файлы Obsidian.

## Быстрый старт (Docker)

1. Скопируйте окружение:

```bash
cp .env.example .env
```

2. Укажите `BOT_TOKEN` от [@BotFather](https://t.me/BotFather).

3. Запустите:

```bash
docker compose up --build
```

Если Docker Hub недоступен, в проекте уже используются зеркала AWS Public ECR
(`public.ecr.aws/docker/library/...`). Подробнее: [docs/DEVELOPER.md](docs/DEVELOPER.md).

API: `http://localhost:8000`  
Health: `http://localhost:8000/health`  
Документация OpenAPI: `http://localhost:8000/docs`

В production используйте HTTPS URL, который выдаёт PaaS.

## Локальная разработка без Docker (backend)

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

Поднимите PostgreSQL (через `docker compose up db` или локально) и задайте:

```env
BOT_TOKEN=...
DATABASE_URL=postgresql+asyncpg://spaced:spaced@localhost:5432/spaced_repetition
```

Миграции и запуск:

```bash
cd backend
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Telegram-бот стартует вместе с приложением через long polling.

## Тесты

```bash
cd backend
pytest
```

## Obsidian-плагин

Сборка:

```bash
cd obsidian-plugin
npm install
npm run build
```

После сборки появятся `main.js`, `manifest.json`, `styles.css`.

### Установка вручную

1. Создайте папку в vault:

```text
<Vault>/.obsidian/plugins/spaced-repetition-sync/
```

2. Скопируйте туда:

- `main.js`
- `manifest.json`
- `styles.css`

3. Включите плагин в настройках Obsidian → Community plugins.

4. В настройках плагина укажите:

- **Token** — из `/token` в Telegram
- **Server URL** — HTTPS адрес сервера
- **Delimiter** — по умолчанию `::`

5. Команда палитры: **Отправить карточки на сервер**.

Подробнее: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и инструкция |
| `/token` | Новый токен для плагина (показывается один раз) |
| `/review` | Сессия повторения |
| `/stats` | Статистика |
| `/set_delim ::` | Разделитель карточек |
| `/reset` | Сброс прогресса (с подтверждением) |

## API

### `POST /api/v1/sync`

```http
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "cards": [
    {
      "question": "Что такое Python?",
      "answer": "Язык программирования",
      "source_file": "notes.md"
    }
  ]
}
```

### `GET /api/v1/status`

Возвращает `user_id`, `cards_count`, `last_sync_at`, `delimiter`.

## Формат карточек

```text
Что такое Python? :: Язык программирования
```

Многострочный:

```text
Что такое Python?
::
Язык программирования.
```

В вопросе обязателен символ `?`. Карточки разделяются пустыми строками.

## Структура репозитория

```text
backend/           # FastAPI + aiogram + SQLAlchemy
obsidian-plugin/   # TypeScript плагин
docs/              # Документация
docker-compose.yml
.env.example
```

## Документация

- [Руководство пользователя](docs/USER_GUIDE.md)
- [Руководство разработчика](docs/DEVELOPER.md)
