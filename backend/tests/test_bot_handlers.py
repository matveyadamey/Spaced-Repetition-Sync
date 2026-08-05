from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram import Bot

# --- ИМПОРТЫ МОДУЛЕЙ (Вместо одного handlers) ---
from app.bot.handlers import decks, onboarding, review, settings, start, utils

# --- ИМПОРТЫ МОДЕЛЕЙ И СЕРВИСОВ ---
from app.models.card import Card
from app.models.deck import Deck
from app.models.progress import Progress
from app.models.user import User
from app.schemas.sync import SyncCardIn
from app.services.deck_service import create_deck
from app.services.notification_service import notify_first_sync
from app.services.review_service import get_or_create_user, start_review_session
from app.services.sync_service import sync_cards
from sqlalchemy import select


class SessionManager:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def patch_session(monkeypatch, session):
    """
    Патчим AsyncSessionLocal во всех модулях, где она импортирована.
    """

    def mock_session_maker():
        return SessionManager(session)

    for module in (start, onboarding, decks, review, settings, utils):
        if hasattr(module, "AsyncSessionLocal"):
            monkeypatch.setattr(module, "AsyncSessionLocal", mock_session_maker)


def make_message(user_id: int = 1001):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
        answer_document=AsyncMock(),
        edit_text=AsyncMock(),
        edit_reply_markup=AsyncMock(),
    )


def make_callback(data: str, message=None, user_id: int = 1001):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        data=data,
        message=message or make_message(user_id),
        answer=AsyncMock(),
    )


def make_state():
    """Мок для FSMContext"""
    state = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


async def seed_cards(
    session, user: User, *, deck: str | None, source_file: str, questions: list[str]
):
    await sync_cards(
        session,
        user,
        source_file=source_file,
        deck=deck,
        cards=[SyncCardIn(question=q, answer=f"A:{q}") for q in questions],
        bot=None,
    )


# ==========================================
# 1. БАЗОВЫЕ ТЕСТЫ И НАВИГАЦИЯ
# ==========================================


@pytest.mark.asyncio
async def test_cmd_start_creates_user_and_launches_onboarding(session, monkeypatch):
    patch_session(monkeypatch, session)
    message = make_message(555)
    state = make_state()

    await start.cmd_start(message, state)

    user = await get_or_create_user(session, 555)
    assert user.telegram_id == 555
    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Spaced Repetition Sync" in text
    assert "настроим" in text
    state.set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_help_command_relaunches_onboarding(session, monkeypatch):
    patch_session(monkeypatch, session)
    message = make_message(777)
    state = make_state()

    await start.cmd_help(message, state)

    message.answer.assert_awaited_once()
    assert "Spaced Repetition Sync" in message.answer.await_args.args[0]
    state.set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_back():
    callback = make_callback("back_to_main")
    state = make_state()
    await start.process_back(callback, state)
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    assert "Главное меню" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_show_decks_menu():
    callback = make_callback("menu_decks")
    state = make_state()
    await decks.show_decks_menu(callback, state)
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    assert "Управление колодами" in callback.message.edit_text.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_cmd_token_updates_hash_and_replies(session, monkeypatch):
    patch_session(monkeypatch, session)
    callback = make_callback("menu_token")
    monkeypatch.setattr(settings, "generate_token", lambda: "x" * 43)
    monkeypatch.setattr(settings, "hash_token", lambda token: f"hashed:{token}")

    await settings.cmd_token(callback)

    user = (await session.execute(select(User).where(User.telegram_id == 1001))).scalar_one()
    assert user.token_hash == f"hashed:{'x' * 43}"
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.await_args.kwargs["text"]
    assert "Новый токен" in text
    assert "Скопировать токен" in text
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.text == "📋 Скопировать токен" for btn in buttons)


# ==========================================
# 2. ТЕСТЫ FSM (УПРАВЛЕНИЕ КОЛОДАМИ)
# ==========================================


