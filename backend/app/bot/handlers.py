import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
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
from app.database import AsyncSessionLocal
from app.models.deck import Deck
from app.services import deck_service
from app.services.deck_service import NO_DECK_LABEL
from app.services.export_service import DEFAULT_DELIMITER, export_deck_markdown
from app.services.notification_service import get_allow_notifications, set_notifications_permission
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


class OnboardingStates(StatesGroup):
    """Состояния онбординга"""

    welcome = State()
    token_step = State()
    install_step = State()
    card_step = State()
    finished = State()


# --- 2. КЛАВИАТУРЫ ---
def get_main_menu_kb():
    """Клавиатура главного меню"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Установка плагина", callback_data="menu_install")],
            [InlineKeyboardButton(text="🔑 Получить новый токен", callback_data="menu_token")],
            [InlineKeyboardButton(text="Повторить карточки", callback_data="menu_review")],
            [InlineKeyboardButton(text="Управление колодами", callback_data="menu_decks")],
            [InlineKeyboardButton(text="Статистика", callback_data="menu_stats")],
            [InlineKeyboardButton(text="Сброс прогресса", callback_data="menu_reset")],
            [InlineKeyboardButton(text="Настройки", callback_data="settings")],
        ]
    )
    return keyboard


def get_decks_menu_kb():
    """Клавиатура меню колод"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мои колоды", callback_data="decks_list")],
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


def get_token_keyboard(token: str, back_callback: str = "back_to_main"):
    """Универсальная клавиатура для отображения токена с кнопкой копирования"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Скопировать токен", copy_text=CopyTextButton(text=token)
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback)],
        ]
    )
    return keyboard


def get_onboarding_start_kb():
    """Клавиатура старта онбординга"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начать настройку", callback_data="onboarding_start")],
            [InlineKeyboardButton(text="✅ Я уже всё установил", callback_data="onboarding_skip")],
        ]
    )
    return keyboard


def get_onboarding_token_kb(token: str):
    """Клавиатура шага с токеном"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Скопировать токен", copy_text=CopyTextButton(text=token)
                )
            ],
            [
                InlineKeyboardButton(
                    text="➡️ Как установить плагин", callback_data="onboarding_install"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Пропустить в главное меню", callback_data="onboarding_finish"
                )
            ],
        ]
    )
    return keyboard


def get_onboarding_install_kb():
    """Клавиатура шага установки плагина"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Установить плагин в Obsidian",
                    url="obsidian://brat?repo=https://github.com/matveyadamey/Spaced-Repetition-Sync",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ У меня нет BRAT", callback_data="onboarding_install_brat"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➡️ Как создавать карточки", callback_data="onboarding_card"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Пропустить в главное меню", callback_data="onboarding_finish"
                )
            ],
        ]
    )
    return keyboard


def get_onboarding_install_brat_kb():
    """Клавиатура инструкции по установке BRAT"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Установить BRAT из Community Store",
                    url="obsidian://show-plugin?id=tfthacker-obsidian42-brat",
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад к установке плагина", callback_data="onboarding_install"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Пропустить в главное меню", callback_data="onboarding_finish"
                )
            ],
        ]
    )
    return keyboard


def get_onboarding_card_kb():
    """Клавиатура шага создания карточки"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово, начнём!", callback_data="onboarding_finish")],
            [
                InlineKeyboardButton(
                    text="🏠 Пропустить в главное меню", callback_data="onboarding_finish"
                )
            ],
        ]
    )
    return keyboard


async def _send_error(target: Message | CallbackQuery, text: str) -> None:
    """Универсальная отправка ошибки: edit_text для callback, answer для message"""
    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=get_back_to_main_kb())
    else:
        await target.answer(text, reply_markup=get_back_to_main_kb())


