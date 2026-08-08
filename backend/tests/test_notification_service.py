from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.review_session import ReviewSession
from app.models.user import User

# --- ИМПОРТЫ ДЛЯ ТЕСТОВ ---
from app.services import notification_service
from app.services.notification_service import (
    get_allow_notifications,
    get_users_to_notify,
    notify_first_sync,
    send_notifications,
    set_notifications_permission,
    start_scheduler,
)
from sqlalchemy import select

# --- ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ (как в вашем примере) ---


class SessionManager:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def patch_session(monkeypatch, session):
    """Патчим AsyncSessionLocal в notification_service."""

    def mock_session_maker():
        return SessionManager(session)

    monkeypatch.setattr(notification_service, "AsyncSessionLocal", mock_session_maker)


# ==========================================
# 1. ТЕСТЫ ВЫБОРКИ ПОЛЬЗОВАТЕЛЕЙ (БД)
# ==========================================


@pytest.mark.asyncio
async def test_get_users_to_notify(session, monkeypatch):
    patch_session(monkeypatch, session)

    # 1. Пользователь разрешивший уведомления, без сессий (создан 2 дня назад) -> Должен попасть
    user1 = User(
        telegram_id=111, allow_notifications=True, created_at=datetime.utcnow() - timedelta(days=2)
    )

    # 2. Пользователь запретивший уведомления -> Не должен попасть
    user2 = User(
        telegram_id=222, allow_notifications=False, created_at=datetime.utcnow() - timedelta(days=2)
    )

    # 3. Пользователь, который учился недавно (1 час назад) -> Не должен попасть
    user3 = User(
        telegram_id=333, allow_notifications=True, created_at=datetime.utcnow() - timedelta(days=2)
    )

    # 4. Пользователь, который учился давно (2 дня назад) -> Должен попасть
    user4 = User(
        telegram_id=444, allow_notifications=True, created_at=datetime.utcnow() - timedelta(days=2)
    )

    session.add_all([user1, user2, user3, user4])
    await session.commit()

    # Добавляем сессии для юзеров 3 и 4
    session.add(ReviewSession(user_id=user3.id, created_at=datetime.utcnow() - timedelta(hours=1)))
    session.add(ReviewSession(user_id=user4.id, created_at=datetime.utcnow() - timedelta(days=2)))
    await session.commit()

    # Запуск
    users_to_notify = await get_users_to_notify()

    # Проверки
    assert 111 in users_to_notify
    assert users_to_notify[111] >= 47  # Прошло ~48 часов

    assert 222 not in users_to_notify  # Отключены уведомления

    assert 333 not in users_to_notify  # Недавно повторял

    assert 444 in users_to_notify  # Давно не повторял
    assert users_to_notify[444] >= 47


# ==========================================
# 2. ТЕСТЫ ОТПРАВКИ УВЕДОМЛЕНИЙ
# ==========================================


@pytest.mark.asyncio
async def test_send_notifications_success():
    bot = AsyncMock()

    with patch(
        "app.services.notification_service.get_users_to_notify", new_callable=AsyncMock
    ) as mock_get_users:
        mock_get_users.return_value = {111: 48, 222: 72}

        await send_notifications(bot)

        assert bot.send_message.await_count == 2

        # Получаем первый вызов мока
        call_obj = bot.send_message.await_args_list[0]
        args = call_obj.args  # Позиционные аргументы: (telegram_id,)
        kwargs = call_obj.kwargs  # Именованные аргументы: {'text': ..., 'reply_markup': ..., ...}

        assert args[0] in (111, 222)
        assert "Вы не повторяли карточки" in kwargs["text"]
        assert "Отключить уведомления" in str(kwargs["reply_markup"])
        assert kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_notifications_handles_exceptions(capfd):
    bot = AsyncMock()
    bot.send_message.side_effect = Exception("Send failed")

    with patch(
        "app.services.notification_service.get_users_to_notify", new_callable=AsyncMock
    ) as mock_get_users:
        mock_get_users.return_value = {111: 48}

        await send_notifications(bot)

        # Функция должна перехватить исключение и напечатать его в консоль
        captured = capfd.readouterr()
        assert "Не удалось отправить уведомление пользователю 111" in captured.out


# ==========================================
# 3. ТЕСТЫ FIRST SYNC УВЕДОМЛЕНИЯ
# ==========================================


@pytest.mark.asyncio
async def test_notify_first_sync_with_deck():
    bot = AsyncMock()
    await notify_first_sync(bot, 111, 50, "MyDeck")

    bot.send_message.assert_awaited_once()
    args, kwargs = bot.send_message.await_args

    assert args[0] == 111
    assert "50 карточек" in args[1]
    assert "MyDeck" in args[1]
    assert "Отлично!" in args[1]


@pytest.mark.asyncio
async def test_notify_first_sync_without_deck():
    bot = AsyncMock()
    await notify_first_sync(bot, 111, 10, None)

    bot.send_message.assert_awaited_once()
    args, _ = bot.send_message.await_args
    assert "10 карточек" in args[1]
    assert "в колоде" not in args[1]


@pytest.mark.asyncio
async def test_notify_first_sync_logs_warning_on_error(caplog):
    bot = AsyncMock()
    bot.send_message.side_effect = Exception("Network error")

    with caplog.at_level("WARNING"):
        await notify_first_sync(bot, 111, 10)

    bot.send_message.assert_awaited_once()
    assert "Failed to send first sync notification" in caplog.text


# ==========================================
# 4. ТЕСТЫ ПЛАНИРОВЩИКА
# ==========================================


def test_start_scheduler():
    bot = AsyncMock()

    with patch("app.services.notification_service.AsyncIOScheduler") as MockScheduler:
        mock_scheduler_instance = MagicMock()
        MockScheduler.return_value = mock_scheduler_instance

        start_scheduler(bot)

        mock_scheduler_instance.add_job.assert_called_once_with(
            send_notifications, "cron", hour="12", minute="0", timezone="Europe/Moscow", args=[bot]
        )
        mock_scheduler_instance.start.assert_called_once()


# ==========================================
# 5. ТЕСТЫ НАСТРОЕК УВЕДОМЛЕНИЙ
# ==========================================


@pytest.mark.asyncio
async def test_get_allow_notifications(session, monkeypatch):
    patch_session(monkeypatch, session)

    # 1. Создаем пользователя с выключенными уведомлениями
    user_off = User(telegram_id=111, allow_notifications=False)
    # 2. Создаем пользователя с включенными уведомлениями
    user_on = User(telegram_id=222, allow_notifications=True)

    session.add_all([user_off, user_on])
    await session.commit()

    # Проверка пользователя с False (теперь должно вернуть False)
    assert await get_allow_notifications(111) is False

    # Проверка пользователя с True
    assert await get_allow_notifications(222) is True

    # Проверка несуществующего пользователя (должен вернуть True по умолчанию)
    assert await get_allow_notifications(999) is True


@pytest.mark.asyncio
async def test_set_notifications_permission(session, monkeypatch):
    patch_session(monkeypatch, session)

    user = User(telegram_id=111, allow_notifications=True)
    session.add(user)
    await session.commit()

    # Меняем разрешение на False
    await set_notifications_permission(111, False)

    # Проверяем, что значение в БД действительно изменилось
    res = await session.execute(select(User.allow_notifications).where(User.telegram_id == 111))
    assert res.scalar_one_or_none() is False
