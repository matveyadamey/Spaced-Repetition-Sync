import secrets
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.card import Card
from app.models.deck import Deck
from app.models.progress import Progress
from app.models.review_session import ReviewSession
from app.models.user import User
from app.services.deck_service import NO_DECK_LABEL
from app.services.sm2 import apply_sm2


async def get_or_create_user(session: AsyncSession, telegram_id: int) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(telegram_id=telegram_id)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def deactivate_active_sessions(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(ReviewSession)
        .where(ReviewSession.user_id == user_id, ReviewSession.is_active.is_(True))
        .values(is_active=False, finished_at=datetime.now(UTC))
    )


def _deck_filter(deck_id: int | None):
    if deck_id is None:
        return Card.deck_id.is_(None)
    return Card.deck_id == deck_id


async def list_reviewable_decks(session: AsyncSession, user: User) -> list[tuple[int | None, str]]:
    """Return decks for /review picker: все колоды пользователя + «без колоды», если там есть карточки."""
    today = date.today()

    # Named decks that have due or new cards.
    named_ready = await session.execute(
        select(Card.deck_id, Deck.name)
        .join(Deck, Deck.id == Card.deck_id)
        .join(Progress, Progress.card_id == Card.id)
        .where(
            Card.user_id == user.id,
            Card.deck_id.is_not(None),
            or_(Progress.next_review <= today, Progress.repetition == 0),
        )
        .distinct()
    )
    items: list[tuple[int | None, str]] = []
    seen: set[int | None] = set()
    for deck_id, deck_name in named_ready.all():
        if deck_id in seen:
            continue
        seen.add(deck_id)
        items.append((deck_id, deck_name))

    # Also include every named deck that has at least one card (even if not due yet),
    # so a deck with cards always appears after sync.
    named_with_cards = await session.execute(
        select(Card.deck_id, Deck.name)
        .join(Deck, Deck.id == Card.deck_id)
        .where(Card.user_id == user.id, Card.deck_id.is_not(None))
        .distinct()
    )
    for deck_id, deck_name in named_with_cards.all():
        if deck_id in seen:
            continue
        seen.add(deck_id)
        items.append((deck_id, deck_name))

    # «без колоды» — если есть due/new карточки без колоды
    no_deck_ready = await session.scalar(
        select(func.count())
        .select_from(Card)
        .join(Progress, Progress.card_id == Card.id)
        .where(
            Card.user_id == user.id,
            Card.deck_id.is_(None),
            or_(Progress.next_review <= today, Progress.repetition == 0),
        )
    )
    if no_deck_ready:
        items.append((None, NO_DECK_LABEL))

    items.sort(key=lambda x: (x[0] is not None, (x[1] or "").casefold()))
    return items


async def start_review_session(
    session: AsyncSession,
    user: User,
    *,
    deck_id: int | None = None,
) -> ReviewSession | None:
    today = date.today()
    deck_clause = _deck_filter(deck_id)

    due_result = await session.execute(
        select(Card.id)
        .join(Progress, Progress.card_id == Card.id)
        .where(
            Card.user_id == user.id,
            Progress.next_review <= today,
            Progress.repetition > 0,
            deck_clause,
        )
        .order_by(Progress.next_review.asc(), Card.id.asc())
    )
    card_ids = list(due_result.scalars().all())

    if not card_ids:
        new_result = await session.execute(
            select(Card.id)
            .join(Progress, Progress.card_id == Card.id)
            .where(Card.user_id == user.id, Progress.repetition == 0, deck_clause)
            .order_by(Card.id.asc())
            .limit(settings.max_new_cards_per_session)
        )
        card_ids = list(new_result.scalars().all())

    if not card_ids:
        return None

    await deactivate_active_sessions(session, user.id)

    review_session = ReviewSession(
        user_id=user.id,
        session_id=secrets.token_urlsafe(16),
        card_ids=card_ids,
        current_index=0,
        reviewed_count=0,
        is_active=True,
    )
    session.add(review_session)
    await session.commit()
    await session.refresh(review_session)
    return review_session


