from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card, Deck, User

NO_DECK_LABEL = "без колоды"


@dataclass(slots=True)
class DeckWithCardCount:
    deck: Deck
    cards_count: int


@dataclass(slots=True)
class DeckListStats:
    decks: list[DeckWithCardCount]
    no_deck_count: int


def normalize_deck_name(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


async def list_decks_with_card_counts(
    session: AsyncSession,
    user: User,
) -> DeckListStats:
    cards_count_subquery = (
        select(func.count(Card.id))
        .where(
            Card.deck_id == Deck.id,
            Card.user_id == user.id,
        )
        .correlate(Deck)
        .scalar_subquery()
    )

    stmt = (
        select(
            Deck,
            cards_count_subquery.label("cards_count"),
        )
        .where(Deck.user_id == user.id)
        .order_by(Deck.name.asc())
    )

    result = await session.execute(stmt)

    decks = [
        DeckWithCardCount(
            deck=deck,
            cards_count=int(cards_count or 0),
        )
        for deck, cards_count in result.all()
    ]

    no_deck_stmt = select(func.count(Card.id)).where(
        Card.user_id == user.id,
        Card.deck_id.is_(None),
    )

    no_deck_result = await session.execute(no_deck_stmt)
    no_deck_count = int(no_deck_result.scalar_one())

    return DeckListStats(
        decks=decks,
        no_deck_count=no_deck_count,
    )


async def list_decks(session: AsyncSession, user: User) -> list[Deck]:
    result = await session.execute(
        select(Deck).where(Deck.user_id == user.id).order_by(Deck.name.asc())
    )
    return list(result.scalars().all())


async def list_names_of_decks(session: AsyncSession, user: User) -> str:
    stats = await list_decks_with_card_counts(session, user)

    lines: list[str] = [f"{item.deck.name} ({item.cards_count})" for item in stats.decks]

    if stats.no_deck_count > 0:
        lines.append(f"Без колоды ({stats.no_deck_count})")

    return "\n".join(lines)


async def get_deck_by_name(session: AsyncSession, user: User, name: str) -> Deck | None:
    normalized = normalize_deck_name(name)
    if not normalized:
        return None
    result = await session.execute(
        select(Deck).where(Deck.user_id == user.id, Deck.name_normalized == normalized)
    )
    return result.scalar_one_or_none()


async def get_deck_by_id(session: AsyncSession, user: User, deck_id: int) -> Deck | None:
    result = await session.execute(select(Deck).where(Deck.user_id == user.id, Deck.id == deck_id))
    return result.scalar_one_or_none()


async def create_deck(session: AsyncSession, user: User, name: str) -> Deck:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise ValueError("Название колоды не может быть пустым")
    if normalize_deck_name(cleaned) == normalize_deck_name(NO_DECK_LABEL):
        raise ValueError(f"Нельзя создать колоду с именем «{NO_DECK_LABEL}»")
    existing = await get_deck_by_name(session, user, cleaned)
    if existing is not None:
        raise ValueError("Колода с таким названием уже существует")
    deck = Deck(
        user_id=user.id,
        name=cleaned,
        name_normalized=normalize_deck_name(cleaned),
    )
    session.add(deck)
    await session.commit()
    await session.refresh(deck)
    return deck


async def delete_deck(session: AsyncSession, user: User, name: str) -> int:
    """
    Delete deck; cards become без колоды (deck_id NULL).
    Returns deleted deck count.
    """
    deck = await get_deck_by_name(session, user, name)
    if deck is None:
        raise ValueError("Колода не найдена")

    await session.execute(
        update(Card)
        .where(
            Card.user_id == user.id,
            Card.deck_id == deck.id,
        )
        .values(deck_id=None)
    )

    await session.execute(
        delete(Deck).where(
            Deck.user_id == user.id,
            Deck.id == deck.id,
        )
    )

    await session.commit()
    return 1


async def resolve_deck_id(session: AsyncSession, user: User, deck_name: str | None) -> int | None:
    """Return deck_id or None for без колоды. Raises ValueError if named deck missing."""
    if deck_name is None:
        return None
    cleaned = " ".join(deck_name.strip().split())
    if not cleaned or normalize_deck_name(cleaned) == normalize_deck_name(NO_DECK_LABEL):
        return None
    deck = await get_deck_by_name(session, user, cleaned)
    if deck is None:
        raise ValueError(f"Колода «{cleaned}» не найдена. Создайте её через /add_deck или плагин.")
    return deck.id
