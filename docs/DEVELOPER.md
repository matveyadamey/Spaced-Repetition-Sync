# Руководство разработчика

## Архитектура

```text
Telegram Bot API (long polling)
        │
        ▼
┌──────────────────────────┐
│  FastAPI app (uvicorn)   │
│  ├── REST /api/v1/*      │
│  ├── aiogram handlers    │
│  └── services (SM-2,     │
│      sync, review, token)│
└────────────┬─────────────┘
             ▼
        PostgreSQL
             ▲
             │ HTTPS Bearer token
      Obsidian Plugin
```

Одно процессное приложение поднимает и API, и бота.

## Backend

### Зависимости

Python 3.10+, FastAPI, aiogram 3.x, SQLAlchemy 2 (async), Alembic, asyncpg.

### Конфигурация

Переменные окружения (см. `.env.example`):

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен Telegram-бота |
| `DATABASE_URL` | `postgresql+asyncpg://...` |
| `ENVIRONMENT` | `development` / `production` |
| `LOG_LEVEL` | `INFO` / `ERROR` |
| `MAX_NEW_CARDS_PER_SESSION` | Лимит новых карточек (по умолчанию 20) |
| `PLUGIN_INSTALL_URL` | Ссылка в `/start` |

Секреты не коммитить. `.env` в `.gitignore`.

### Миграции

```bash
cd backend
alembic upgrade head
alembic revision --autogenerate -m "message"
```

### Запуск

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Или через Docker Compose из корня репозитория.

### Тесты

```bash
cd backend
pytest -v
```

Покрыто:

- SM-2;
- токены (генерация / SHA-256);
- sync add / update / delete / empty;
- изоляция пользователей;
- API-аутентификация.

### Ключевые модули

| Путь | Роль |
|------|------|
| `app/services/sm2.py` | Алгоритм SM-2 |
| `app/services/sync_service.py` | Зеркальная синхронизация в одной транзакции |
| `app/services/review_service.py` | Сессии `/review`, статистика, reset |
| `app/services/export_service.py` | Экспорт колоды в Markdown (`/export_deck`) |
| `app/services/token_service.py` | Генерация и хеширование токенов |
| `app/bot/handlers.py` | Команды и callback-кнопки |
| `app/api/sync.py` | `POST /api/v1/sync` |
| `app/api/status.py` | `GET /api/v1/status` |

### Безопасность

- В БД хранится только `SHA256(token)`.
- API: `Authorization: Bearer <token>`.
- Все операции с карточками ограничены `user_id`.
- Callback сессии содержат `session_id`; устаревшие кнопки не меняют прогресс.

## Obsidian Plugin

```bash
cd obsidian-plugin
npm install
npm run build
```

Исходники:

| Файл | Роль |
|------|------|
| `main.ts` | Плагин, настройки, команда sync |
| `src/parser.ts` | Парсинг карточек и дедупликация |
| `src/sync.ts` | HTTP-клиент и обработка ошибок |

Плагин использует только:

```typescript
app.vault.getMarkdownFiles()
app.vault.read(file)
```


## Деплой

Пошаговая инструкция: [DEPLOY.md](DEPLOY.md) (Railway из GitHub + релизы плагина для BRAT).

## Логирование

Уровни `INFO` / `ERROR`. Логируются команды бота, API-запросы, ошибки auth/DB/sync. Сырые токены в логи не пишутся.
