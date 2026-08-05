import pytest
from app.models.card import Card
from app.schemas.sync import SyncCardIn
from app.services import deck_service
from app.services.deck_service import (
    NO_DECK_LABEL,
    create_deck,
    delete_deck,
    list_decks_with_card_counts,
    list_names_of_decks,
    normalize_deck_name,
    resolve_deck_id,
)
from app.services.sync_service import sync_cards
from sqlalchemy import select


def test_normalize_deck_name():
    assert normalize_deck_name("  Матан   ") == "матан"
    assert normalize_deck_name("БЕЗ КОЛОДЫ") == "без колоды"
    assert normalize_deck_name("  без   колоды  ") == "без колоды"
    assert normalize_deck_name("") == ""


@pytest.mark.asyncio
async def test_create_deck_and_list(session, user_with_token):
    user, _ = user_with_token

    deck = await create_deck(session, user, "  Матан  ")

    assert deck.name == "Матан"
    assert deck.name_normalized == "матан"

    decks = await deck_service.list_decks(session, user)
    assert [d.name for d in decks] == ["Матан"]


@pytest.mark.asyncio
async def test_create_deck_rejects_empty_and_reserved(session, user_with_token):
    user, _ = user_with_token

    with pytest.raises(ValueError, match="пустым"):
        await create_deck(session, user, "   ")

    with pytest.raises(ValueError, match="без колоды"):
        await create_deck(session, user, "Без колоды")

    with pytest.raises(ValueError, match="без колоды"):
        await create_deck(session, user, "  БЕЗ   КОЛОДЫ  ")


@pytest.mark.asyncio
async def test_create_deck_rejects_duplicate_case_insensitive(session, user_with_token):
    user, _ = user_with_token

    await create_deck(session, user, "Матан")

    with pytest.raises(ValueError, match="уже существует"):
        await create_deck(session, user, "матан")

    with pytest.raises(ValueError, match="уже существует"):
        await create_deck(session, user, "  МАТАН  ")


@pytest.mark.asyncio
async def test_list_decks_with_card_counts(session, user_with_token):
    user, _ = user_with_token

    math_deck = await create_deck(session, user, "Матан")
    await create_deck(session, user, "История")

    session.add_all(
        [
            Card(
                user_id=user.id,
                deck_id=math_deck.id,
                question="Q1",
                answer="A1",
            ),
            Card(
                user_id=user.id,
                deck_id=math_deck.id,
                question="Q2",
                answer="A2",
            ),
            Card(
                user_id=user.id,
                deck_id=None,
                question="Q3",
                answer="A3",
            ),
        ]
    )
    await session.commit()

    stats = await list_decks_with_card_counts(session, user)

    counts = {item.deck.name: item.cards_count for item in stats.decks}

    assert counts == {
        "История": 0,
        "Матан": 2,
    }
    assert stats.no_deck_count == 1


@pytest.mark.asyncio
async def test_list_names_of_decks(session, user_with_token):
    user, _ = user_with_token

    math_deck = await create_deck(session, user, "Матан")

    session.add_all(
        [
            Card(
                user_id=user.id,
                deck_id=math_deck.id,
                question="Q1",
                answer="A1",
            ),
            Card(
                user_id=user.id,
                deck_id=None,
                question="Q2",
                answer="A2",
            ),
        ]
    )
    await session.commit()

    text = await list_names_of_decks(session, user)

    assert text == "Матан (1)\nБез колоды (1)"


@pytest.mark.asyncio
async def test_list_names_of_decks_without_no_deck_cards(session, user_with_token):
    user, _ = user_with_token

    await create_deck(session, user, "Пустая")

    text = await list_names_of_decks(session, user)

    assert text == "Пустая (0)"
    assert "Без колоды" not in text


@pytest.mark.asyncio
async def test_list_names_of_decks_empty(session, user_with_token):
    user, _ = user_with_token

    text = await list_names_of_decks(session, user)

    assert text == ""


@pytest.mark.asyncio
async def test_delete_deck_moves_cards_to_no_deck(session, user_with_token):
    user, _ = user_with_token

    await create_deck(session, user, "Матан")

    await sync_cards(
        session,
        user,
        source_file="a.md",
        deck="Матан",
        cards=[SyncCardIn(question="Q?", answer="A")],
    )

    deleted = await delete_deck(session, user, "Матан")
    assert deleted == 1

    card = (await session.execute(select(Card).where(Card.user_id == user.id))).scalar_one()

    assert card.deck_id is None

    assert await deck_service.get_deck_by_name(session, user, "Матан") is None

    stats = await list_decks_with_card_counts(session, user)
    assert stats.decks == []
    assert stats.no_deck_count == 1


@pytest.mark.asyncio
async def test_delete_missing_deck(session, user_with_token):
    user, _ = user_with_token

    with pytest.raises(ValueError, match="не найдена"):
        await delete_deck(session, user, "Нет")


@pytest.mark.asyncio
async def test_resolve_deck_id(session, user_with_token):
    user, _ = user_with_token

    deck = await create_deck(session, user, "D")

    assert await resolve_deck_id(session, user, None) is None
    assert await resolve_deck_id(session, user, "") is None
    assert await resolve_deck_id(session, user, "   ") is None

    assert await resolve_deck_id(session, user, NO_DECK_LABEL) is None
    assert await resolve_deck_id(session, user, "Без колоды") is None
    assert await resolve_deck_id(session, user, "  БЕЗ   КОЛОДЫ  ") is None

    assert await resolve_deck_id(session, user, "D") == deck.id
    assert await resolve_deck_id(session, user, " d ") == deck.id

    with pytest.raises(ValueError, match="не найдена"):
        await resolve_deck_id(session, user, "Missing")


@pytest.mark.asyncio
async def test_get_deck_by_name_empty_name(session, user_with_token):
    user, _ = user_with_token

    assert await deck_service.get_deck_by_name(session, user, "") is None
    assert await deck_service.get_deck_by_name(session, user, "   ") is None
