import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.handlers.utils import DeckManagementStates
from app.bot.keyboards import (
    back_to_decks_kb,
    decks_menu_kb,
    edit_card_deck_keyboard,
)
from app.database import AsyncSessionLocal
from app.models.deck import Deck
from app.services import deck_service
from app.services.deck_service import NO_DECK_LABEL
from app.services.export_service import DEFAULT_DELIMITER, export_deck_markdown
from app.services.review_service import (
    find_card_by_question,
    get_or_create_user,
    set_card_deck,
)

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "menu_decks")
async def show_decks_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        text="<b>Управление колодами</b>\nВыберите действие:",
        reply_markup=decks_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "decks_list")
async def cmd_decks_list(callback: CallbackQuery):
    if callback.from_user is None:
        return

    await callback.answer()

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        decks = await deck_service.list_names_of_decks(session, user)

    if len(decks) > 0:
        await callback.message.edit_text(
            text=f"<b>Ваши колоды:</b>\n{decks}",
            reply_markup=back_to_decks_kb(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            text="Список колод пуст",
            reply_markup=back_to_decks_kb(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "deck_add")
async def prompt_add_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
    await callback.answer()
    await callback.message.edit_text(
        text="➕ <b>Добавление колоды</b>\n\nВведите название новой колоды одним сообщением:",
        reply_markup=back_to_decks_kb(),
        parse_mode="HTML",
    )
    await state.set_state(DeckManagementStates.waiting_for_add_name)


@router.message(DeckManagementStates.waiting_for_add_name)
async def process_add_deck(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    name = message.text.strip()
    if not name:
        await message.answer(
            "Название не может быть пустым. Попробуйте ещё раз или нажмите 'Назад'."
        )
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        try:
            deck = await deck_service.create_deck(session, user, name)
        except ValueError as exc:
            await message.answer(f"Ошибка: {exc}")
            return

    logger.info("Deck added: telegram_id=%s deck=%s", message.from_user.id, deck.name)
    await message.answer(f"Колода <b>{deck.name}</b> успешно создана!", parse_mode="HTML")
    await state.clear()
    await message.answer(
        "<b>Управление колодами</b>\nВыберите действие:",
        reply_markup=decks_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "deck_delete")
async def prompt_delete_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
    await callback.answer()
    await callback.message.edit_text(
        text="➖ <b>Удаление колоды</b>\n\nВведите точное название колоды, которую хотите удалить:",
        reply_markup=back_to_decks_kb(),
        parse_mode="HTML",
    )
    await state.set_state(DeckManagementStates.waiting_for_delete_name)


@router.message(DeckManagementStates.waiting_for_delete_name)
async def process_delete_deck(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    name = message.text.strip()
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        try:
            await deck_service.delete_deck(session, user, name)
        except ValueError as exc:
            await message.answer(f"Ошибка: {exc}")
            return
    logger.info("Deck deleted: telegram_id=%s deck=%s", message.from_user.id, name)
    await message.answer(
        f"Колода <b>{name}</b> удалена. Карточки из неё перемещены в «{NO_DECK_LABEL}».",
        parse_mode="HTML",
    )
    await state.clear()
    await message.answer(
        "<b>Управление колодами</b>\nВыберите действие:",
        reply_markup=decks_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "deck_export")
async def prompt_export_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
    await callback.answer()
    await callback.message.edit_text(
        text="<b>Экспорт колоды</b>\n\nВведите название колоды для экспорта:",
        reply_markup=back_to_decks_kb(),
        parse_mode="HTML",
    )
    await state.set_state(DeckManagementStates.waiting_for_export_name)


@router.message(DeckManagementStates.waiting_for_export_name)
async def process_export_deck(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    name = message.text.strip()
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        try:
            filename, markdown, count = await export_deck_markdown(session, user, name)
        except ValueError as exc:
            await message.answer(f"❌ Ошибка: {exc}")
            return

    if count == 0:
        await message.answer("⚠️ В этой колоде нет карточек.")
    else:
        document = BufferedInputFile(markdown.encode("utf-8"), filename=filename)
        logger.info("Deck exported: telegram_id=%s cards=%s", message.from_user.id, count)
        await message.answer_document(
            document,
            caption=f"Экспорт завершён: {count} карт.\nРазделитель: `{DEFAULT_DELIMITER}`",
            parse_mode="Markdown",
        )

    await state.clear()
    await message.answer(
        "<b>Управление колодами</b>\nВыберите действие:",
        reply_markup=decks_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "deck_edit_card")
async def prompt_edit_card_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
    await callback.answer()
    await callback.message.edit_text(
        text="<b>Смена колоды карточки</b>\n\nВведите точный текст <b>вопроса</b> карточки:",
        reply_markup=back_to_decks_kb(),
        parse_mode="HTML",
    )
    await state.set_state(DeckManagementStates.waiting_for_edit_question)


@router.message(DeckManagementStates.waiting_for_edit_question)
async def process_edit_card_deck(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    question = message.text.strip()
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        card = await find_card_by_question(session, user, question)
        if card is None:
            await message.answer("Карточка с таким вопросом не найдена. Проверьте текст.")
            return
        decks = await deck_service.list_decks(session, user)
        keyboard = edit_card_deck_keyboard(card.id, [(d.id, d.name) for d in decks])

    await message.answer(
        text=f"Карточка найдена!\n\n<b>Вопрос:</b> {question}\n\nВыберите новую колоду:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await state.clear()


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

    await callback.message.edit_text(
        f"Колода карточки обновлена: <b>{label}</b>",
        parse_mode="HTML",
        reply_markup=back_to_decks_kb(),
    )
    await callback.answer()
