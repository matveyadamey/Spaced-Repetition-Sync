from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deck import Deck
from app.models.user import User

NO_DECK_LABEL = "без колоды"


def normalize_deck_name(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


async def list_decks(session: AsyncSession, user: User) -> list[Deck]:
    result = await session.execute(
        select(Deck).where(Deck.user_id == user.id).order_by(Deck.name.asc())
    )
    return list(result.scalars().all())


async def list_names_of_decks(session: AsyncSession, user: User) -> str:
    decks = await list_decks(session, user)
    names_of_decks: list[str] = []
    deck: Deck
    for deck in decks:
        decks.append(deck.name)
    return "\n".join(names_of_decks)


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
    """Delete deck; cards become без колоды (deck_id NULL). Returns deleted deck count."""
    deck = await get_deck_by_name(session, user, name)
    if deck is None:
        raise ValueError("Колода не найдена")
    await session.delete(deck)
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
