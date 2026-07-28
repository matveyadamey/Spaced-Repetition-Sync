import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    edit_card_deck_keyboard,
    rate_keyboard,
    reset_confirm_keyboard,
    review_deck_keyboard,
    show_answer_keyboard,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.deck import Deck
from app.services import deck_service
from app.services.deck_service import NO_DECK_LABEL
from app.services.review_service import (
    find_card_by_question,
    get_active_session,
    get_current_card,
    get_or_create_user,
    get_stats,
    list_reviewable_decks,
    rate_current_card,
    reset_progress,
    set_card_deck,
    start_review_session,
)
from app.services.token_service import generate_token, hash_token

logger = logging.getLogger(__name__)
router = Router()


async def _send_question(message: Message, session_id: str, card) -> None:
    await message.answer(
        card.question,
        reply_markup=show_answer_keyboard(session_id, card.id),
    )


async def _start_deck_review(message: Message, user_telegram_id: int, deck_id: int | None) -> None:
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, user_telegram_id)
        review_session = await start_review_session(session, user, deck_id=deck_id)
        if review_session is None:
            await message.answer("В этой колоде нет карточек для повторения.")
            return
        card = await get_current_card(session, review_session)
        if card is None:
            await message.answer("В этой колоде нет карточек для повторения.")
            return
        await _send_question(message, review_session.session_id, card)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, message.from_user.id)
    logger.info("Command /start from telegram_id=%s", message.from_user.id)
    await message.answer(
        "Добро пожаловать в сервис интервального повторения!\n\n"
        "Вы создаёте карточки в Obsidian, плагин отправляет их на сервер, "
        "а повторения проходят здесь, в Telegram.\n\n"
        "Команды:\n"
        "/token — токен для плагина\n"
        "/review — повторение по колоде\n"
        "/add_deck название — создать колоду\n"
        "/delete_deck название — удалить колоду\n"
        "/edit_card_deck вопрос — сменить колоду карточки\n"
        "/stats — статистика\n"
        "/reset — сброс прогресса\n\n"
        f"Инструкция:\n{settings.plugin_install_url}"
    )


@router.message(Command("token"))
async def cmd_token(message: Message) -> None:
    if message.from_user is None:
        return
    token = generate_token()
    token_hash = hash_token(token)
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        user.token_hash = token_hash
        await session.commit()
    logger.info("Command /token for telegram_id=%s", message.from_user.id)
    await message.answer(
        f"Ваш токен:\n{token}\n\n"
        "Сохраните его. Повторно показать этот токен невозможно."
    )