async def get_active_session(
    session: AsyncSession, user_id: int, session_id: str
) -> ReviewSession | None:
    result = await session.execute(
        select(ReviewSession).where(
            ReviewSession.user_id == user_id,
            ReviewSession.session_id == session_id,
            ReviewSession.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_current_card(
    session: AsyncSession, review_session: ReviewSession
) -> Card | None:
    if review_session.current_index >= len(review_session.card_ids):
        return None
    card_id = review_session.card_ids[review_session.current_index]
    result = await session.execute(
        select(Card).options(selectinload(Card.progress)).where(Card.id == card_id)
    )
    return result.scalar_one_or_none()


async def rate_current_card(
    session: AsyncSession,
    review_session: ReviewSession,
    card_id: int,
    q: int,
) -> tuple[bool, int]:
    """Rate current card. Returns (finished, reviewed_count)."""
    if review_session.current_index >= len(review_session.card_ids):
        return True, review_session.reviewed_count

    expected_card_id = review_session.card_ids[review_session.current_index]
    if expected_card_id != card_id:
        return False, review_session.reviewed_count

    result = await session.execute(select(Progress).where(Progress.card_id == card_id))
    progress = result.scalar_one_or_none()
    if progress is None:
        return False, review_session.reviewed_count

    sm2 = apply_sm2(
        q=q,
        interval=progress.interval,
        ease_factor=progress.ease_factor,
        repetition=progress.repetition,
    )
    progress.interval = sm2.interval
    progress.ease_factor = sm2.ease_factor
    progress.repetition = sm2.repetition
    progress.next_review = sm2.next_review
    progress.updated_at = datetime.now(UTC)

    review_session.current_index += 1
    review_session.reviewed_count += 1

    finished = review_session.current_index >= len(review_session.card_ids)
    if finished:
        review_session.is_active = False
        review_session.finished_at = datetime.now(UTC)

    await session.commit()
    return finished, review_session.reviewed_count


async def get_stats(session: AsyncSession, user: User) -> dict[str, int | float]:
    today = date.today()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)

    total = await session.scalar(
        select(func.count()).select_from(Card).where(Card.user_id == user.id)
    )
    total = total or 0

    due = await session.scalar(
        select(func.count())
        .select_from(Card)
        .join(Progress, Progress.card_id == Card.id)
        .where(Card.user_id == user.id, Progress.next_review <= today)
    )
    due = due or 0

    reviewed_today = await session.scalar(
        select(func.count())
        .select_from(Card)
        .join(Progress, Progress.card_id == Card.id)
        .where(
            Card.user_id == user.id,
            Progress.updated_at >= start_of_day,
            ~(
                (Progress.repetition == 0)
                & (Progress.ease_factor == 2.5)
                & (Progress.interval == 1)
                & (Progress.next_review == today)
            ),
        )
    )
    reviewed_today = reviewed_today or 0

    learned = await session.scalar(
        select(func.count())
        .select_from(Card)
        .join(Progress, Progress.card_id == Card.id)
        .where(Card.user_id == user.id, Progress.repetition >= 2)
    )
    learned = learned or 0
    learned_pct = 0 if total == 0 else round(learned / total * 100)

    return {
        "total": total,
        "due": due,
        "reviewed_today": reviewed_today,
        "learned_pct": learned_pct,
    }


async def reset_progress(session: AsyncSession, user: User) -> int:
    today = date.today()
    now = datetime.now(UTC)
    result = await session.execute(
        select(Progress)
        .join(Card, Card.id == Progress.card_id)
        .where(Card.user_id == user.id)
    )
    rows = list(result.scalars().all())
    for progress in rows:
        progress.interval = 1
        progress.ease_factor = 2.5
        progress.repetition = 0
        progress.next_review = today
        progress.updated_at = now
    await deactivate_active_sessions(session, user.id)
    await session.commit()
    return len(rows)


async def find_card_by_question(
    session: AsyncSession, user: User, question: str
) -> Card | None:
    cleaned = question.strip()
    result = await session.execute(
        select(Card).where(Card.user_id == user.id, Card.question == cleaned)
    )
    return result.scalar_one_or_none()


async def set_card_deck(
    session: AsyncSession, user: User, card_id: int, deck_id: int | None
) -> Card | None:
    result = await session.execute(
        select(Card).where(Card.user_id == user.id, Card.id == card_id)
    )
    card = result.scalar_one_or_none()
    if card is None:
        return None
    if deck_id is not None:
        deck_result = await session.execute(
            select(Deck).where(Deck.user_id == user.id, Deck.id == deck_id)
        )
        if deck_result.scalar_one_or_none() is None:
            raise ValueError("Колода не найдена")
    card.deck_id = deck_id
    card.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(card)
    return card
