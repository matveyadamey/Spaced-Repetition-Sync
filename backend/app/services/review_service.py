import secrets
from datetime import date, datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.card import Card
from app.models.progress import Progress
from app.models.review_session import ReviewSession
from app.models.user import User
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
        .values(is_active=False, finished_at=datetime.now(timezone.utc))
    )


async def start_review_session(session: AsyncSession, user: User) -> ReviewSession | None:
    today = date.today()

    due_result = await session.execute(
        select(Card.id)
        .join(Progress, Progress.card_id == Card.id)
        .where(Card.user_id == user.id, Progress.next_review <= today)
        .order_by(Progress.next_review.asc(), Card.id.asc())
    )
    card_ids = list(due_result.scalars().all())

    if not card_ids:
        new_result = await session.execute(
            select(Card.id)
            .join(Progress, Progress.card_id == Card.id)
            .where(Card.user_id == user.id, Progress.repetition == 0)
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

    result = await session.execute(
        select(Progress).where(Progress.card_id == card_id)
    )
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
    progress.updated_at = datetime.now(timezone.utc)

    review_session.current_index += 1
    review_session.reviewed_count += 1

    finished = review_session.current_index >= len(review_session.card_ids)
    if finished:
        review_session.is_active = False
        review_session.finished_at = datetime.now(timezone.utc)

    await session.commit()
    return finished, review_session.reviewed_count


async def get_stats(session: AsyncSession, user: User) -> dict[str, int | float]:
    today = date.today()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

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

    # Cards rated today: progress.updated_at is set on every rating.
    # Exclude pristine cards created/reset today (still at initial SM-2 values with next_review=today).
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
    now = datetime.now(timezone.utc)
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
