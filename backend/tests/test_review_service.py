from datetime import date, timedelta

import pytest
from app.models.card import Card
from app.models.progress import Progress
from app.schemas.sync import SyncCardIn
from app.services.deck_service import NO_DECK_LABEL, create_deck, get_deck_by_name
from app.services.review_service import (
    find_card_by_question,
    get_active_session,
    get_current_card,
    get_stats,
    list_reviewable_decks,
    rate_current_card,
    reset_progress,
    set_card_deck,
    start_review_session,
)
from app.services.sync_service import sync_cards
from sqlalchemy import select


async def _sync_cards(
    session, user, *, deck: str | None, questions: list[str], source_file: str = "note.md"
):
    await sync_cards(
        session,
        user,
        source_file=source_file,
        deck=deck,
        cards=[SyncCardIn(question=q, answer=f"A:{q}") for q in questions],
    )


@pytest.mark.asyncio
async def test_start_review_uses_new_cards(session, user_with_token):
    user, _ = user_with_token
    await create_deck(session, user, "D")
    await _sync_cards(session, user, deck="D", questions=["One?", "Two?"])
    deck = await get_deck_by_name(session, user, "D")
    review = await start_review_session(session, user, deck_id=deck.id)
    assert review is not None
    assert review.is_active is True
    assert len(review.card_ids) == 2
    card = await get_current_card(session, review)
    assert card is not None
    assert card.question in {"One?", "Two?"}


@pytest.mark.asyncio
async def test_start_review_empty_deck_returns_none(session, user_with_token):
    user, _ = user_with_token
    await create_deck(session, user, "Empty")
    deck = await get_deck_by_name(session, user, "Empty")
    assert await start_review_session(session, user, deck_id=deck.id) is None


@pytest.mark.asyncio
async def test_rate_card_advances_and_finishes(session, user_with_token):
    user, _ = user_with_token
    await _sync_cards(session, user, deck=None, questions=["Only?"])
    review = await start_review_session(session, user, deck_id=None)
    assert review is not None
    card = await get_current_card(session, review)
    finished, count = await rate_current_card(session, review, card.id, q=5)
    assert finished is True
    assert count == 1
    assert review.is_active is False
    progress = (
        await session.execute(select(Progress).where(Progress.card_id == card.id))
    ).scalar_one()
    assert progress.repetition == 1
    assert progress.interval == 1


@pytest.mark.asyncio
async def test_rate_wrong_card_id_ignored(session, user_with_token):
    user, _ = user_with_token
    await _sync_cards(session, user, deck=None, questions=["A?", "B?"])
    review = await start_review_session(session, user, deck_id=None)
    wrong_id = review.card_ids[1]
    finished, count = await rate_current_card(session, review, wrong_id, q=5)
    assert finished is False
    assert count == 0
    assert review.current_index == 0
    assert review.is_active is True


@pytest.mark.asyncio
async def test_inactive_session_not_returned(session, user_with_token):
    user, _ = user_with_token
    await _sync_cards(session, user, deck=None, questions=["A?"])
    review = await start_review_session(session, user, deck_id=None)
    card = await get_current_card(session, review)
    await rate_current_card(session, review, card.id, q=3)
    assert await get_active_session(session, user.id, review.session_id) is None


@pytest.mark.asyncio
async def test_list_reviewable_decks(session, user_with_token):
    user, _ = user_with_token
    await create_deck(session, user, "Матан")
    await _sync_cards(session, user, deck="Матан", questions=["Math?"], source_file="math.md")
    await _sync_cards(session, user, deck=None, questions=["Loose?"], source_file="loose.md")
    await create_deck(session, user, "Пустая")
    items = await list_reviewable_decks(session, user)
    labels = [name for _, name in items]
    assert "Матан" in labels
    assert NO_DECK_LABEL in labels
    assert "Пустая" not in labels


@pytest.mark.asyncio
async def test_get_stats_and_reset(session, user_with_token):
    user, _ = user_with_token
    await _sync_cards(session, user, deck=None, questions=["Q?"])
    review = await start_review_session(session, user, deck_id=None)
    card = await get_current_card(session, review)
    await rate_current_card(session, review, card.id, q=5)

    stats = await get_stats(session, user)
    assert stats["total"] == 1
    assert stats["reviewed_today"] >= 1

    reset_count = await reset_progress(session, user)
    assert reset_count == 1
    progress = (
        await session.execute(select(Progress).where(Progress.card_id == card.id))
    ).scalar_one()
    assert progress.repetition == 0
    assert progress.ease_factor == 2.5
    assert progress.interval == 1
    assert progress.next_review == date.today()


@pytest.mark.asyncio
async def test_find_and_set_card_deck(session, user_with_token, another_user_with_token):
    user, _ = user_with_token
    other, _ = another_user_with_token
    deck = await create_deck(session, user, "D")
    await _sync_cards(session, user, deck=None, questions=["Move me?"])
    card = await find_card_by_question(session, user, "Move me?")
    assert card is not None

    updated = await set_card_deck(session, user, card.id, deck.id)
    assert updated is not None
    assert updated.deck_id == deck.id

    assert await find_card_by_question(session, other, "Move me?") is None
    assert await set_card_deck(session, other, card.id, None) is None

    with pytest.raises(ValueError, match="не найдена"):
        await set_card_deck(session, user, card.id, 999999)


@pytest.mark.asyncio
async def test_due_cards_preferred_over_new(session, user_with_token):
    user, _ = user_with_token
    await _sync_cards(session, user, deck=None, questions=["New?", "Due?"])
    cards = {
        c.question: c
        for c in (await session.execute(select(Card).where(Card.user_id == user.id))).scalars()
    }
    due = (
        await session.execute(select(Progress).where(Progress.card_id == cards["Due?"].id))
    ).scalar_one()
    due.repetition = 2
    due.interval = 3
    due.next_review = date.today() - timedelta(days=1)
    await session.commit()

    review = await start_review_session(session, user, deck_id=None)
    assert review is not None
    assert review.card_ids == [cards["Due?"].id]
