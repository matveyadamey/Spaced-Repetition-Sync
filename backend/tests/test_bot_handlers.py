from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram import Bot
from app.bot import handlers
from app.models.card import Card
from app.models.deck import Deck
from app.models.progress import Progress
from app.models.user import User
from app.schemas.sync import SyncCardIn
from app.services.deck_service import create_deck
from app.services.review_service import get_or_create_user
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
    monkeypatch.setattr(handlers, "AsyncSessionLocal", lambda: SessionManager(session))


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
        bot=None,  # явно передаём None — уведомления не нужны в тестах seed
    )


# ==========================================
# 1. БАЗОВЫЕ ТЕСТЫ И НАВИГАЦИЯ
# ==========================================


@pytest.mark.asyncio
async def test_cmd_start_creates_user_and_launches_onboarding(session, monkeypatch):
    """cmd_start теперь запускает онбординг, а не сразу главное меню"""
    patch_session(monkeypatch, session)
    message = make_message(555)
    state = make_state()

    await handlers.cmd_start(message, state)

    user = await get_or_create_user(session, 555)
    assert user.telegram_id == 555
    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    # Проверяем текст онбординга
    assert "Spaced Repetition Sync" in text
    assert "настроим" in text
    # FSM должна быть установлена в welcome
    state.set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_help_command_relaunches_onboarding(session, monkeypatch):
    """Команда /help перезапускает онбординг"""
    patch_session(monkeypatch, session)
    message = make_message(777)
    state = make_state()

    await handlers.cmd_help(message, state)

    message.answer.assert_awaited_once()
    assert "Spaced Repetition Sync" in message.answer.await_args.args[0]
    state.set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_back():
    callback = make_callback("back_to_main")
    state = make_state()
    await handlers.process_back(callback, state)
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    assert "Главное меню" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_show_decks_menu():
    callback = make_callback("menu_decks")
    state = make_state()
    await handlers.show_decks_menu(callback, state)
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    assert "Управление колодами" in callback.message.edit_text.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_cmd_token_updates_hash_and_replies(session, monkeypatch):
    patch_session(monkeypatch, session)
    callback = make_callback("menu_token")
    monkeypatch.setattr(handlers, "generate_token", lambda: "x" * 43)
    monkeypatch.setattr(handlers, "hash_token", lambda token: f"hashed:{token}")

    await handlers.cmd_token(callback)

    user = (await session.execute(select(User).where(User.telegram_id == 1001))).scalar_one()
    assert user.token_hash == f"hashed:{'x' * 43}"
    callback.message.edit_text.assert_awaited_once()
    # Теперь текст содержит "Новый токен" и инструкцию про кнопку копирования
    text = callback.message.edit_text.await_args.kwargs["text"]
    assert "Новый токен" in text
    assert "Скопировать токен" in text
    # Кнопка с copy_text должна быть в клавиатуре
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
    await handlers.prompt_add_deck(cb, state)
    state.set_state.assert_awaited_once()

    missing = make_message()
    missing.text = "   "
    await handlers.process_add_deck(missing, state)
    assert "Название не может быть пустым" in missing.answer.await_args.args[0]

    ok = make_message()
    ok.text = "Матан"
    await handlers.process_add_deck(ok, state)
    calls = ok.answer.await_args_list
    assert len(calls) == 2
    assert "Колода <b>Матан</b> успешно создана!" in calls[0].args[0]
    assert "Управление колодами" in calls[1].args[0]

    duplicate = make_message()
    duplicate.text = "матан"
    await handlers.process_add_deck(duplicate, state)
    assert "Ошибка:" in duplicate.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_cmd_delete_deck_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    state = make_state()

    cb = make_callback("deck_delete")
    await handlers.prompt_delete_deck(cb, state)
    state.set_state.assert_awaited_once()

    ok = make_message()
    ok.text = "Матан"
    await handlers.process_delete_deck(ok, state)
    calls = ok.answer.await_args_list
    assert len(calls) == 2
    assert "Колода <b>Матан</b> удалена" in calls[0].args[0]

    absent = make_message()
    absent.text = "Нет"
    await handlers.process_delete_deck(absent, state)
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
    await handlers.prompt_export_deck(cb, state)

    empty = make_message()
    empty.text = "Пустая"
    await handlers.process_export_deck(empty, state)
    calls = empty.answer.await_args_list
    assert len(calls) == 2
    assert "⚠️ В этой колоде нет карточек." in calls[0].args[0]

    ok = make_message()
    ok.text = "Матан"
    await handlers.process_export_deck(ok, state)
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
    await handlers.prompt_edit_card_deck(cb, state)

    not_found = make_message()
    not_found.text = "Нет такой?"
    await handlers.process_edit_card_deck(not_found, state)
    assert "не найдена" in not_found.answer.await_args.args[0]

    ok = make_message()
    ok.text = "Что такое Python?"
    await handlers.process_edit_card_deck(ok, state)
    ok.answer.assert_awaited_once()
    markup = ok.answer.await_args.kwargs["reply_markup"]
    buttons = [row[0].callback_data for row in markup.inline_keyboard]
    assert buttons[0].startswith("setdeck:")
    assert any("Матан" == row[0].text for row in markup.inline_keyboard)


