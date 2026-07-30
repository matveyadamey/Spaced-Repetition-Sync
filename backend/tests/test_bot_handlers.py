from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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
    )


# ==========================================
# 1. БАЗОВЫЕ ТЕСТЫ И НАВИГАЦИЯ
# ==========================================


@pytest.mark.asyncio
async def test_cmd_start_creates_user_and_sends_help(session, monkeypatch):
    patch_session(monkeypatch, session)
    message = make_message(555)

    await handlers.cmd_start(message)

    user = await get_or_create_user(session, 555)
    assert user.telegram_id == 555
    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    # Проверяем новый текст меню
    assert "Главное меню" in text
    assert "https://github.com/matveyadamey/Spaced-Repetition-Sync" in text


@pytest.mark.asyncio
async def test_process_back():
    callback = make_callback("back_to_main")
    state = make_state()
    await handlers.process_back(callback, state)
    state.clear.assert_awaited_once()
    # Теперь это сработает благодаря исправлению в show_main_menu
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
    assert "Ваш токен" in callback.message.edit_text.await_args.kwargs["text"]


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
    # Проверяем список вызовов, так как их теперь два (успех + возврат в меню)
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

    # После отправки документа тоже отправляется меню
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

    # Prompt
    cb = make_callback("deck_edit_card")
    await handlers.prompt_edit_card_deck(cb, state)

    # Process: not found
    not_found = make_message()
    not_found.text = "Нет такой?"
    await handlers.process_edit_card_deck(not_found, state)
    assert "не найдена" in not_found.answer.await_args.args[0]

    # Process: ok
    ok = make_message()
    ok.text = "Что такое Python?"
    await handlers.process_edit_card_deck(ok, state)
    ok.answer.assert_awaited_once()
    markup = ok.answer.await_args.kwargs["reply_markup"]
    buttons = [row[0].callback_data for row in markup.inline_keyboard]
    assert buttons[0].startswith("setdeck:")
    assert any("Матан" == row[0].text for row in markup.inline_keyboard)


# ==========================================
# 3. ТЕСТЫ CALLBACK КНОПОК
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

    # Message handlers
    message = make_message()
    message.from_user = None

    # Callback handlers
    cb_message = make_message()
    callback = make_callback("menu_token", message=cb_message)
    callback.from_user = None

    state = make_state()

    # Проверяем Message handlers
    await handlers.cmd_start(message)

    # Проверяем Callback handlers
    await handlers.cmd_token(callback)
    await handlers.prompt_add_deck(callback, state)
    await handlers.prompt_delete_deck(callback, state)
    await handlers.prompt_export_deck(callback, state)
    await handlers.prompt_edit_card_deck(callback, state)
    await handlers.cmd_review(callback)
    await handlers.cmd_stats(callback)
    await handlers.cmd_reset(callback)

    # Process handlers (Message)
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
