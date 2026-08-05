from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from app.services.deck_service import NO_DECK_LABEL


# --- КЛАВИАТУРЫ РЕЖИМА ПОВТОРЕНИЯ ---
def show_answer_keyboard(session_id: str, card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Показать ответ",
                    callback_data=f"review:{session_id}:{card_id}:show",
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
        ]
    )


def rate_keyboard(session_id: str, card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сложно",
                    callback_data=f"review:{session_id}:{card_id}:rate:1",
                ),
                InlineKeyboardButton(
                    text="Средне",
                    callback_data=f"review:{session_id}:{card_id}:rate:3",
                ),
                InlineKeyboardButton(
                    text="Легко",
                    callback_data=f"review:{session_id}:{card_id}:rate:5",
                ),
            ],
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
        ]
    )


def reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить сброс", callback_data="reset:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="reset:cancel"),
            ]
        ]
    )


def review_deck_keyboard(decks: list[tuple[int | None, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for deck_id, label in decks:
        token = "0" if deck_id is None else str(deck_id)
        rows.append([InlineKeyboardButton(text=label, callback_data=f"revdeck:{token}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_card_deck_keyboard(card_id: int, decks: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=NO_DECK_LABEL, callback_data=f"setdeck:{card_id}:0")]
    ]
    for deck_id, name in decks:
        rows.append(
            [
                InlineKeyboardButton(
                    text=name,
                    callback_data=f"setdeck:{card_id}:{deck_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- КЛАВИАТУРЫ ГЛАВНОГО МЕНЮ И НАВИГАЦИИ ---
def main_menu_kb() -> InlineKeyboardMarkup:
    """Клавиатура главного меню"""
    return InlineKeyboardMarkup(
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


def decks_menu_kb() -> InlineKeyboardMarkup:
    """Клавиатура меню колод"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мои колоды", callback_data="decks_list")],
            [InlineKeyboardButton(text="Добавить колоду", callback_data="deck_add")],
            [InlineKeyboardButton(text="Удалить колоду", callback_data="deck_delete")],
            [InlineKeyboardButton(text="Сменить колоду карточки", callback_data="deck_edit_card")],
            [InlineKeyboardButton(text="Экспортировать колоду", callback_data="deck_export")],
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")],
        ]
    )


def back_to_decks_kb() -> InlineKeyboardMarkup:
    """Клавиатура возврата в меню колод"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к колодам", callback_data="menu_decks")]
        ]
    )


def back_to_main_kb() -> InlineKeyboardMarkup:
    """Клавиатура возврата в главное меню"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="back_to_main")]
        ]
    )


# --- КЛАВИАТУРЫ ОНБОРДИНГА ---
def onboarding_start_kb() -> InlineKeyboardMarkup:
    """Клавиатура старта онбординга"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начать настройку", callback_data="onboarding_start")],
            [InlineKeyboardButton(text="✅ Я уже всё установил", callback_data="onboarding_skip")],
        ]
    )


def onboarding_token_kb(token: str) -> InlineKeyboardMarkup:
    """Клавиатура шага с токеном — кнопка копирования через CopyTextButton"""
    return InlineKeyboardMarkup(
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


def onboarding_install_kb() -> InlineKeyboardMarkup:
    """Клавиатура шага установки плагина — только https ссылки"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Репозиторий плагина",
                    url="https://github.com/matveyadamey/Spaced-Repetition-Sync",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Как установить BRAT", callback_data="onboarding_install_brat"
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


def onboarding_install_brat_kb() -> InlineKeyboardMarkup:
    """Клавиатура инструкции по установке BRAT"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Репозиторий BRAT", url="https://github.com/TfTHacker/obsidian42-brat"
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


def onboarding_card_kb() -> InlineKeyboardMarkup:
    """Клавиатура шага создания карточки"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово, начнём!", callback_data="onboarding_finish")],
            [
                InlineKeyboardButton(
                    text="🏠 Пропустить в главное меню", callback_data="onboarding_finish"
                )
            ],
        ]
    )


# --- КЛАВИАТУРЫ ТОКЕНА ---
def token_keyboard(token: str, back_callback: str = "back_to_main") -> InlineKeyboardMarkup:
    """Универсальная клавиатура для отображения токена с кнопкой копирования"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Скопировать токен", copy_text=CopyTextButton(text=token)
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback)],
        ]
    )


# --- КЛАВИАТУРЫ УВЕДОМЛЕНИЙ ---
def first_sync_notification_kb() -> InlineKeyboardMarkup:
    """Клавиатура поздравления после первого sync"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать повторение", callback_data="menu_review")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_main")],
        ]
    )
