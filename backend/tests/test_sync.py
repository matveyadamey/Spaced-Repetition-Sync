import pytest
from app.models.card import Card
from app.models.deck import Deck
from app.models.progress import Progress
from app.schemas.sync import SyncCardIn
from app.services.deck_service import create_deck
from app.services.sync_service import sync_cards
from sqlalchemy import select


@pytest.mark.asyncio
async def test_sync_adds_new_cards(session, user_with_token):
    user, _ = user_with_token
    result = await sync_cards(
        session,
        user,
        source_file="a.md",
        deck=None,
        cards=[
            SyncCardIn(question="Q1?", answer="A1"),
            SyncCardIn(question="Q2?", answer="A2"),
        ],
    )
    assert result.added == 2
    assert result.updated == 0
    assert result.deleted == 0

    cards = (await session.execute(select(Card).where(Card.user_id == user.id))).scalars().all()
    assert len(cards) == 2
    assert all(c.deck_id is None for c in cards)
    assert all(c.source_file == "a.md" for c in cards)
    progress = (
        await session.execute(select(Progress).where(Progress.card_id == cards[0].id))
    ).scalar_one()
    assert progress.interval == 1
    assert progress.ease_factor == 2.5
    assert progress.repetition == 0


@pytest.mark.asyncio
async def test_sync_note_scoped_delete_and_deck_change(session, user_with_token):
    user, _ = user_with_token
    deck = await create_deck(session, user, "Матан")

    await sync_cards(
        session,
        user,
        source_file="a.md",
        deck="Матан",
        cards=[
            SyncCardIn(question="Q1?", answer="A1"),
            SyncCardIn(question="Q2?", answer="A2"),
        ],
    )
    await sync_cards(
        session,
        user,
        source_file="b.md",
        deck=None,
        cards=[SyncCardIn(question="Other?", answer="X")],
    )

    result = await sync_cards(
        session,
        user,
        source_file="a.md",
        deck=None,
        cards=[SyncCardIn(question="Q1?", answer="A1u")],
    )
    assert result.deleted == 1
    assert result.updated == 1

    cards = {
        c.question: c
        for c in (await session.execute(select(Card).where(Card.user_id == user.id)))
        .scalars()
        .all()
    }
    assert set(cards) == {"Q1?", "Other?"}
    assert cards["Q1?"].deck_id is None
    assert cards["Q1?"].answer == "A1u"
    assert cards["Other?"].source_file == "b.md"
    assert (
        await session.execute(select(Deck).where(Deck.id == deck.id))
    ).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_sync_updates_existing_without_resetting_progress(session, user_with_token):
    user, _ = user_with_token
    await sync_cards(
        session,
        user,
        source_file="a.md",
        deck=None,
        cards=[SyncCardIn(question="Q1?", answer="A1")],
    )
    card = (
        await session.execute(select(Card).where(Card.user_id == user.id, Card.question == "Q1?"))
    ).scalar_one()
    progress = (
        await session.execute(select(Progress).where(Progress.card_id == card.id))
    ).scalar_one()
    progress.repetition = 3
    progress.interval = 15
    progress.ease_factor = 2.7
    await session.commit()

    await create_deck(session, user, "История")
    result = await sync_cards(
        session,
        user,
        source_file="b.md",
        deck="История",
        cards=[SyncCardIn(question="Q1?", answer="A1 updated")],
    )
    assert result.added == 0
    assert result.updated == 1

    await session.refresh(card)
    await session.refresh(progress)
    assert card.answer == "A1 updated"
    assert card.source_file == "b.md"
    assert card.deck_id is not None
    assert progress.repetition == 3


@pytest.mark.asyncio
async def test_sync_empty_note_deletes_only_that_note(session, user_with_token):
    user, _ = user_with_token
    await sync_cards(
        session,
        user,
        source_file="a.md",
        deck=None,
        cards=[SyncCardIn(question="Q?", answer="A")],
    )
    await sync_cards(
        session,
        user,
        source_file="b.md",
        deck=None,
        cards=[SyncCardIn(question="Keep?", answer="B")],
    )
    result = await sync_cards(session, user, source_file="a.md", deck=None, cards=[])
    assert result.deleted == 1
    cards = (await session.execute(select(Card).where(Card.user_id == user.id))).scalars().all()
    assert len(cards) == 1
    assert cards[0].question == "Keep?"


@pytest.mark.asyncio
async def test_sync_skips_duplicates_in_request(session, user_with_token):
    user, _ = user_with_token
    result = await sync_cards(
        session,
        user,
        source_file="a.md",
        deck=None,
        cards=[
            SyncCardIn(question="Same?", answer="A1"),
            SyncCardIn(question="Same?", answer="A2"),
        ],
    )
    assert result.added == 1
    assert result.skipped == 1


@pytest.mark.asyncio
async def test_user_isolation(session, user_with_token, another_user_with_token):
    user_a, _ = user_with_token
    user_b, _ = another_user_with_token

    await sync_cards(
        session,
        user_a,
        source_file="a.md",
        deck=None,
        cards=[SyncCardIn(question="Shared?", answer="A")],
    )
    await sync_cards(
        session,
        user_b,
        source_file="a.md",
        deck=None,
        cards=[SyncCardIn(question="Shared?", answer="B")],
    )

    await sync_cards(session, user_a, source_file="a.md", deck=None, cards=[])
    cards_b_after = (
        (await session.execute(select(Card).where(Card.user_id == user_b.id))).scalars().all()
    )
    assert len(cards_b_after) == 1