@pytest.mark.asyncio
async def test_cmd_add_deck_branches(session, monkeypatch):
    patch_session(monkeypatch, session)
    state = make_state()

    cb = make_callback("deck_add")
    await decks.prompt_add_deck(cb, state)
    state.set_state.assert_awaited_once()

    missing = make_message()
    missing.text = "   "
    await decks.process_add_deck(missing, state)
    assert "Название не может быть пустым" in missing.answer.await_args.args[0]

    ok = make_message()
    ok.text = "Матан"
    await decks.process_add_deck(ok, state)
    calls = ok.answer.await_args_list
    assert len(calls) == 2
    assert "Колода <b>Матан</b> успешно создана!" in calls[0].args[0]
    assert "Управление колодами" in calls[1].args[0]

    duplicate = make_message()
    duplicate.text = "матан"
    await decks.process_add_deck(duplicate, state)
    assert "Ошибка:" in duplicate.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_cmd_delete_deck_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    state = make_state()

    cb = make_callback("deck_delete")
    await decks.prompt_delete_deck(cb, state)
    state.set_state.assert_awaited_once()

    ok = make_message()
    ok.text = "Матан"
    await decks.process_delete_deck(ok, state)
    calls = ok.answer.await_args_list
    assert len(calls) == 2
    assert "Колода <b>Матан</b> удалена" in calls[0].args[0]

    absent = make_message()
    absent.text = "Нет"
    await decks.process_delete_deck(absent, state)
    assert "Ошибка:" in absent.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_cmd_export_deck_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    await seed_cards(session, user, deck="Матан", source_file="math.md", questions=["Q?"])
    await create_deck(session, user, "Пустая")
    state = make_state()

    cb = make_callback("deck_export")
    await decks.prompt_export_deck(cb, state)

    empty = make_message()
    empty.text = "Пустая"
    await decks.process_export_deck(empty, state)
    calls = empty.answer.await_args_list
    assert len(calls) == 2
    assert "⚠️ В этой колоде нет карточек." in calls[0].args[0]

    ok = make_message()
    ok.text = "Матан"
    await decks.process_export_deck(ok, state)
    ok.answer_document.assert_awaited_once()
    document = ok.answer_document.await_args.args[0]
    caption = ok.answer_document.await_args.kwargs["caption"]
    assert document.filename == "Матан.md"
    assert "Экспорт завершён: 1 карт." in caption

    menu_calls = ok.answer.await_args_list
    assert len(menu_calls) == 1
    assert "Управление колодами" in menu_calls[0].args[0]


@pytest.mark.asyncio
async def test_cmd_edit_card_deck_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Что такое Python?"])
    state = make_state()

    cb = make_callback("deck_edit_card")
    await decks.prompt_edit_card_deck(cb, state)

    not_found = make_message()
    not_found.text = "Нет такой?"
    await decks.process_edit_card_deck(not_found, state)
    assert "не найдена" in not_found.answer.await_args.args[0]

    ok = make_message()
    ok.text = "Что такое Python?"
    await decks.process_edit_card_deck(ok, state)
    ok.answer.assert_awaited_once()
    markup = ok.answer.await_args.kwargs["reply_markup"]
    buttons = [row[0].callback_data for row in markup.inline_keyboard]
    assert buttons[0].startswith("setdeck:")
    assert any("Матан" == row[0].text for row in markup.inline_keyboard)


# ==========================================
# 3. ТЕСТЫ ОНБОРДИНГА
# ==========================================


@pytest.mark.asyncio
async def test_onboarding_start_shows_token():
    callback = make_callback("onboarding_start")
    state = make_state()

    with (
        patch.object(onboarding, "generate_token", return_value="test-token-123"),
        patch.object(onboarding, "hash_token", return_value="hashed-test"),
        patch.object(onboarding, "get_or_create_user", new=AsyncMock()),
        patch.object(onboarding, "AsyncSessionLocal", return_value=SessionManager(AsyncMock())),
    ):
        await onboarding.onboarding_start_handler(callback, state)

    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.await_args.args[0]
    assert "Шаг 1/3" in text
    assert "test-token-123" in text
    state.set_state.assert_awaited()


