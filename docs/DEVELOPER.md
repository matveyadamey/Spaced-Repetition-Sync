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

## Процесс разработки (Workflow)

Разработка ведется по модели **`dev` → `main`**. Прямые коммиты в `main` запрещены.

### Шаги работы над задачей

1. **Локальная разработка и тестирование**
   - Вся разработка ведется локально.
   - Бэкенд и инфраструктура (PostgreSQL) поднимаются через Docker Compose:
     ```bash
     docker compose up --build
     ```
   - Бот запускается локально через Python для удобной отладки и hot-reload.
   - Перед коммитом обязательно прогоняются тесты:
     ```bash
     pytest -v
     ```

2. **Тестирование на dev-боте**
   - В настройках плагина Obsidian указать Server URL: http://localhost:8000
   - На тестовом боте проверяется end-to-end сценарий:
     - синхронизация карточек из Obsidian,
     - работа онбординга и команд,
     - процесс повторения,
     - корректность FSM и callback-кнопок.

3. **Создание Merge Request**
   - Если на тестовом боте всё работает корректно — создается MR из `dev`в `main`, который триггерит деплой в прод.


### Правила

- ✅ Ветка `dev` — рабочая, в неё идёт вся текущая разработка.
- ✅ Ветка `main` — стабильная, соответствует production.
- ❌ Нельзя коммитить прямо в `main` — только через MR.
- ❌ Нельзя мёржить MR, если CI (`pytest`, `ruff`, `typecheck`) не зелёный.
- ❌ Нельзя мёржить в `main` без предварительного прогона на тестовом боте.

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

### Pre-commit и линтинг

Для соблюдения стандартов кода и успешного прохождения CI в проекте настроены pre-commit хуки. Они автоматически проверяют код и применяют исправления (включая `ruff check --fix`) при коммите, поэтому запускать линтер вручную не требуется.

Установка хуков в локальный репозиторий:
```bash
pip install pre-commit
pre-commit install
```

Обновление `.pre-commit-config.yaml` 
```bash
pre-commit autoupdate
```

### Запуск

Создание .env
```bash
cp .env.example .env
```

Docker compose
```bash
docker compose up --build
```

### Тесты

```bash
cd backend
./.venv/scripts/activate    
pip install -r requirements.txt    
pytest -v
```

Плагин:

```bash
cd obsidian-plugin
npm test
npm run typecheck
```

Покрыто:

- SM-2;
- токены (генерация / SHA-256 / ротация);
- sync add / update / delete / empty / missing deck;
- колоды (`deck_service` + `GET/POST /api/v1/decks`);
- review (сессия, оценка, due vs new, stats, reset, смена колоды);
- экспорт колоды в Markdown;
- изоляция пользователей;
- API-аутентификация;
- парсер карточек плагина (Vitest).

Не покрыто намеренно (тонкий I/O): обработчики aiogram целиком — логика в сервисах.

CI (`.github/workflows/ci.yml`) на push/PR в `main`: pytest + ruff, typecheck + vitest плагина.

### Ключевые модули

| Путь | Роль |
|------|------|
| `app/services/sm2.py` | Алгоритм SM-2 |
| `app/services/sync_service.py` | Зеркальная синхронизация в одной транзакции |
| `app/services/review_service.py` | Сессии `/review`, статистика, reset |
| `app/services/export_service.py` | Экспорт колоды в Markdown (`/export_deck`) |
| `app/services/token_service.py` | Генерация и хеширование токенов |
| `app/services/notification_service.py` | Отправка системных уведомлений (напр. первый sync) |
| `app/bot/handlers/` | Пакет с роутерами: `start`, `onboarding`, `decks`, `review`, `settings` |
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

