import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

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
from app.services.export_service import DEFAULT_DELIMITER, export_deck_markdown
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


class DeckManagementStates(StatesGroup):
    waiting_for_add_name = State()
    waiting_for_delete_name = State()
    waiting_for_export_name = State()
    waiting_for_edit_question = State()


# --- 2. КЛАВИАТУРЫ ---
def get_main_menu_kb():
    """Клавиатура главного меню"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Получить токен", callback_data="menu_token")],
            [InlineKeyboardButton(text="Повторить карточки", callback_data="menu_review")],
            [InlineKeyboardButton(text="Управление колодами", callback_data="menu_decks")],
            [InlineKeyboardButton(text="Статистика", callback_data="menu_stats")],
            [InlineKeyboardButton(text="Сброс прогресса", callback_data="menu_reset")],
        ]
    )
    return keyboard


def get_decks_menu_kb():
    """Клавиатура меню колод"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить колоду", callback_data="deck_add")],
            [InlineKeyboardButton(text="Удалить колоду", callback_data="deck_delete")],
            [InlineKeyboardButton(text="Сменить колоду карточки", callback_data="deck_edit_card")],
            [InlineKeyboardButton(text="Экспортировать колоду", callback_data="deck_export")],
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
        ]
    )
    return keyboard


def get_back_to_decks_kb():
    """Клавиатура возврата в меню колод"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к колодам", callback_data="menu_decks")]
        ]
    )
    return keyboard


def get_back_to_main_kb():
    """Клавиатура возврата в главное меню"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")]
        ]
    )
    return keyboard


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
            await message.answer(
                "В этой колоде нет карточек для повторения.", reply_markup=get_back_to_main_kb()
            )
            return
        card = await get_current_card(session, review_session)
        if card is None:
            await message.answer(
                "В этой колоде нет карточек для повторения.", reply_markup=get_back_to_main_kb()
            )
            return
        await _send_question(message, review_session.session_id, card)


async def show_main_menu(target: Message | CallbackQuery):
    """Универсальная функция показа главного меню"""
    text = (
        "<b>Главное меню</b>\n\n"
        "Вы создаёте карточки в Obsidian, плагин отправляет их на сервер, "
        "а повторения проходят здесь, в Telegram.\n\n"
        f"🔗 Инструкция: {settings.plugin_install_url}"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=get_main_menu_kb(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=get_main_menu_kb(), parse_mode="HTML")


@router.message(F.text == "/start")
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, message.from_user.id)
    logger.info("Command /start from telegram_id=%s", message.from_user.id)
    await show_main_menu(message)


@router.callback_query(F.data == "back_to_main")
async def process_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await show_main_menu(callback)


@router.callback_query(F.data == "menu_decks")
async def show_decks_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        text="<b>Управление колодами</b>\nВыберите действие:",
        reply_markup=get_decks_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_token")
async def cmd_token(callback: CallbackQuery) -> None:
    await callback.answer()
    token = generate_token()
    token_hash = hash_token(token)
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        user.token_hash = token_hash
        await session.commit()
    logger.info("Token generated for telegram_id=%s", callback.from_user.id)

    await callback.message.edit_text(
        text=f"<b>Ваш токен:</b>\n\n<code>{token}</code>\n\n Сохраните его. Повторно показать этот токен невозможно.",
        reply_markup=get_back_to_main_kb(),
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
        reply_markup=get_back_to_main_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_reset")
async def cmd_reset(callback: CallbackQuery) -> None:
    await callback.answer()
    logger.info("Reset requested by telegram_id=%s", callback.from_user.id)
    await callback.message.edit_text(
        text="<b>Сброс прогресса</b>\n\nСбросить весь прогресс обучения?\nКарточки останутся, но интервалы повторения будут обнулены.",
        reply_markup=reset_confirm_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_review")
async def cmd_review(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        decks = await list_reviewable_decks(session, user)

    if not decks:
        await callback.message.edit_text(
            text="Нет карточек для повторения.\n\nСинхронизируйте карточки из Obsidian или добавьте новые.",
            reply_markup=get_back_to_main_kb(),
            parse_mode="HTML",
        )
        return

    logger.info("Review started by telegram_id=%s", callback.from_user.id)
    await callback.message.edit_text(
        text="<b>Выберите колоду для повторения:</b>",
        reply_markup=review_deck_keyboard(decks),
        parse_mode="HTML",
    )


# --- Добавление колоды ---
@router.callback_query(F.data == "deck_add")
async def prompt_add_deck(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        text="➕ <b>Добавление колоды</b>\n\nВведите название новой колоды одним сообщением:",
        reply_markup=get_back_to_decks_kb(),
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
    # Возвращаем меню колод
    await message.answer(
        "<b>Управление колодами</b>\nВыберите действие:",
        reply_markup=get_decks_menu_kb(),
        parse_mode="HTML",
    )


# --- Удаление колоды ---
@router.callback_query(F.data == "deck_delete")
async def prompt_delete_deck(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        text="➖ <b>Удаление колоды</b>\n\nВведите точное название колоды, которую хотите удалить:",
        reply_markup=get_back_to_decks_kb(),
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
        reply_markup=get_decks_menu_kb(),
        parse_mode="HTML",
    )


# --- Экспорт колоды ---
@router.callback_query(F.data == "deck_export")
async def prompt_export_deck(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        text="<b>Экспорт колоды</b>\n\nВведите название колоды для экспорта:",
        reply_markup=get_back_to_decks_kb(),
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
        reply_markup=get_decks_menu_kb(),
        parse_mode="HTML",
    )


# --- Смена колоды карточки ---
@router.callback_query(F.data == "deck_edit_card")
async def prompt_edit_card_deck(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        text="<b>Смена колоды карточки</b>\n\nВведите точный текст <b>вопроса</b> карточки:",
        reply_markup=get_back_to_decks_kb(),
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
        reply_markup=get_back_to_decks_kb(),
    )
    await callback.answer()


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
                    reply_markup=get_back_to_main_kb(),
                    parse_mode="HTML",
                )
                return

            next_card = await get_current_card(session, review_session)
            if next_card is None:
                await callback.message.edit_text(
                    f"🎉 <b>Сессия завершена!</b>\n\nПовторено карточек: {reviewed_count}",
                    reply_markup=get_back_to_main_kb(),
                    parse_mode="HTML",
                )
                return
            await _send_question(callback.message, session_id, next_card)
            return

    await callback.answer("Неизвестное действие.", show_alert=True)


@router.callback_query(F.data.startswith("reset:"))
async def on_reset_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.edit_text("Сброс отменён.", reply_markup=get_back_to_main_kb())
        await callback.answer()
        return
    if action == "confirm":
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(session, callback.from_user.id)
            count = await reset_progress(session, user)
        await callback.message.edit_text(
            f"<b>Прогресс сброшен.</b>\nКарточек обновлено: {count}",
            reply_markup=get_back_to_main_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await callback.answer()
