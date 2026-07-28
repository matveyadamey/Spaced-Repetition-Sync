from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.deck_service import NO_DECK_LABEL


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


def review_deck_keyboard(decks: list[tuple[int | None, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for deck_id, label in decks:
        token = "0" if deck_id is None else str(deck_id)
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"revdeck:{token}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_card_deck_keyboard(
    card_id: int, decks: list[tuple[int, str]]
) -> InlineKeyboardMarkup:
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