@pytest.mark.asyncio
async def test_onboarding_skip_finishes_immediately():
    callback = make_callback("onboarding_skip")
    state = make_state()
    await onboarding.onboarding_skip_handler(callback, state)
    callback.answer.assert_awaited_once()
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    assert "Настройка завершена" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_onboarding_install_shows_instructions():
    """Шаг установки показывает текстовую инструкцию"""
    callback = make_callback("onboarding_install")
    state = make_state()

    await onboarding.onboarding_install_handler(callback, state)

    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()

    text = callback.message.edit_text.await_args.args[0]

    assert "Шаг 2/3" in text
    assert "Установка плагина" in text

    assert "BRAT" in text
    assert "Add a beta plugin" in text

    assert "https://github.com/matveyadamey/Spaced-Repetition-Sync" in text

    assert "Token" in text

    state.set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_onboarding_install_brat_shows_instructions():
    """Инструкция по BRAT показывает шаги установки из Community Store"""
    callback = make_callback("onboarding_install_brat")
    state = make_state()

    await onboarding.onboarding_install_brat_handler(callback, state)

    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()

    text = callback.message.edit_text.await_args.args[0]

    assert "Установка BRAT" in text

    assert "Community plugins" in text
    assert "Browse" in text
    assert "BRAT" in text
    assert "Install" in text
    assert "Enable" in text

    state.set_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_onboarding_card_shows_example():
    callback = make_callback("onboarding_card")
    state = make_state()
    await onboarding.onboarding_card_handler(callback, state)
    callback.answer.assert_awaited_once()
    text = callback.message.edit_text.await_args.args[0]
    assert "Шаг 3/3" in text
    assert "Python" in text
    assert "::" in text


@pytest.mark.asyncio
async def test_onboarding_finish_goes_to_main_menu():
    callback = make_callback("onboarding_finish")
    state = make_state()
    await onboarding.onboarding_finish_handler(callback, state)
    callback.answer.assert_awaited_once()
    state.clear.assert_awaited_once()
    assert "Настройка завершена" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_menu_install_opens_install_step():
    callback = make_callback("menu_install")
    state = make_state()
    await onboarding.menu_install_handler(callback, state)
    callback.answer.assert_awaited_once()
    text = callback.message.edit_text.await_args.args[0]
    assert "Установка плагина" in text or "Шаг 2" in text


@pytest.mark.asyncio
async def test_show_main_menu_with_callback():
    callback = make_callback("some_callback")
    await utils.show_main_menu(callback)
    callback.message.edit_text.assert_awaited_once()
    assert "Главное меню" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_send_error_with_message():
    message = make_message()
    await utils._send_error(message, "Ошибка!")
    message.answer.assert_awaited_once()
    assert "Ошибка!" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_send_error_with_callback():
    callback = make_callback("some_callback")
    await utils._send_error(callback, "Ошибка!")
    callback.message.edit_text.assert_awaited_once()
    assert "Ошибка!" in callback.message.edit_text.await_args.args[0]


# ==========================================
# 4. ТЕСТЫ notify_first_sync (Теперь из services)
# ==========================================


@pytest.mark.asyncio
async def test_notify_first_sync_sends_message():
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()

    await notify_first_sync(bot, telegram_id=12345, cards_count=5, deck_name="Python")

    bot.send_message.assert_awaited_once()
    args = bot.send_message.await_args.args
    kwargs = bot.send_message.await_args.kwargs

    assert args[0] == 12345
    assert "5 карточек" in args[1]
    assert "Python" in args[1]
    assert kwargs["parse_mode"] == "HTML"

    markup = kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.text == "▶️ Начать повторение" for btn in buttons)
    assert any(btn.text == "🏠 В главное меню" for btn in buttons)


@pytest.mark.asyncio
async def test_notify_first_sync_without_deck():
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    await notify_first_sync(bot, telegram_id=99999, cards_count=1, deck_name=None)
    bot.send_message.assert_awaited_once()
    args = bot.send_message.await_args.args
    text = args[1]
    assert "1 карточек" in text
    assert "колоде" not in text


@pytest.mark.asyncio
async def test_notify_first_sync_handles_bot_error():
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock(side_effect=Exception("Telegram API error"))
    await notify_first_sync(bot, telegram_id=12345, cards_count=5, deck_name="Test")


# ==========================================
# 5. ТЕСТЫ sync_cards
# ==========================================


