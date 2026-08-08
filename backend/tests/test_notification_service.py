from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
async def test_get_users_to_notify():

    fake_row_1 = SimpleNamespace(telegram_id=111, delta_hours=48.5)
    fake_row_2 = SimpleNamespace(telegram_id=444, delta_hours=72.1)

    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([fake_row_1, fake_row_2])

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    class MockSessionManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            pass

    with patch("app.services.notification_service.AsyncSessionLocal", MockSessionManager):
        users_to_notify = await get_users_to_notify()

    assert users_to_notify == {111: 48, 444: 72}

    mock_session.execute.assert_awaited_once()


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
        call_obj = bot.send_message.await_args_list[0]
        args = call_obj.args
        kwargs = call_obj.kwargs

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

    user_off = User(telegram_id=111, allow_notifications=False)

    user_on = User(telegram_id=222, allow_notifications=True)

    session.add_all([user_off, user_on])
    await session.commit()

    assert await get_allow_notifications(111) is False

    assert await get_allow_notifications(222) is True

    assert await get_allow_notifications(999) is True


@pytest.mark.asyncio
async def test_set_notifications_permission(session, monkeypatch):
    patch_session(monkeypatch, session)

    user = User(telegram_id=111, allow_notifications=True)
    session.add(user)
    await session.commit()

    await set_notifications_permission(111, False)

    res = await session.execute(select(User.allow_notifications).where(User.telegram_id == 111))
    assert res.scalar_one_or_none() is False
