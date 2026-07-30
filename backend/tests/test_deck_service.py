import pytest
from app.models.card import Card
from app.schemas.sync import SyncCardIn
from app.services import deck_service
from app.services.deck_service import NO_DECK_LABEL, create_deck, delete_deck, resolve_deck_id
from app.services.sync_service import sync_cards
from sqlalchemy import select


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
    with pytest.raises(ValueError, match=NO_DECK_LABEL):
        await create_deck(session, user, "Без колоды")


@pytest.mark.asyncio
async def test_create_deck_rejects_duplicate_case_insensitive(session, user_with_token):
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    with pytest.raises(ValueError, match="уже существует"):
        await create_deck(session, user, "матан")


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
    await delete_deck(session, user, "Матан")
    card = (await session.execute(select(Card).where(Card.user_id == user.id))).scalar_one()
    assert card.deck_id is None
    assert await deck_service.get_deck_by_name(session, user, "Матан") is None


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
    assert await resolve_deck_id(session, user, "без колоды") is None
    assert await resolve_deck_id(session, user, "D") == deck.id
    with pytest.raises(ValueError, match="не найдена"):
        await resolve_deck_id(session, user, "Missing")
