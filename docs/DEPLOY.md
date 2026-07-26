# Деплой на Railway и обновления плагина через BRAT

Репозиторий: https://github.com/matveyadamey/Spaced-Repetition-Sync

---

## 1. Подготовка GitHub

1. Убедитесь, что код запушен в `main`.
2. Репозиторий должен быть **публичным**, если хотите, чтобы BRAT ставил плагин без PAT.

---

## 2. Создайте проект на Railway

1. Откройте [Railway](https://railway.com/) → **New Project**.
2. Подключите GitHub (если ещё не подключён).

---

## 3. Добавьте PostgreSQL

1. В проекте: **+ New** → **Database** → **PostgreSQL**.
2. Дождитесь, пока сервис станет Healthy.

Railway сам создаст `DATABASE_URL` в variables у сервиса Postgres, скопируйте его и вставьте в соответсвующее поле бэкенда.

---

## 4. Задеплойте backend из GitHub

1. **+ New** → **GitHub Repo** → `Spaced-Repetition-Sync`.
2. Railway подхватит корневой `Dockerfile` и `railway.toml`.
3. Откройте сервис приложения → **Variables** и добавьте:

| Переменная | Значение |
|------------|----------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference variable) |
| `BOT_TOKEN` | токен от BotFather |
| `ENVIRONMENT` | `production` |
| `LOG_LEVEL` | `INFO` |


> Имя сервиса БД может отличаться (`Postgres`, `PostgreSQL`, …). В UI Variables нажмите **Add Variable** → **Add Reference** и выберите `DATABASE_URL` у Postgres.

4. Приложение само приводит `postgres://...` к `postgresql+asyncpg://...` и `sslmode=require` к `ssl=require`.

### Networking

1. Сервис приложения → **Settings** → **Networking** → **Generate Domain**.
2. Порт выберите 8000
2. Получите HTTPS URL вида:

```text
https://<service>.up.railway.app
```

Его можно использовать для проверки API. Плагин подключается к production URL сам.




### Watch Paths (чтобы плагин не редеплоил backend)

Settings сервиса приложения → **Watch Paths** (или Build filters):

```text
backend/**
Dockerfile
railway.toml
requirements.txt
```

Либо явно игнорируйте через настройки Railway только нужные пути. Идея: изменения в `obsidian-plugin/` и `docs/` не должны пересобирать API.

### Проверка

```text
GET https://<your-service>.up.railway.app/health
→ {"status":"ok"}
```

В Telegram бот должен отвечать на `/start`.

---

## 5. Установка плагина через BRAT

1. В Obsidian установите community-плагин **BRAT** (`obsidian42-brat`).
2. Включите BRAT.
3. Команда палитры: **BRAT: Add a beta plugin for testing**.
4. Вставьте:

```text
matveyadamey/Spaced-Repetition-Sync
```

5. Выберите **latest** (автообновления) или конкретную версию (frozen).
6. Включите **Spaced Repetition Sync**.
7. В настройках плагина укажите:
   - **Token** — из `/token` в Telegram
   - **Delimiter** — разделитель карточек (по умолчанию `::`)

URL сервера встроен в плагин (`https://spaced-repetition-sync-production.up.railway.app`), отдельно указывать его не нужно.

### Как BRAT обновляет плагин

При каждом GitHub Release с ассетами `main.js`, `manifest.json`, `styles.css` BRAT скачивает свежую версию. Это делает workflow `.github/workflows/release-plugin.yml`.

---

## 6. Выпуск новой версии плагина

```bash
git add obsidian-plugin
git commit -m "Release plugin 1.0.1"
git push origin main

git tag 1.0.1
git push origin 1.0.1
```

Тег = semver. Actions соберёт плагин и создаст Release для BRAT.