@pytest.mark.asyncio
async def test_sync_cards_first_sync_calls_notify(session, user_with_token):
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()

    with patch(
        "app.services.notification_service.notify_first_sync", new=AsyncMock()
    ) as mock_notify:
        result = await sync_cards(
            session,
            user,
            source_file="test.md",
            deck=None,
            cards=[SyncCardIn(question="Q?", answer="A")],
            bot=bot,
        )

    assert result.added == 1
    mock_notify.assert_awaited_once()
    call_args = mock_notify.await_args
    assert call_args.args[0] == bot
    assert call_args.args[1] == user.telegram_id
    assert call_args.args[2] == 1


@pytest.mark.asyncio
async def test_sync_cards_subsequent_sync_skips_notify(session, user_with_token):
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    await sync_cards(
        session,
        user,
        source_file="test.md",
        deck=None,
        cards=[SyncCardIn(question="Q1?", answer="A1")],
        bot=None,
    )

    await session.refresh(user)
    assert user.last_sync_at is not None

    bot = AsyncMock(spec=Bot)

    with patch(
        "app.services.notification_service.notify_first_sync", new=AsyncMock()
    ) as mock_notify:
        result = await sync_cards(
            session,
            user,
            source_file="test.md",
            deck=None,
            cards=[SyncCardIn(question="Q2?", answer="A2")],
            bot=bot,
        )

    assert result.added == 1
    mock_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_cards_no_bot_skips_notify(session, user_with_token):
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    with patch(
        "app.services.notification_service.notify_first_sync", new=AsyncMock()
    ) as mock_notify:
        result = await sync_cards(
            session,
            user,
            source_file="test.md",
            deck=None,
            cards=[SyncCardIn(question="Q?", answer="A")],
            bot=None,
        )

    assert result.added == 1
    mock_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_cards_empty_first_sync_skips_notify(session, user_with_token):
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    with patch(
        "app.services.notification_service.notify_first_sync", new=AsyncMock()
    ) as mock_notify:
        result = await sync_cards(
            session,
            user,
            source_file="test.md",
            deck=None,
            cards=[],
            bot=AsyncMock(spec=Bot),
        )

    assert result.added == 0
    mock_notify.assert_not_awaited()


# ==========================================
# 6. ТЕСТЫ CALLBACK КНОПОК И REVIEW
# ==========================================


@pytest.mark.asyncio
async def test_on_set_deck_callback_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    deck = await create_deck(session, user, "Матан")
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Move?"])
    card = (await session.execute(select(Card).where(Card.user_id == user.id))).scalar_one()

    bad = make_callback("setdeck:1")
    await decks.on_set_deck_callback(bad)
    bad.answer.assert_awaited_once_with("Некорректные данные.", show_alert=True)

    missing = make_callback(f"setdeck:{card.id}:999999")
    await decks.on_set_deck_callback(missing)
    assert "Колода не найдена" in missing.answer.await_args.args[0]

    ok = make_callback(f"setdeck:{card.id}:{deck.id}")
    await decks.on_set_deck_callback(ok)
    ok.message.edit_text.assert_awaited_once()
    assert "Колода карточки обновлена: <b>Матан</b>" in ok.message.edit_text.await_args.args[0]
    ok.answer.assert_awaited()


@pytest.mark.asyncio
async def test_cmd_review_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token

    empty = make_callback("menu_review")
    await review.cmd_review(empty)
    assert "Нет карточек для повторения" in empty.message.answer.await_args.kwargs["text"]
    assert empty.message.answer.await_args.kwargs["reply_markup"] is not None

    await create_deck(session, user, "Матан")
    await seed_cards(session, user, deck="Матан", source_file="a.md", questions=["Math?"])

    ok = make_callback("menu_review")
    await review.cmd_review(ok)
    ok.message.answer.assert_awaited_once()
    assert "Выберите колоду для повторения:" in ok.message.answer.await_args.kwargs["text"]

    markup = ok.message.answer.await_args.kwargs["reply_markup"]
    all_callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert any(data.startswith("revdeck:") for data in all_callbacks)
    assert "back_to_main" in all_callbacks


