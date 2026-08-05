# состояния и общие функции

import logging

from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import back_to_main_kb, main_menu_kb, show_answer_keyboard
from app.database import AsyncSessionLocal
from app.services.review_service import (
    get_current_card,
    get_or_create_user,
    start_review_session,
)

logger = logging.getLogger(__name__)


# --- СОСТОЯНИЯ (STATES) ---
class DeckManagementStates(StatesGroup):
    waiting_for_add_name = State()
    waiting_for_delete_name = State()
    waiting_for_export_name = State()
    waiting_for_edit_question = State()


class OnboardingStates(StatesGroup):
    """Состояния онбординга"""

    welcome = State()
    token_step = State()
    install_step = State()
    card_step = State()
    finished = State()


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def _send_error(target: Message | CallbackQuery, text: str) -> None:
    """Универсальная отправка ошибки"""
    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=back_to_main_kb())
    else:
        await target.answer(text, reply_markup=back_to_main_kb())


async def _send_question(target: Message | CallbackQuery, session_id: str, card) -> None:
    """Универсальная отправка вопроса"""
    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            card.question,
            reply_markup=show_answer_keyboard(session_id, card.id),
        )
    else:
        await target.answer(
            card.question,
            reply_markup=show_answer_keyboard(session_id, card.id),
        )


async def _start_deck_review(
    target: Message | CallbackQuery, user_telegram_id: int, deck_id: int | None
) -> None:
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, user_telegram_id)
        review_session = await start_review_session(session, user, deck_id=deck_id)
        if review_session is None:
            await _send_error(target, "В этой колоде нет карточек для повторения.")
            return
        card = await get_current_card(session, review_session)
        if card is None:
            await _send_error(target, "В этой колоде нет карточек для повторения.")
            return

        await _send_question(target, review_session.session_id, card)


async def show_main_menu(target: Message | CallbackQuery):
    """Универсальная функция показа главного меню"""
    text = (
        "<b>Главное меню</b>\n\n"
        "Вы создаёте карточки в Obsidian, плагин отправляет их на сервер, "
        "а повторения проходят здесь, в Telegram."
    )
    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")
