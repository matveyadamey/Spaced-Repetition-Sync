from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.card import Card
from app.models.progress import Progress
from app.models.user import User
from app.schemas.sync import SyncCardIn, SyncResponse


async def sync_cards(
    session: AsyncSession,
    user: User,
    cards: list[SyncCardIn],
) -> SyncResponse:
    added = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    seen_questions: set[str] = set()
    unique_cards: list[SyncCardIn] = []
    for card in cards:
        question = card.question.strip()
        answer = card.answer.strip()
        if not question or not answer:
            skipped += 1
            errors.append("Skipped card with empty question or answer")
            continue
        if question in seen_questions:
            skipped += 1
            continue
        seen_questions.add(question)
        unique_cards.append(
            SyncCardIn(
                question=question,
                answer=answer,
                source_file=card.source_file,
            )
        )

    result = await session.execute(select(Card).where(Card.user_id == user.id))
    existing_by_question = {card.question: card for card in result.scalars().all()}

    today = date.today()
    now = datetime.now(timezone.utc)
    incoming_questions: set[str] = set()

    for card_in in unique_cards:
        incoming_questions.add(card_in.question)
        existing = existing_by_question.get(card_in.question)
        if existing is None:
            new_card = Card(
                user_id=user.id,
                question=card_in.question,
                answer=card_in.answer,
                source_file=card_in.source_file,
            )
            session.add(new_card)
            await session.flush()
            session.add(
                Progress(
                    card_id=new_card.id,
                    interval=1,
                    ease_factor=2.5,
                    repetition=0,
                    next_review=today,
                )
            )
            added += 1
        else:
            existing.answer = card_in.answer
            existing.source_file = card_in.source_file
            existing.updated_at = now
            updated += 1

    deleted = 0
    for question, card in existing_by_question.items():
        if question not in incoming_questions:
            await session.execute(delete(Progress).where(Progress.card_id == card.id))
            await session.delete(card)
            deleted += 1

    user.last_sync_at = now
    await session.commit()

    return SyncResponse(
        status="ok",
        added=added,
        updated=updated,
        skipped=skipped,
        deleted=deleted,
        errors=errors,
    )
