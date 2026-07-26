import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from app.bot.keyboards import (
    rate_keyboard,
    reset_confirm_keyboard,
    show_answer_keyboard,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.services.review_service import (
    get_active_session,
    get_current_card,
    get_or_create_user,
    get_stats,
    rate_current_card,
    reset_progress,
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


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, message.from_user.id)
    logger.info("Command /start from telegram_id=%s", message.from_user.id)
    await message.answer(
        "Добро пожаловать в сервис интервального повторения!\n\n"
        "Вы создаёте карточки «вопрос — ответ» в Obsidian, "
        "плагин отправляет их на сервер, а повторения проходят здесь, в Telegram.\n\n"
        "Как это работает:\n"
        "1. Получите токен командой /token\n"
        "2. Установите и настройте Obsidian-плагин\n"
        "3. Синхронизируйте карточки\n"
        "4. Запускайте повторения командой /review\n\n"
        f"Инструкция по установке плагина:\n{settings.plugin_install_url}"
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


@router.message(Command("review"))
async def cmd_review(message: Message) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        review_session = await start_review_session(session, user)
        if review_session is None:
            await message.answer("Нет карточек для повторения. Синхронизируйте карточки из Obsidian.")
            return
        card = await get_current_card(session, review_session)
        if card is None:
            await message.answer("Нет карточек для повторения.")
            return
        logger.info(
            "Command /review telegram_id=%s session=%s cards=%s",
            message.from_user.id,
            review_session.session_id,
            len(review_session.card_ids),
        )
        await _send_question(message, review_session.session_id, card)


@router.callback_query(F.data.startswith("review:"))
async def on_review_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return

    parts = callback.data.split(":")
    # review:{session_id}:{card_id}:show
    # review:{session_id}:{card_id}:rate:{q}
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