# ==========================================
# 3. ТЕСТЫ ОНБОРДИНГА (НОВЫЕ)
# ==========================================


@pytest.mark.asyncio
async def test_onboarding_start_shows_token():
    """Начало онбординга генерирует токен и показывает его"""
    callback = make_callback("onboarding_start")
    state = make_state()

    with (
        patch.object(handlers, "generate_token", return_value="test-token-123"),
        patch.object(handlers, "hash_token", return_value="hashed-test"),
        patch.object(handlers, "get_or_create_user", new=AsyncMock()),
        patch.object(handlers, "AsyncSessionLocal", return_value=SessionManager(AsyncMock())),
    ):
        await handlers.onboarding_start_handler(callback, state)

    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.await_args.args[0]
    assert "Шаг 1/3" in text
    assert "test-token-123" in text
    state.set_state.assert_awaited()


@pytest.mark.asyncio
async def test_onboarding_skip_finishes_immediately():
    """Пропуск онбординга сразу ведёт в главное меню"""
    callback = make_callback("onboarding_skip")
    state = make_state()

    await handlers.onboarding_skip_handler(callback, state)

    callback.answer.assert_awaited_once()
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    assert "Настройка завершена" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_onboarding_install_shows_brat_link():
    """Шаг установки показывает deep link для BRAT"""
    callback = make_callback("onboarding_install")
    state = make_state()

    await handlers.onboarding_install_handler(callback, state)

    callback.answer.assert_awaited_once()
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    install_btn = next(b for b in buttons if b.text == "📦 Установить плагин в Obsidian")
    assert "obsidian://brat" in install_btn.url
    assert "Spaced-Repetition-Sync" in install_btn.url


@pytest.mark.asyncio
async def test_onboarding_install_brat_shows_store_link():
    """Инструкция по BRAT показывает ссылку на Community Store"""
    callback = make_callback("onboarding_install_brat")
    state = make_state()

    await handlers.onboarding_install_brat_handler(callback, state)

    callback.answer.assert_awaited_once()
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    brat_btn = next(b for b in buttons if b.text == "📦 Установить BRAT из Community Store")
    assert "obsidian://show-plugin" in brat_btn.url
    assert "brat" in brat_btn.url.lower()


@pytest.mark.asyncio
async def test_onboarding_card_shows_example():
    """Шаг создания карточки показывает пример формата"""
    callback = make_callback("onboarding_card")
    state = make_state()

    await handlers.onboarding_card_handler(callback, state)

    callback.answer.assert_awaited_once()
    text = callback.message.edit_text.await_args.args[0]
    assert "Шаг 3/3" in text
    assert "Python" in text
    assert "::" in text


