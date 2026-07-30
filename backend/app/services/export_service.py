from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.card import Card
from app.models.user import User
from app.services import deck_service
from app.services.deck_service import NO_DECK_LABEL

DEFAULT_DELIMITER = "::"


def format_card(question: str, answer: str, delimiter: str = DEFAULT_DELIMITER) -> str:
    """Format one card in Obsidian-compatible markdown."""
    q = question.strip()
    a = answer.strip()
    needs_multiline = "\n" in q or "\n" in a or delimiter in q or delimiter in a
    if needs_multiline:
        return f"{q}\n{delimiter}\n{a}"
    return f"{q} {delimiter} {a}"


def cards_to_markdown(cards: list[Card], delimiter: str = DEFAULT_DELIMITER) -> str:
    blocks = [format_card(c.question, c.answer, delimiter) for c in cards]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in name.strip())
    cleaned = " ".join(cleaned.split()) or "deck"
    return f"{cleaned}.md"


async def list_deck_cards(session: AsyncSession, user: User, deck_id: int | None) -> list[Card]:
    stmt = select(Card).where(Card.user_id == user.id)
    if deck_id is None:
        stmt = stmt.where(Card.deck_id.is_(None))
    else:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.order_by(Card.created_at.asc(), Card.id.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def export_deck_markdown(
    session: AsyncSession, user: User, deck_name: str
) -> tuple[str, str, int]:
    """
    Export deck cards to markdown.

    Returns (filename, markdown, card_count).
    Raises ValueError if deck name is empty or named deck is missing.
    """
    cleaned = " ".join(deck_name.strip().split())
    if not cleaned:
        raise ValueError("Укажите название колоды.\nПример: /export_deck Матан")

    if deck_service.normalize_deck_name(cleaned) == deck_service.normalize_deck_name(NO_DECK_LABEL):
        cards = await list_deck_cards(session, user, None)
        filename = safe_filename(NO_DECK_LABEL)
    else:
        deck = await deck_service.get_deck_by_name(session, user, cleaned)
        if deck is None:
            raise ValueError("Колода не найдена")
        cards = await list_deck_cards(session, user, deck.id)
        filename = safe_filename(deck.name)

    return filename, cards_to_markdown(cards), len(cards)
