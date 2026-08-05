import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.handlers.utils import _send_question, _start_deck_review
from app.bot.keyboards import (
    back_to_main_kb,
    rate_keyboard,
    review_deck_keyboard,
)
from app.database import AsyncSessionLocal
from app.services.review_service import (
    get_active_session,
    get_current_card,
    get_or_create_user,
    list_reviewable_decks,
    rate_current_card,
)

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "menu_review")
async def cmd_review(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    await callback.answer()

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        decks = await list_reviewable_decks(session, user)

    if not decks:
        await callback.message.answer(
            text="Нет карточек для повторения.\n\nСинхронизируйте карточки из Obsidian или добавьте новые.",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
        return

    logger.info("Review started by telegram_id=%s", callback.from_user.id)

    kb = review_deck_keyboard(decks)
    kb.inline_keyboard.append(
        [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")]
    )

    await callback.message.answer(
        text="<b>Выберите колоду для повторения:</b>",
        reply_markup=kb,
        parse_mode="HTML",
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

    deck_token = "0" if deck_id is None else str(deck_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Легкие", callback_data=f"revdiff:{deck_token}:1")],
            [InlineKeyboardButton(text="Легкие+средние", callback_data=f"revdiff:{deck_token}:2")],
            [
                InlineKeyboardButton(
                    text="Все (включая новые)", callback_data=f"revdiff:{deck_token}:3"
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад к выбору колоды", callback_data="menu_review")],
        ]
    )

    await callback.message.edit_text(
        text="<b>Выберите сложность карточек:</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("revdiff:"))
async def on_review_diff_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    _, deck_token, diff_token = parts

    try:
        deck_id = None if deck_token == "0" else int(deck_token)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    try:
        difficulty = int(diff_token)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await callback.answer()

    # Передаем выбранную сложность дальше
    await _start_deck_review(callback, callback.from_user.id, deck_id, difficulty=difficulty)


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
            await callback.answer("Сессия устарела. Запустите повторение заново.", show_alert=True)
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

            finished, reviewed_count = await rate_current_card(session, review_session, card_id, q)
            await callback.answer()

            if finished:
                await callback.message.edit_text(
                    f"🎉 <b>Сессия завершена!</b>\n\nПовторено карточек: {reviewed_count}",
                    reply_markup=back_to_main_kb(),
                    parse_mode="HTML",
                )
                return
            next_card = await get_current_card(session, review_session)
            if next_card is None:
                await callback.message.edit_text(
                    f"🎉 <b>Сессия завершена!</b>\n\nПовторено карточек: {reviewed_count}",
                    reply_markup=back_to_main_kb(),
                    parse_mode="HTML",
                )
                return

            await _send_question(callback, session_id, next_card)
            return

    await callback.answer("Неизвестное действие.", show_alert=True)