@pytest.mark.asyncio
async def test_onboarding_finish_goes_to_main_menu():
    """Завершение онбординга ведёт в главное меню"""
    callback = make_callback("onboarding_finish")
    state = make_state()

    await handlers.onboarding_finish_handler(callback, state)

    callback.answer.assert_awaited_once()
    state.clear.assert_awaited_once()
    assert "Настройка завершена" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_menu_install_opens_install_step():
    """Кнопка 'Установка плагина' в меню открывает шаг установки"""
    callback = make_callback("menu_install")
    state = make_state()

    await handlers.menu_install_handler(callback, state)

    callback.answer.assert_awaited_once()
    text = callback.message.edit_text.await_args.args[0]
    assert "Установка плагина" in text or "Шаг 2" in text


@pytest.mark.asyncio
async def test_show_main_menu_with_callback():
    """show_main_menu работает и с Message, и с CallbackQuery"""
    callback = make_callback("some_callback")

    await handlers.show_main_menu(callback)

    callback.message.edit_text.assert_awaited_once()
    assert "Главное меню" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_send_error_with_message():
    """_send_error отправляет answer для Message"""
    message = make_message()

    await handlers._send_error(message, "Ошибка!")

    message.answer.assert_awaited_once()
    assert "Ошибка!" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_send_error_with_callback():
    """_send_error отправляет edit_text для CallbackQuery"""
    callback = make_callback("some_callback")

    await handlers._send_error(callback, "Ошибка!")

    callback.message.edit_text.assert_awaited_once()
    assert "Ошибка!" in callback.message.edit_text.await_args.args[0]


# ==========================================
# 4. ТЕСТЫ notify_first_sync
# ==========================================


@pytest.mark.asyncio
async def test_notify_first_sync_sends_message():
    """notify_first_sync отправляет сообщение с правильным текстом"""
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()

    await handlers.notify_first_sync(bot, telegram_id=12345, cards_count=5, deck_name="Python")

    bot.send_message.assert_awaited_once()
    args = bot.send_message.await_args.args
    kwargs = bot.send_message.await_args.kwargs

    # send_message(chat_id, text, reply_markup=..., parse_mode=...)
    assert args[0] == 12345
    assert "5 карточек" in args[1]
    assert "Python" in args[1]
    assert kwargs["parse_mode"] == "HTML"

    # Проверяем кнопки
    markup = kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.text == "▶️ Начать повторение" for btn in buttons)
    assert any(btn.text == "🏠 В главное меню" for btn in buttons)


@pytest.mark.asyncio
async def test_notify_first_sync_without_deck():
    """notify_first_sync работает и без указания колоды"""
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()

    await handlers.notify_first_sync(bot, telegram_id=99999, cards_count=1, deck_name=None)

    bot.send_message.assert_awaited_once()
    args = bot.send_message.await_args.args
    text = args[1]
    assert "1 карточек" in text
    # Без упоминания колоды
    assert "колоде" not in text


@pytest.mark.asyncio
async def test_notify_first_sync_handles_bot_error():
    """Ошибка отправки в Telegram не пробрасывается наружу"""
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock(side_effect=Exception("Telegram API error"))

    # Не должно поднять исключение
    await handlers.notify_first_sync(bot, telegram_id=12345, cards_count=5, deck_name="Test")


# ==========================================
# 5. ТЕСТЫ sync_cards
# ==========================================


@pytest.mark.asyncio
async def test_sync_cards_first_sync_calls_notify(session, user_with_token):
    """При первом sync вызывается notify_first_sync"""
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()

    # Патчим по месту экспорта, т.к. импорт происходит внутри функции
    with patch("app.bot.handlers.notify_first_sync", new=AsyncMock()) as mock_notify:
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
    assert call_args.args[2] == 1  # cards_count


