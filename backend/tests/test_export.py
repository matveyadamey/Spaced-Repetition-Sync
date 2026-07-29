import pytest
from sqlalchemy import select

from app.models.card import Card
from app.schemas.sync import SyncCardIn
from app.services.deck_service import create_deck
from app.services.export_service import (
    DEFAULT_DELIMITER,
    cards_to_markdown,
    export_deck_markdown,
    format_card,
    safe_filename,
)
from app.services.sync_service import sync_cards


def test_format_card_single_line():
    assert format_card("Q?", "A") == "Q? :: A"


def test_format_card_multiline_when_newlines():
    text = format_card("Q?\nmore", "A\nline")
    assert text == "Q?\nmore\n::\nA\nline"


def test_format_card_multiline_when_delimiter_in_text():
    text = format_card("What is :: here?", "still :: ok")
    assert text == "What is :: here?\n::\nstill :: ok"


def test_safe_filename():
    assert safe_filename("Матан") == "Матан.md"
    assert safe_filename('a/b:c') == "a_b_c.md"


@pytest.mark.asyncio
async def test_export_deck_markdown(session, user_with_token):
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    await sync_cards(
        session,
        user,
        source_file="a.md",
        deck="Матан",
        cards=[
            SyncCardIn(question="What is Python?", answer="A language"),
            SyncCardIn(question="What is SM-2?", answer="Algorithm"),
        ],
    )
    await sync_cards(
        session,
        user,
        source_file="b.md",
        deck=None,
        cards=[SyncCardIn(question="Orphan?", answer="No deck")],
    )

    filename, markdown, count = await export_deck_markdown(session, user, "Матан")
    assert filename == "Матан.md"
    assert count == 2
    assert "What is Python? :: A language" in markdown
    assert "What is SM-2? :: Algorithm" in markdown
    assert "Orphan?" not in markdown
    assert DEFAULT_DELIMITER in markdown


@pytest.mark.asyncio
async def test_export_no_deck_label(session, user_with_token):
    user, _ = user_with_token
    await sync_cards(
        session,
        user,
        source_file="a.md",
        deck=None,
        cards=[SyncCardIn(question="Orphan?", answer="No deck")],
    )
    filename, markdown, count = await export_deck_markdown(session, user, "без колоды")
    assert filename == "без колоды.md"
    assert count == 1
    assert markdown.strip() == "Orphan? :: No deck"


@pytest.mark.asyncio
async def test_export_missing_deck(session, user_with_token):
    user, _ = user_with_token
    with pytest.raises(ValueError, match="не найдена"):
        await export_deck_markdown(session, user, "Нет такой")


@pytest.mark.asyncio
async def test_export_empty_deck(session, user_with_token):
    user, _ = user_with_token
    await create_deck(session, user, "Пустая")
    filename, markdown, count = await export_deck_markdown(session, user, "Пустая")
    assert filename == "Пустая.md"
    assert count == 0
    assert markdown == ""


@pytest.mark.asyncio
async def test_cards_to_markdown_order(session, user_with_token):
    user, _ = user_with_token
    await create_deck(session, user, "D")
    await sync_cards(
        session,
        user,
        source_file="a.md",
        deck="D",
        cards=[
            SyncCardIn(question="First?", answer="1"),
            SyncCardIn(question="Second?", answer="2"),
        ],
    )
    cards = list(
        (
            await session.execute(select(Card).where(Card.user_id == user.id).order_by(Card.id))
        ).scalars()
    )
    md = cards_to_markdown(cards)
    assert md.index("First?") < md.index("Second?")
