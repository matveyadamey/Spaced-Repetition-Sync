import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.utils import OnboardingStates
from app.bot.keyboards import (
    main_menu_kb,
    onboarding_card_kb,
    onboarding_install_brat_kb,
    onboarding_install_kb,
    onboarding_start_kb,
    onboarding_token_kb,
)
from app.database import AsyncSessionLocal
from app.services.review_service import get_or_create_user
from app.services.token_service import generate_token, hash_token

logger = logging.getLogger(__name__)
router = Router()


async def show_onboarding_welcome(target: Message | CallbackQuery, state: FSMContext):
    """Приветственный экран онбординга"""
    text = (
        "👋 <b>Привет! Это Spaced Repetition Sync.</b>\n\n"
        "Карточки пишете в Obsidian, повторяете здесь.\n\n"
        "Давайте настроим за 3 минуты."
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=onboarding_start_kb(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=onboarding_start_kb(), parse_mode="HTML")

    await state.set_state(OnboardingStates.welcome)


async def show_onboarding_token(target: Message | CallbackQuery, state: FSMContext, user_id: int):
    """Шаг 1: получение токена с кнопкой копирования"""
    token = generate_token()
    token_hash = hash_token(token)

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, user_id)
        user.token_hash = token_hash
        await session.commit()

    logger.info("Onboarding token generated for telegram_id=%s", user_id)

    text = (
        "🔑 <b>Шаг 1/3: Получите токен</b>\n\n"
        f"Ваш токен:\n<code>{token}</code>\n\n"
        "Нажмите «📋 Скопировать токен» и вставьте в настройки плагина Obsidian.\n\n"
        "💡 Если потеряете токен — просто сгенерируйте новый в главном меню. "
        "Старый автоматически перестанет работать."
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=onboarding_token_kb(token), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=onboarding_token_kb(token), parse_mode="HTML")

    await state.set_state(OnboardingStates.token_step)


async def show_onboarding_install(target: Message | CallbackQuery, state: FSMContext):
    """Шаг 2: установка плагина ("""
    text = (
        "<b>Шаг 2/3: Установка плагина в Obsidian</b>\n\n"
        "1. Скачайте и установите Obsidian\n"
        "2. Установите плагин <b>BRAT</b>(по кнопке ниже инструкция по установке)\n"
        "3. Вернитесь на основной экран Obsidian. На боковой панели нажмите на появившийся значок BRAT — откроется меню.\n"
        "4. Выберите <b>Add a beta plugin for testing</b> \n"
        "5. В поле <b>Repository</b> Вставьте ссылку на репозиторий:\n"
        "<code>https://github.com/matveyadamey/Spaced-Repetition-Sync</code>\n"
        "6. В Select a version выберите latest. Нажмите Add plugin. Плагин установится.\n"
        "7. Откройте настройки → Сторонние плагины → Spaced Repetition Sync и включите его \n"
        "8. Вставьте токен в поле <b>Token</b>"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=onboarding_install_kb(), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=onboarding_install_kb(), parse_mode="HTML")

    await state.set_state(OnboardingStates.install_step)


async def show_onboarding_install_brat(target: Message | CallbackQuery, state: FSMContext):
    """Инструкция по установке BRAT"""
    text = (
        "<b>Установка BRAT</b>\n\n"
        "1. Откройте Obsidian\n"
        "2. Settings → Community plugins → <b>Browse</b>\n"
        "3. Найдите <b>BRAT</b> → Install → Enable\n"
        "4. Вернитесь к установке плагина"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(
            text, reply_markup=onboarding_install_brat_kb(), parse_mode="HTML"
        )
    else:
        await target.answer(text, reply_markup=onboarding_install_brat_kb(), parse_mode="HTML")


async def show_onboarding_card(target: Message | CallbackQuery, state: FSMContext):
    """Шаг 3: создание первой карточки"""
    text = (
        "✍️ <b>Шаг 3/3: Создайте карточку</b>\n\n"
        "Откройте любую заметку и напишите:\n\n"
        "<code>Что такое Python? :: Язык программирования</code>\n\n"
        "Потом откройте палитру (Ctrl/Cmd+P) и выберите\n"
        "<b>«Отправить карточки на сервер»</b>.\n"
        "Выберите колоду (или + Добавить колоду / без колоды). \n"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=onboarding_card_kb(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=onboarding_card_kb(), parse_mode="HTML")

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
        await target.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


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
    """Пользователь нажал 'Как установить BRAT'"""
    await callback.answer()
    await show_onboarding_install_brat(callback, state)


@router.callback_query(F.data == "onboarding_card")
async def onboarding_card_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Как создавать карточки'"""
    await callback.answer()
    await show_onboarding_card(callback, state)


@router.callback_query(F.data == "onboarding_finish")
async def onboarding_finish_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Пропустить' или 'Готово, начнём!'"""
    await callback.answer()
    await finish_onboarding(callback, state)


@router.callback_query(F.data == "menu_install")
async def menu_install_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Установка плагина' в главном меню"""
    await callback.answer()
    await show_onboarding_install(callback, state)
