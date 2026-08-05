import logging
from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.card import Card
from app.models.progress import Progress
from app.models.user import User
from app.schemas.sync import SyncCardIn, SyncResponse
from app.services.deck_service import resolve_deck_id

logger = logging.getLogger(__name__)


async def sync_cards(
    session: AsyncSession,
    user: User,
    *,
    source_file: str,
    deck: str | None,
    cards: list[SyncCardIn],
    bot=None,
) -> SyncResponse:
    """Mirror-sync cards for a single note (source_file), assign all to one deck.

    Args:
        session: Асинхронная сессия БД
        user: Пользователь
        source_file: Путь к файлу заметки в Obsidian
        deck: Название колоды (None для "без колоды")
        cards: Список карточек для синхронизации
        bot: Опциональный инстанс бота для отправки поздравления
             после первого успешного sync
    """

    is_first_sync = user.last_sync_at is None

    added = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    source_file = source_file.strip()
    if not source_file:
        raise ValueError("source_file is required")

    deck_id = await resolve_deck_id(session, user, deck)

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
                source_file=source_file,
            )
        )

    result = await session.execute(select(Card).where(Card.user_id == user.id))
    existing_by_question = {card.question: card for card in result.scalars().all()}

    note_result = await session.execute(
        select(Card).where(Card.user_id == user.id, Card.source_file == source_file)
    )
    note_cards = {card.question: card for card in note_result.scalars().all()}

    today = date.today()
    now = datetime.now(UTC)
    incoming_questions: set[str] = set()

    for card_in in unique_cards:
        incoming_questions.add(card_in.question)
        existing = existing_by_question.get(card_in.question)
        if existing is None:
            new_card = Card(
                user_id=user.id,
                question=card_in.question,
                answer=card_in.answer,
                source_file=source_file,
                deck_id=deck_id,
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
            existing.source_file = source_file
            existing.deck_id = deck_id
            existing.updated_at = now
            updated += 1

    deleted = 0
    for question, card in note_cards.items():
        if question not in incoming_questions:
            await session.execute(delete(Progress).where(Progress.card_id == card.id))
            await session.delete(card)
            deleted += 1

    user.last_sync_at = now
    await session.commit()

    if is_first_sync and added > 0 and bot is not None:
        try:
            from app.services.notification_service import notify_first_sync

            await notify_first_sync(bot, user.telegram_id, added, deck)
        except Exception as e:
            logger.warning(
                "Failed to send first sync notification to telegram_id=%s: %s", user.telegram_id, e
            )

    logger.info(
        "Sync completed: telegram_id=%s added=%s updated=%s skipped=%s deleted=%s is_first=%s",
        user.telegram_id,
        added,
        updated,
        skipped,
        deleted,
        is_first_sync,
    )

    return SyncResponse(
        status="ok",
        added=added,
        updated=updated,
        skipped=skipped,
        deleted=deleted,
        errors=errors,
    )
