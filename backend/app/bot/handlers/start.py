# start, help, back to main menu

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.onboarding import show_onboarding_welcome
from app.bot.handlers.utils import show_main_menu
from app.database import AsyncSessionLocal
from app.services.review_service import get_or_create_user

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, message.from_user.id)
    logger.info("Command /start from telegram_id=%s", message.from_user.id)

    await show_onboarding_welcome(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    """Повторный запуск онбординга"""
    if message.from_user is None:
        return
    logger.info("Command /help from telegram_id=%s", message.from_user.id)
    await show_onboarding_welcome(message, state)


@router.callback_query(F.data == "back_to_main")
async def process_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await show_main_menu(callback)