@pytest.mark.asyncio
async def test_sync_cards_subsequent_sync_skips_notify(session, user_with_token):
    """При повторном sync notify_first_sync НЕ вызывается"""
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    # Первый sync
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

    with patch("app.bot.handlers.notify_first_sync", new=AsyncMock()) as mock_notify:
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
    """Если bot=None, notify_first_sync не вызывается"""
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    with patch("app.bot.handlers.notify_first_sync", new=AsyncMock()) as mock_notify:
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
    """Если в первом sync ничего не добавлено, notify не вызывается"""
    user, _ = user_with_token
    user.last_sync_at = None
    await session.commit()

    with patch("app.bot.handlers.notify_first_sync", new=AsyncMock()) as mock_notify:
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
# 6. ТЕСТЫ CALLBACK КНОПОК
# ==========================================


@pytest.mark.asyncio
async def test_on_set_deck_callback_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    deck = await create_deck(session, user, "Матан")
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Move?"])
    card = (await session.execute(select(Card).where(Card.user_id == user.id))).scalar_one()

    bad = make_callback("setdeck:1")
    await handlers.on_set_deck_callback(bad)
    bad.answer.assert_awaited_once_with("Некорректные данные.", show_alert=True)

    missing = make_callback(f"setdeck:{card.id}:999999")
    await handlers.on_set_deck_callback(missing)
    assert "Колода не найдена" in missing.answer.await_args.args[0]

    ok = make_callback(f"setdeck:{card.id}:{deck.id}")
    await handlers.on_set_deck_callback(ok)
    ok.message.edit_text.assert_awaited_once()
    assert "Колода карточки обновлена: <b>Матан</b>" in ok.message.edit_text.await_args.args[0]
    ok.answer.assert_awaited()