async def _send_question(target: Message | CallbackQuery, session_id: str, card) -> None:
    """Универсальная отправка вопроса: редактирует сообщение, если это callback"""
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
        await target.message.edit_text(text, reply_markup=get_main_menu_kb(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=get_main_menu_kb(), parse_mode="HTML")


# --- УВЕДОМЛЕНИЯ О ПЕРВОМ SYNC ---
async def notify_first_sync(
    bot: Bot, telegram_id: int, cards_count: int, deck_name: str | None = None
):
    """
    Отправляет поздравление после первого успешного sync из Obsidian.

    Вызывается из sync_service при первом появлении карточек у пользователя.

    Args:
        bot: Инстанс бота aiogram
        telegram_id: ID пользователя в Telegram
        cards_count: Количество карточек в первом sync
        deck_name: Название колоды (опционально)
    """
    deck_text = f" в колоде «{deck_name}»" if deck_name else ""
    text = (
        f"🎉 <b>Отлично! Получено {cards_count} карточек{deck_text}.</b>\n\n"
        "Ваша первая синхронизация прошла успешно. Теперь вы можете начать повторение."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать повторение", callback_data="menu_review")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_main")],
        ]
    )

    try:
        await bot.send_message(
            telegram_id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        logger.info(
            "First sync notification sent to telegram_id=%s cards=%s", telegram_id, cards_count
        )
    except Exception as e:
        logger.warning(
            "Failed to send first sync notification to telegram_id=%s: %s", telegram_id, e
        )


# --- ОНБОРДИНГ ---
async def show_onboarding_welcome(target: Message | CallbackQuery, state: FSMContext):
    """Приветственный экран онбординга"""
    text = (
        "👋 <b>Привет! Это Spaced Repetition Sync.</b>\n\n"
        "Карточки пишете в Obsidian, повторяете здесь.\n\n"
        "Давайте настроим за 3 минуты."
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=get_onboarding_start_kb(), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=get_onboarding_start_kb(), parse_mode="HTML")

    await state.set_state(OnboardingStates.welcome)


async def show_onboarding_token(target: Message | CallbackQuery, state: FSMContext, user_id: int):
    """Шаг 1: получение токена"""
    # Генерируем токен
    token = generate_token()
    token_hash = hash_token(token)

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, user_id)
        user.token_hash = token_hash
        await session.commit()

    logger.info("Onboarding token generated for telegram_id=%s", user_id)

    text = (
        "🔑 <b>Шаг 1/3: Получите токен</b>\n\n"
        f"Ваш токен:\n"
        f"<code>{token}</code>\n\n"
        "Нажмите «📋 Скопировать токен» и вставьте в настройки плагина Obsidian.\n\n"
        "💡 Если потеряете токен — просто сгенерируйте новый в главном меню. "
        "Старый автоматически перестанет работать."
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=get_onboarding_token_kb(token), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=get_onboarding_token_kb(token), parse_mode="HTML")

    await state.set_state(OnboardingStates.token_step)


async def show_onboarding_install(target: Message | CallbackQuery, state: FSMContext):
    """Шаг 2: установка плагина"""
    text = (
        "📦 <b>Шаг 2/3: Установка плагина в Obsidian</b>\n\n"
        "1. Obsidian → Settings → Community plugins → включите\n"
        "2. Установите плагин <b>BRAT</b> (если ещё нет)\n"
        "3. Иконка BRAT → Add a beta plugin\n"
        "4. Вставьте: <code>https://github.com/matveyadamey/Spaced-Repetition-Sync</code>\n"
        "5. Settings → Spaced Repetition Sync → включите\n"
        "6. Вставьте токен в поле Token"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=get_onboarding_install_kb(), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=get_onboarding_install_kb(), parse_mode="HTML")

    await state.set_state(OnboardingStates.install_step)


async def show_onboarding_install_brat(target: Message | CallbackQuery, state: FSMContext):
    """Инструкция по установке BRAT"""
    text = (
        "📦 <b>Установка BRAT</b>\n\n"
        "1. Откройте Obsidian\n"
        "2. Settings → Community plugins → Browse\n"
        "3. Найдите <b>BRAT</b> → Install → Enable\n"
        "4. Вернитесь сюда и нажмите '📦 Установить плагин в Obsidian'"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=get_onboarding_install_brat_kb(), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=get_onboarding_install_brat_kb(), parse_mode="HTML")


async def show_onboarding_card(target: Message | CallbackQuery, state: FSMContext):
    """Шаг 3: создание первой карточки"""
    text = (
        "✍️ <b>Шаг 3/3: Создайте карточку</b>\n\n"
        "Откройте любую заметку и напишите:\n\n"
        "<code>Что такое Python? :: Язык программирования</code>\n\n"
        "Потом откройте палитру (Ctrl/Cmd+P) и выберите\n"
        "«Отправить карточки на сервер».\n\n"
        "💡 После первой синхронизации бот пришлёт вам поздравление!"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=get_onboarding_card_kb(), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=get_onboarding_card_kb(), parse_mode="HTML")

    await state.set_state(OnboardingStates.card_step)