@router.message(Command("add_deck"))
async def cmd_add_deck(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    name = (command.args or "").strip()
    if not name:
        await message.answer("Укажите название колоды.\nПример: /add_deck Матан")
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        try:
            deck = await deck_service.create_deck(session, user, name)
        except ValueError as exc:
            await message.answer(str(exc))
            return
    logger.info("Command /add_deck telegram_id=%s deck=%s", message.from_user.id, deck.name)
    await message.answer(f"Колода создана: {deck.name}")


@router.message(Command("delete_deck"))
async def cmd_delete_deck(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    name = (command.args or "").strip()
    if not name:
        await message.answer("Укажите название колоды.\nПример: /delete_deck Матан")
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        try:
            await deck_service.delete_deck(session, user, name)
        except ValueError as exc:
            await message.answer(str(exc))
            return
    logger.info("Command /delete_deck telegram_id=%s", message.from_user.id)
    await message.answer(
        f"Колода удалена. Карточки из неё теперь в «{NO_DECK_LABEL}»."
    )


@router.message(Command("edit_card_deck"))
async def cmd_edit_card_deck(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    question = (command.args or "").strip()
    if not question:
        await message.answer(
            "Укажите вопрос карточки.\nПример: /edit_card_deck Что такое Python?"
        )
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        card = await find_card_by_question(session, user, question)
        if card is None:
            await message.answer("Карточка с таким вопросом не найдена.")
            return
        decks = await deck_service.list_decks(session, user)
        keyboard = edit_card_deck_keyboard(
            card.id, [(d.id, d.name) for d in decks]
        )
    await message.answer(
        f"Выберите колоду для карточки:\n{question}",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("setdeck:"))
async def on_set_deck_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректные данные.", show_alert=True)
        return
    try:
        card_id = int(parts[1])
        deck_token = int(parts[2])
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return
    deck_id = None if deck_token == 0 else deck_token
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            card = await set_card_deck(session, user, card_id, deck_id)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        if card is None:
            await callback.answer("Карточка не найдена.", show_alert=True)
            return
        label = NO_DECK_LABEL
        if deck_id is not None:
            deck = await session.get(Deck, deck_id)
            label = deck.name if deck else label
    await callback.message.edit_text(f"Колода карточки обновлена: {label}")
    await callback.answer()


@router.message(Command("review"))
async def cmd_review(message: Message) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        decks = await list_reviewable_decks(session, user)
    if not decks:
        await message.answer(
            "Нет карточек для повторения. Синхронизируйте карточки из Obsidian."
        )
        return
    logger.info("Command /review telegram_id=%s pick_deck count=%s", message.from_user.id, len(decks))
    await message.answer(
        "Выберите колоду для повторения:",
        reply_markup=review_deck_keyboard(decks),
    )


@router.callback_query(F.data.startswith("revdeck:"))
async def on_review_deck_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    token = callback.data.split(":", 1)[1]
    try:
        deck_id = None if token == "0" else int(token)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _start_deck_review(callback.message, callback.from_user.id, deck_id)


@router.callback_query(F.data.startswith("review:"))
async def on_review_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    _, session_id, card_id_str, action, *rest = parts
    try:
        card_id = int(card_id_str)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        review_session = await get_active_session(session, user.id, session_id)
        if review_session is None:
            await callback.answer("Сессия устарела. Запустите /review.", show_alert=True)
            return

        current = await get_current_card(session, review_session)
        if current is None or current.id != card_id:
            await callback.answer("Эта карточка уже не актуальна.", show_alert=True)
            return

        if action == "show":
            await callback.message.edit_text(
                f"{current.question}\n\n{current.answer}",
                reply_markup=rate_keyboard(session_id, card_id),
            )
            await callback.answer()
            return

        if action == "rate" and rest:
            try:
                q = int(rest[0])
            except ValueError:
                await callback.answer("Некорректная оценка.", show_alert=True)
                return
            if q not in (1, 3, 5):
                await callback.answer("Некорректная оценка.", show_alert=True)
                return

            finished, reviewed_count = await rate_current_card(
                session, review_session, card_id, q
            )
            await callback.answer()

            if finished:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(
                    f"Сессия завершена.\n\nПовторено карточек: {reviewed_count}"
                )
                return

            next_card = await get_current_card(session, review_session)
            if next_card is None:
                await callback.message.answer(
                    f"Сессия завершена.\n\nПовторено карточек: {reviewed_count}"
                )
                return
            await _send_question(callback.message, session_id, next_card)
            return

    await callback.answer("Неизвестное действие.", show_alert=True)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        stats = await get_stats(session, user)
    logger.info("Command /stats telegram_id=%s", message.from_user.id)
    await message.answer(
        f"Всего карточек: {stats['total']}\n"
        f"К повторению сегодня: {stats['due']}\n"
        f"Повторено сегодня: {stats['reviewed_today']}\n"
        f"Изучено: {stats['learned_pct']}%"
    )


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    if message.from_user is None:
        return
    logger.info("Command /reset telegram_id=%s", message.from_user.id)
    await message.answer(
        "Сбросить весь прогресс обучения?\nКарточки останутся, интервалы будут обнулены.",
        reply_markup=reset_confirm_keyboard(),
    )


@router.callback_query(F.data.startswith("reset:"))
async def on_reset_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.edit_text("Сброс отменён.")
        await callback.answer()
        return
    if action == "confirm":
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(session, callback.from_user.id)
            count = await reset_progress(session, user)
        await callback.message.edit_text(f"Прогресс сброшен. Карточек обновлено: {count}")
        await callback.answer()
        return
    await callback.answer()