@pytest.mark.asyncio
async def test_cmd_review_branches(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token

    empty = make_callback("menu_review")
    await handlers.cmd_review(empty)

    assert "Нет карточек для повторения" in empty.message.answer.await_args.kwargs["text"]
    assert empty.message.answer.await_args.kwargs["reply_markup"] is not None

    await create_deck(session, user, "Матан")
    await seed_cards(session, user, deck="Матан", source_file="a.md", questions=["Math?"])

    ok = make_callback("menu_review")
    await handlers.cmd_review(ok)

    ok.message.answer.assert_awaited_once()
    assert "Выберите колоду для повторения:" in ok.message.answer.await_args.kwargs["text"]

    markup = ok.message.answer.await_args.kwargs["reply_markup"]
    all_callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert any(data.startswith("revdeck:") for data in all_callbacks)
    assert "back_to_main" in all_callbacks


@pytest.mark.asyncio
async def test_on_review_deck_callback_branches(monkeypatch):
    callback = make_callback("revdeck:bad")
    await handlers.on_review_deck_callback(callback)
    callback.answer.assert_awaited_once_with("Некорректные данные.", show_alert=True)

    called = AsyncMock()
    monkeypatch.setattr(handlers, "_start_deck_review", called)
    ok = make_callback("revdeck:0")
    await handlers.on_review_deck_callback(ok)

    ok.answer.assert_awaited_once_with()

    called.assert_awaited_once_with(ok, 1001, None)


@pytest.mark.asyncio
async def test_on_review_deck_callback_ignores_missing_context():
    callback = make_callback("revdeck:0")
    callback.from_user = None
    callback.data = None
    callback.message = None

    await handlers.on_review_deck_callback(callback)
    callback.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_review_callback_show_and_invalid_cases(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Show?"])
    review = await handlers.start_review_session(session, user, deck_id=None)
    card = (await session.execute(select(Card).where(Card.user_id == user.id))).scalar_one()

    malformed = make_callback("review:x")
    await handlers.on_review_callback(malformed)
    malformed.answer.assert_awaited_once_with("Некорректные данные.", show_alert=True)

    stale = make_callback(f"review:missing:{card.id}:show")
    await handlers.on_review_callback(stale)
    assert "Сессия устарела" in stale.answer.await_args.args[0]

    wrong_card = make_callback(f"review:{review.session_id}:999999:show")
    await handlers.on_review_callback(wrong_card)
    assert "не актуальна" in wrong_card.answer.await_args.args[0]

    show = make_callback(f"review:{review.session_id}:{card.id}:show")
    await handlers.on_review_callback(show)
    show.message.edit_text.assert_awaited_once()
    assert "A:Show?" in show.message.edit_text.await_args.args[0]
    show.answer.assert_awaited_once_with()

    markup = show.message.edit_text.await_args.kwargs["reply_markup"]
    all_callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "back_to_main" in all_callbacks

    bad_rate = make_callback(f"review:{review.session_id}:{card.id}:rate:2")
    await handlers.on_review_callback(bad_rate)
    bad_rate.answer.assert_awaited_once_with("Некорректная оценка.", show_alert=True)

    unknown = make_callback(f"review:{review.session_id}:{card.id}:noop")
    await handlers.on_review_callback(unknown)
    unknown.answer.assert_awaited_once_with("Неизвестное действие.", show_alert=True)


@pytest.mark.asyncio
async def test_on_review_callback_ignores_missing_context():
    callback = make_callback("review:x")
    callback.from_user = None
    callback.data = None
    callback.message = None

    await handlers.on_review_callback(callback)
    callback.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_review_callback_rate_paths(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["First?", "Second?"])
    review = await handlers.start_review_session(session, user, deck_id=None)
    first, second = (
        (await session.execute(select(Card).where(Card.user_id == user.id).order_by(Card.id.asc())))
        .scalars()
        .all()
    )

    next_card = make_callback(f"review:{review.session_id}:{first.id}:rate:5")
    await handlers.on_review_callback(next_card)
    next_card.answer.assert_awaited_once_with()

    next_card.message.edit_text.assert_awaited()
    sent_question = next_card.message.edit_text.await_args.args[0]
    assert sent_question == "Second?"

    finish = make_callback(
        f"review:{review.session_id}:{second.id}:rate:5", message=next_card.message
    )
    await handlers.on_review_callback(finish)
    finish.message.edit_text.assert_awaited()
    assert "Сессия завершена" in finish.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_cmd_stats_and_reset(session, monkeypatch, user_with_token):
    patch_session(monkeypatch, session)
    user, _ = user_with_token
    await seed_cards(session, user, deck=None, source_file="a.md", questions=["Q?"])

    stats = make_callback("menu_stats")
    await handlers.cmd_stats(stats)
    stats.message.edit_text.assert_awaited_once()
    assert "Всего карточек: 1" in stats.message.edit_text.await_args.kwargs["text"]

    reset = make_callback("menu_reset")
    await handlers.cmd_reset(reset)
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
    await handlers.on_reset_callback(cancel)
    cancel.message.edit_text.assert_awaited_once()
    assert "Сброс отменён." in cancel.message.edit_text.await_args.args[0]
    cancel.answer.assert_awaited_once_with()

    confirm = make_callback("reset:confirm")
    await handlers.on_reset_callback(confirm)
    confirm.message.edit_text.assert_awaited_once()
    assert "Прогресс сброшен" in confirm.message.edit_text.await_args.args[0]
    confirm.answer.assert_awaited_once_with()

    unknown = make_callback("reset:other")
    await handlers.on_reset_callback(unknown)
    unknown.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_on_set_deck_callback_ignores_missing_context():
    callback = make_callback("setdeck:1:0")
    callback.from_user = None
    callback.data = None
    callback.message = None

    await handlers.on_set_deck_callback(callback)
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
    await handlers._start_deck_review(empty_msg, user.telegram_id, deck.id)
    assert "нет карточек" in empty_msg.answer.await_args.args[0].casefold()

    await seed_cards(session, user, deck="Матан", source_file="a.md", questions=["Math?"])
    full_msg = make_message()
    await handlers._start_deck_review(full_msg, user.telegram_id, deck.id)
    full_msg.answer.assert_awaited_once()
    assert full_msg.answer.await_args.args[0] == "Math?"

    full_cb = make_callback("revdeck:0")
    await handlers._start_deck_review(full_cb, user.telegram_id, deck.id)

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

    # cmd_start теперь принимает (message, state)
    await handlers.cmd_start(message, state)

    await handlers.cmd_token(callback)
    await handlers.prompt_add_deck(callback, state)
    await handlers.prompt_delete_deck(callback, state)
    await handlers.prompt_export_deck(callback, state)
    await handlers.prompt_edit_card_deck(callback, state)
    await handlers.cmd_review(callback)
    await handlers.cmd_stats(callback)
    await handlers.cmd_reset(callback)

    msg_for_process = make_message()
    msg_for_process.from_user = None
    msg_for_process.text = "test"
    await handlers.process_add_deck(msg_for_process, state)
    await handlers.process_delete_deck(msg_for_process, state)
    await handlers.process_export_deck(msg_for_process, state)
    await handlers.process_edit_card_deck(msg_for_process, state)

    message.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    msg_for_process.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_cmd_decks_list_shows_decks_or_empty(session, monkeypatch, user_with_token):
    """Список колод показывает колоды или сообщение о пустом списке"""
    patch_session(monkeypatch, session)
    user, _ = user_with_token

    # Пустой список
    empty = make_callback("decks_list")
    await handlers.cmd_decks_list(empty)
    empty.answer.assert_awaited_once()
    empty.message.edit_text.assert_awaited_once()
    assert "Список колод пуст" in empty.message.edit_text.await_args.kwargs["text"]

    # С колодами
    await create_deck(session, user, "Матан")
    await create_deck(session, user, "Физика")

    with_decks = make_callback("decks_list")
    await handlers.cmd_decks_list(with_decks)
    with_decks.message.edit_text.assert_awaited_once()
    text = with_decks.message.edit_text.await_args.kwargs["text"]
    assert "Ваши колоды:" in text
    assert "Матан" in text or "Физика" in text


@pytest.mark.asyncio
async def test_cmd_decks_list_ignores_missing_user():
    """decks_list не вызывает ничего если from_user=None"""
    callback = make_callback("decks_list")
    callback.from_user = None

    await handlers.cmd_decks_list(callback)

    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_show_main_menu_displays_correct_text():
    """Главное меню показывает правильный текст и кнопки"""
    message = make_message()

    await handlers.show_main_menu(message)

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Главное меню" in text
    assert "Obsidian" in text
    assert "Telegram" in text

    markup = message.answer.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]

    # Проверяем наличие всех основных кнопок
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
    """Настройки показывают статус уведомлений"""
    callback = make_callback("settings")

    with patch.object(handlers, "get_allow_notifications", new=AsyncMock(return_value=True)):
        await handlers.settings_menu(callback)

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
    """Настройки показывают отключённые уведомления"""
    callback = make_callback("settings")

    with patch.object(handlers, "get_allow_notifications", new=AsyncMock(return_value=False)):
        await handlers.settings_menu(callback)

    text = callback.message.edit_text.await_args.kwargs["text"]
    assert "Уведомления: <b>Отключены</b>" in text

    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == "enable_notifications" for btn in buttons)


@pytest.mark.asyncio
async def test_disable_notifications_updates_permission(monkeypatch):
    """Отключение уведомлений вызывает set_notifications_permission"""
    callback = make_callback("disable_notifications")

    with patch.object(handlers, "set_notifications_permission", new=AsyncMock()) as mock_set:
        await handlers.cmd_disable_notifications(callback)

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
    """Включение уведомлений вызывает set_notifications_permission"""
    callback = make_callback("enable_notifications")

    with patch.object(handlers, "set_notifications_permission", new=AsyncMock()) as mock_set:
        await handlers.cmd_enable_notifications(callback)

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
    """disable_notifications не вызывает ничего если from_user=None"""
    callback = make_callback("disable_notifications")
    callback.from_user = None

    await handlers.cmd_disable_notifications(callback)

    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_enable_notifications_ignores_missing_user():
    """enable_notifications не вызывает ничего если from_user=None"""
    callback = make_callback("enable_notifications")
    callback.from_user = None

    await handlers.cmd_enable_notifications(callback)

    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_menu_ignores_missing_user():
    """settings_menu не вызывает ничего если from_user=None"""
    callback = make_callback("settings")
    callback.from_user = None

    await handlers.settings_menu(callback)

    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
