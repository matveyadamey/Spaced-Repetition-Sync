import pytest
from sqlalchemy import select

from app.models.card import Card
from app.models.progress import Progress
from app.models.user import User
from app.schemas.sync import SyncCardIn
from app.services.sync_service import sync_cards


@pytest.mark.asyncio
async def test_sync_adds_new_cards(session, user_with_token):
    user, _ = user_with_token
    result = await sync_cards(
        session,
        user,
        [
            SyncCardIn(question="Q1?", answer="A1", source_file="a.md"),
            SyncCardIn(question="Q2?", answer="A2", source_file="a.md"),
        ],
    )
    assert result.added == 2
    assert result.updated == 0
    assert result.deleted == 0

    cards = (await session.execute(select(Card).where(Card.user_id == user.id))).scalars().all()
    assert len(cards) == 2
    progress = (
        await session.execute(select(Progress).where(Progress.card_id == cards[0].id))
    ).scalar_one()
    assert progress.interval == 1
    assert progress.ease_factor == 2.5
    assert progress.repetition == 0


@pytest.mark.asyncio
async def test_sync_updates_existing_without_resetting_progress(session, user_with_token):
    user, _ = user_with_token
    await sync_cards(
        session,
        user,
        [SyncCardIn(question="Q1?", answer="A1", source_file="a.md")],
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

    result = await sync_cards(
        session,
        user,
        [SyncCardIn(question="Q1?", answer="A1 updated", source_file="b.md")],
    )
    assert result.added == 0
    assert result.updated == 1

    await session.refresh(card)
    await session.refresh(progress)
    assert card.answer == "A1 updated"
    assert card.source_file == "b.md"
    assert progress.repetition == 3
    assert progress.interval == 15
    assert progress.ease_factor == 2.7


@pytest.mark.asyncio
async def test_sync_deletes_missing_cards(session, user_with_token):
    user, _ = user_with_token
    await sync_cards(
        session,
        user,
        [
            SyncCardIn(question="Keep?", answer="yes"),
            SyncCardIn(question="Drop?", answer="no"),
        ],
    )
    result = await sync_cards(
        session,
        user,
        [SyncCardIn(question="Keep?", answer="yes")],
    )
    assert result.deleted == 1
    assert result.updated == 1
    cards = (await session.execute(select(Card).where(Card.user_id == user.id))).scalars().all()
    assert len(cards) == 1
    assert cards[0].question == "Keep?"


@pytest.mark.asyncio
async def test_sync_empty_list_deletes_all(session, user_with_token):
    user, _ = user_with_token
    await sync_cards(
        session,
        user,
        [SyncCardIn(question="Q?", answer="A")],
    )
    result = await sync_cards(session, user, [])
    assert result.deleted == 1
    assert result.added == 0
    cards = (await session.execute(select(Card).where(Card.user_id == user.id))).scalars().all()
    assert cards == []


@pytest.mark.asyncio
async def test_sync_skips_duplicates_in_request(session, user_with_token):
    user, _ = user_with_token
    result = await sync_cards(
        session,
        user,
        [
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

    await sync_cards(session, user_a, [SyncCardIn(question="Shared?", answer="A")])
    await sync_cards(session, user_b, [SyncCardIn(question="Shared?", answer="B")])

    cards_a = (
        await session.execute(select(Card).where(Card.user_id == user_a.id))
    ).scalars().all()
    cards_b = (
        await session.execute(select(Card).where(Card.user_id == user_b.id))
    ).scalars().all()
    assert len(cards_a) == 1
    assert len(cards_b) == 1
    assert cards_a[0].answer == "A"
    assert cards_b[0].answer == "B"

    await sync_cards(session, user_a, [])
    cards_b_after = (
        await session.execute(select(Card).where(Card.user_id == user_b.id))
    ).scalars().all()
    assert len(cards_b_after) == 1