@pytest.mark.asyncio
async def test_on_review_deck_callback_branches(monkeypatch):

    callback = make_callback("revdeck:bad")
    await review.on_review_deck_callback(callback)
    callback.answer.assert_awaited_once_with("Некорректные данные.", show_alert=True)

    ok = make_callback("revdeck:0")
    called = AsyncMock()
    monkeypatch.setattr(review, "_start_deck_review", called)

    await review.on_review_deck_callback(ok)

    called.assert_not_called()

    ok.answer.assert_awaited_once_with()

    ok.message.edit_text.assert_awaited_once()
    call_args, call_kwargs = ok.message.edit_text.call_args
    assert "Выберите сложность карточек" in call_kwargs.get("text", "")

    kb = call_kwargs.get("reply_markup")
    assert kb is not None
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "revdiff:0:1" in callbacks  # Легкие
    assert "revdiff:0:2" in callbacks  # Легкие+средние
    assert "revdiff:0:3" in callbacks  # Все


@pytest.mark.asyncio
async def test_on_review_diff_callback_branches(monkeypatch):

    bad_cb = make_callback("revdiff:bad:1")
    await review.on_review_diff_callback(bad_cb)
    bad_cb.answer.assert_awaited_once_with("Некорректные данные.", show_alert=True)

    ok_cb = make_callback("revdiff:0:3")
    called = AsyncMock()
    monkeypatch.setattr(review, "_start_deck_review", called)

    await review.on_review_diff_callback(ok_cb)

    ok_cb.answer.assert_awaited_once_with()

    called.assert_awaited_once_with(ok_cb, 1001, None, difficulty=3)


