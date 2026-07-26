from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def show_answer_keyboard(session_id: str, card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Показать ответ",
                    callback_data=f"review:{session_id}:{card_id}:show",
                )
            ]
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
            ]
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