async def finish_onboarding(target: Message | CallbackQuery, state: FSMContext):
    """Завершение онбординга"""
    await state.clear()

    text = (
        "🎉 <b>Настройка завершена!</b>\n\n"
        "Теперь вы можете:\n"
        "• Создавать карточки в Obsidian\n"
        "• Синхронизировать их через плагин\n"
        "• Повторять здесь в Telegram\n\n"
        "Удачи в обучении!"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=get_main_menu_kb(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=get_main_menu_kb(), parse_mode="HTML")


# --- ОБРАБОТЧИКИ КОМАНД ---
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, message.from_user.id)
    logger.info("Command /start from telegram_id=%s", message.from_user.id)

    # Запускаем онбординг
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


# --- ОБРАБОТЧИКИ ОНБОРДИНГА ---
@router.callback_query(F.data == "onboarding_start")
async def onboarding_start_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Начать настройку'"""
    await callback.answer()
    if callback.from_user is None:
        return
    await show_onboarding_token(callback, state, callback.from_user.id)


@router.callback_query(F.data == "onboarding_skip")
async def onboarding_skip_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Я уже всё установил'"""
    await callback.answer()
    await finish_onboarding(callback, state)


@router.callback_query(F.data == "onboarding_install")
async def onboarding_install_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Как установить плагин'"""
    await callback.answer()
    await show_onboarding_install(callback, state)


@router.callback_query(F.data == "onboarding_install_brat")
async def onboarding_install_brat_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'У меня нет BRAT'"""
    await callback.answer()
    await show_onboarding_install_brat(callback, state)


@router.callback_query(F.data == "onboarding_card")
async def onboarding_card_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Как создавать карточки'"""
    await callback.answer()
    await show_onboarding_card(callback, state)


@router.callback_query(F.data == "onboarding_finish")
async def onboarding_finish_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Пропустить в главное меню' или 'Готово, начнём!'"""
    await callback.answer()
    await finish_onboarding(callback, state)


@router.callback_query(F.data == "menu_install")
async def menu_install_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Установка плагина' в главном меню"""
    await callback.answer()
    await show_onboarding_install(callback, state)


# --- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ---
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
    """Генерация нового токена (старый автоматически инвалидируется)"""
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
        reply_markup=get_token_keyboard(token),
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
    if callback.from_user is None:
        return
    await callback.answer()
    logger.info("Reset requested by telegram_id=%s", callback.from_user.id)
    await callback.message.edit_text(
        text="<b>Сброс прогресса</b>\n\nСбросить весь прогресс обучения?\nКарточки останутся, но интервалы повторения будут обнулены.",
        reply_markup=reset_confirm_keyboard(),
        parse_mode="HTML",
    )


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
            text=" Нет карточек для повторения.\n\nСинхронизируйте карточки из Obsidian или добавьте новые.",
            reply_markup=get_back_to_main_kb(),
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
            text=f"<b>Ваши колоды:</b> \n {decks}",
            reply_markup=get_back_to_decks_kb(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            text="Список колод пуст",
            reply_markup=get_back_to_decks_kb(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "deck_add")
async def prompt_add_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
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


@router.callback_query(F.data == "deck_delete")
async def prompt_delete_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
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


@router.callback_query(F.data == "deck_export")
async def prompt_export_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
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


@router.callback_query(F.data == "deck_edit_card")
async def prompt_edit_card_deck(callback: CallbackQuery, state: FSMContext):
    if callback.from_user is None:
        return
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

    await _start_deck_review(callback, callback.from_user.id, deck_id)


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

            await _send_question(callback, session_id, next_card)
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

    if allow:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
                [
                    InlineKeyboardButton(
                        text="Отключить уведомления", callback_data="disable_notifications"
                    )
                ],
            ]
        )
        text_status = "Уведомления: <b>Включены</b>"
    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
                [
                    InlineKeyboardButton(
                        text="Включить уведомления", callback_data="enable_notifications"
                    )
                ],
            ]
        )
        text_status = "Уведомления: <b>Отключены</b>"

    await callback.message.edit_text(
        text=f"⚙️ <b>Настройки</b>\n\n{text_status}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