@pytest.mark.asyncio
async def test_on_review_deck_callback_ignores_missing_context():
    callback = make_callback("revdeck:0")
    callback.from_user = None
    callback.data = None
    callback.message = None
    await review.on_review_deck_callback(callback)
    callback.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_review_callback_show_and_invalid_cases(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Show?"])

    # start_review_session импортирована напрямую из review_service
    rev_session = await start_review_session(session, user, deck_id=None)
    card = (await session.execute(select(Card).where(Card.user_id == user.id))).scalar_one()

    malformed = make_callback("review:x")
    await review.on_review_callback(malformed)
    malformed.answer.assert_awaited_once_with("Некорректные данные.", show_alert=True)

    stale = make_callback(f"review:missing:{card.id}:show")
    await review.on_review_callback(stale)
    assert "Сессия устарела" in stale.answer.await_args.args[0]

    wrong_card = make_callback(f"review:{rev_session.session_id}:999999:show")
    await review.on_review_callback(wrong_card)
    assert "не актуальна" in wrong_card.answer.await_args.args[0]

    show = make_callback(f"review:{rev_session.session_id}:{card.id}:show")
    await review.on_review_callback(show)
    show.message.edit_text.assert_awaited_once()
    assert "A:Show?" in show.message.edit_text.await_args.args[0]
    show.answer.assert_awaited_once_with()

    markup = show.message.edit_text.await_args.kwargs["reply_markup"]
    all_callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "back_to_main" in all_callbacks

    bad_rate = make_callback(f"review:{rev_session.session_id}:{card.id}:rate:2")
    await review.on_review_callback(bad_rate)
    bad_rate.answer.assert_awaited_once_with("Некорректная оценка.", show_alert=True)

    unknown = make_callback(f"review:{rev_session.session_id}:{card.id}:noop")
    await review.on_review_callback(unknown)
    unknown.answer.assert_awaited_once_with("Неизвестное действие.", show_alert=True)


@pytest.mark.asyncio
async def test_on_review_callback_ignores_missing_context():
    callback = make_callback("review:x")
    callback.from_user = None
    callback.data = None
    callback.message = None
    await review.on_review_callback(callback)
    callback.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_review_callback_rate_paths(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["First?", "Second?"])
    rev_session = await start_review_session(session, user, deck_id=None)
    first, second = (
        (await session.execute(select(Card).where(Card.user_id == user.id).order_by(Card.id.asc())))
        .scalars()
        .all()
    )

    next_card = make_callback(f"review:{rev_session.session_id}:{first.id}:rate:5")
    await review.on_review_callback(next_card)
    next_card.answer.assert_awaited_once_with()

    next_card.message.edit_text.assert_awaited()
    sent_question = next_card.message.edit_text.await_args.args[0]
    assert sent_question == "Second?"

    finish = make_callback(
        f"review:{rev_session.session_id}:{second.id}:rate:5", message=next_card.message
    )
    await review.on_review_callback(finish)
    finish.message.edit_text.assert_awaited()
    assert "Сессия завершена" in finish.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_cmd_stats_and_reset(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Q?"])

    stats = make_callback("menu_stats")
    await settings.cmd_stats(stats)
    stats.message.edit_text.assert_awaited_once()
    assert "Всего карточек: 1" in stats.message.edit_text.await_args.kwargs["text"]

    reset = make_callback("menu_reset")
    await settings.cmd_reset(reset)
    reset.message.edit_text.assert_awaited_once()
    assert "Сбросить весь прогресс обучения?" in reset.message.edit_text.await_args.kwargs["text"]
    assert reset.message.edit_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_on_reset_callback_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Q?"])
    card = (await session.execute(select(Card).where(Card.user_id == user.id))).scalar_one()
    progress = (
        await session.execute(select(Progress).where(Progress.card_id == card.id))
    ).scalar_one()
    progress.repetition = 2
    await session.commit()

    cancel = make_callback("reset:cancel")
    await settings.on_reset_callback(cancel)
    cancel.message.edit_text.assert_awaited_once()
    assert "Сброс отменён." in cancel.message.edit_text.await_args.args[0]
    cancel.answer.assert_awaited_once_with()

    confirm = make_callback("reset:confirm")
    await settings.on_reset_callback(confirm)
    confirm.message.edit_text.assert_awaited_once()
    assert "Прогресс сброшен" in confirm.message.edit_text.await_args.args[0]
    confirm.answer.assert_awaited_once_with()

    unknown = make_callback("reset:other")
    await settings.on_reset_callback(unknown)
    unknown.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_on_set_deck_callback_ignores_missing_context():
    callback = make_callback("setdeck:1:0")
    callback.from_user = None
    callback.data = None
    callback.message = None
    await decks.on_set_deck_callback(callback)
    callback.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_deck_review_handles_empty_and_sends_question(
    session, monkeypatch, user_with_token
):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    deck = (await session.execute(select(Deck).where(Deck.user_id == user.id))).scalar_one()

    empty_msg = make_message()
    await utils._start_deck_review(empty_msg, user.telegram_id, deck.id)
    assert "нет карточек" in empty_msg.answer.await_args.args[0].casefold()

    await seed_cards(session, user, deck="Матан", source_file="a.md", questions=["Math?"])
    full_msg = make_message()
    await utils._start_deck_review(full_msg, user.telegram_id, deck.id)
    full_msg.answer.assert_awaited_once()
    assert full_msg.answer.await_args.args[0] == "Math?"

    full_cb = make_callback("revdeck:0")
    await utils._start_deck_review(full_cb, user.telegram_id, deck.id)
    full_cb.message.edit_text.assert_awaited_once()
    assert full_cb.message.edit_text.await_args.args[0] == "Math?"


@pytest.mark.asyncio
async def test_handler_none_user_guards(session, monkeypatch):
    patch_session(monkeypatch, session)

    message = make_message()
    message.from_user = None

    cb_message = make_message()
    callback = make_callback("menu_token", message=cb_message)
    callback.from_user = None

    state = make_state()

    await start.cmd_start(message, state)
    await settings.cmd_token(callback)
    await decks.prompt_add_deck(callback, state)
    await decks.prompt_delete_deck(callback, state)
    await decks.prompt_export_deck(callback, state)
    await decks.prompt_edit_card_deck(callback, state)
    await review.cmd_review(callback)
    await settings.cmd_stats(callback)
    await settings.cmd_reset(callback)

    msg_for_process = make_message()
    msg_for_process.from_user = None
    msg_for_process.text = "test"
    await decks.process_add_deck(msg_for_process, state)
    await decks.process_delete_deck(msg_for_process, state)
    await decks.process_export_deck(msg_for_process, state)
    await decks.process_edit_card_deck(msg_for_process, state)

    message.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    msg_for_process.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_cmd_decks_list_shows_decks_or_empty(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token

    empty = make_callback("decks_list")
    await decks.cmd_decks_list(empty)
    empty.answer.assert_awaited_once()
    empty.message.edit_text.assert_awaited_once()
    assert "Список колод пуст" in empty.message.edit_text.await_args.kwargs["text"]

    await create_deck(session, user, "Матан")
    await create_deck(session, user, "Физика")

    with_decks = make_callback("decks_list")
    await decks.cmd_decks_list(with_decks)
    with_decks.message.edit_text.assert_awaited_once()
    text = with_decks.message.edit_text.await_args.kwargs["text"]
    assert "Ваши колоды:" in text
    assert "Матан" in text or "Физика" in text


@pytest.mark.asyncio
async def test_cmd_decks_list_ignores_missing_user():
    callback = make_callback("decks_list")
    callback.from_user = None
    await decks.cmd_decks_list(callback)
    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_show_main_menu_displays_correct_text():
    message = make_message()
    await utils.show_main_menu(message)

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Главное меню" in text
    assert "Obsidian" in text
    assert "Telegram" in text

    markup = message.answer.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]

    button_texts = [btn.text for btn in buttons]
    assert "📦 Установка плагина" in button_texts
    assert "🔑 Получить новый токен" in button_texts
    assert "Повторить карточки" in button_texts
    assert "Управление колодами" in button_texts
    assert "Статистика" in button_texts
    assert "Сброс прогресса" in button_texts
    assert "Настройки" in button_texts


# ==========================================
# 7. ТЕСТЫ УВЕДОМЛЕНИЙ И НАСТРОЕК
# ==========================================


@pytest.mark.asyncio
async def test_settings_menu_shows_notifications_status(monkeypatch):
    callback = make_callback("settings")
    with patch.object(settings, "get_allow_notifications", new=AsyncMock(return_value=True)):
        await settings.settings_menu(callback)

    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.await_args.kwargs["text"]
    assert "Настройки" in text
    assert "Уведомления: <b>Включены</b>" in text

    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == "disable_notifications" for btn in buttons)


@pytest.mark.asyncio
async def test_settings_menu_shows_disabled_notifications(monkeypatch):
    callback = make_callback("settings")
    with patch.object(settings, "get_allow_notifications", new=AsyncMock(return_value=False)):
        await settings.settings_menu(callback)

    text = callback.message.edit_text.await_args.kwargs["text"]
    assert "Уведомления: <b>Отключены</b>" in text

    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == "enable_notifications" for btn in buttons)


