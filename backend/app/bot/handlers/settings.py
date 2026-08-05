import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards import (
    back_to_main_kb,
    reset_confirm_keyboard,
    token_keyboard,
)
from app.database import AsyncSessionLocal
from app.services.notification_service import get_allow_notifications, set_notifications_permission
from app.services.review_service import get_or_create_user, get_stats, reset_progress
from app.services.token_service import generate_token, hash_token

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "menu_token")
async def cmd_token(callback: CallbackQuery) -> None:
    """Генерация нового токена"""
    if callback.from_user is None:
        return
    await callback.answer()
    token = generate_token()
    token_hash = hash_token(token)
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        user.token_hash = token_hash
        await session.commit()
    logger.info("Token generated for telegram_id=%s", callback.from_user.id)

    text = (
        f"<b>🔑 Новый токен</b>\n\n"
        f"<code>{token}</code>\n\n"
        "Нажмите «📋 Скопировать токен» и вставьте в настройки плагина Obsidian.\n\n"
        "⚠️ Старый токен автоматически перестаёт работать. Если не успели скопировать — "
        "просто сгенерируйте новый."
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=token_keyboard(token),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_stats")
async def cmd_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        stats = await get_stats(session, user)
    logger.info("Stats viewed by telegram_id=%s", callback.from_user.id)
    await callback.message.edit_text(
        text=(
            f"<b>Статистика</b>\n\n"
            f"Всего карточек: {stats['total']}\n"
            f"К повторению сегодня: {stats['due']}\n"
            f"Повторено сегодня: {stats['reviewed_today']}\n"
            f"Изучено: {stats['learned_pct']}%"
        ),
        reply_markup=back_to_main_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_reset")
async def cmd_reset(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer()
    logger.info("Reset requested by telegram_id=%s", callback.from_user.id)
    await callback.message.edit_text(
        text="<b>Сброс прогресса</b>\n\nСбросить весь прогресс обучения?\nКарточки останутся, но интервалы повторения будут обнулены.",
        reply_markup=reset_confirm_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("reset:"))
async def on_reset_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.edit_text("Сброс отменён.", reply_markup=back_to_main_kb())
        await callback.answer()
        return
    if action == "confirm":
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(session, callback.from_user.id)
            count = await reset_progress(session, user)
        await callback.message.edit_text(
            f"<b>Прогресс сброшен.</b>\nКарточек обновлено: {count}",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(F.data == "disable_notifications")
async def cmd_disable_notifications(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer()

    await set_notifications_permission(callback.from_user.id, False)

    await callback.message.edit_text(
        text="Уведомления отключены",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
                [
                    InlineKeyboardButton(
                        text="Включить уведомления", callback_data="enable_notifications"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "enable_notifications")
async def cmd_enable_notifications(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer()

    await set_notifications_permission(callback.from_user.id, True)

    await callback.message.edit_text(
        text="Уведомления включены",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
                [
                    InlineKeyboardButton(
                        text="Отключить уведомления", callback_data="disable_notifications"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings")
async def settings_menu(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer()

    allow = await get_allow_notifications(callback.from_user.id)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="◀️ Назад в главное меню",
        callback_data="back_to_main",
    )

    builder.button(
        text="Отключить уведомления" if allow else "Включить уведомления",
        callback_data="disable_notifications" if allow else "enable_notifications",
    )

    builder.adjust(1)

    status = "Включены" if allow else "Отключены"

    await callback.message.edit_text(
        text=f"⚙️ <b>Настройки</b>\n\nУведомления: <b>{status}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