@pytest.mark.asyncio
async def test_disable_notifications_updates_permission(monkeypatch):
    callback = make_callback("disable_notifications")
    with patch.object(settings, "set_notifications_permission", new=AsyncMock()) as mock_set:
        await settings.cmd_disable_notifications(callback)

    callback.answer.assert_awaited_once()
    mock_set.assert_awaited_once_with(1001, False)
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.await_args.kwargs["text"]
    assert "Уведомления отключены" in text

    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == "enable_notifications" for btn in buttons)


@pytest.mark.asyncio
async def test_enable_notifications_updates_permission(monkeypatch):
    callback = make_callback("enable_notifications")
    with patch.object(settings, "set_notifications_permission", new=AsyncMock()) as mock_set:
        await settings.cmd_enable_notifications(callback)

    callback.answer.assert_awaited_once()
    mock_set.assert_awaited_once_with(1001, True)
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.await_args.kwargs["text"]
    assert "Уведомления включены" in text

    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == "disable_notifications" for btn in buttons)


@pytest.mark.asyncio
async def test_disable_notifications_ignores_missing_user():
    callback = make_callback("disable_notifications")
    callback.from_user = None
    await settings.cmd_disable_notifications(callback)
    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_enable_notifications_ignores_missing_user():
    callback = make_callback("enable_notifications")
    callback.from_user = None
    await settings.cmd_enable_notifications(callback)
    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_menu_ignores_missing_user():
    callback = make_callback("settings")
    callback.from_user = None
    await settings.settings_menu(callback)
    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
