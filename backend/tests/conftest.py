import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from app.database import Base, get_session
from app.main import app
from app.models.user import User
from app.services.token_service import generate_token, hash_token
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as sess:
        yield sess


@pytest_asyncio.fixture
async def client(engine) -> AsyncGenerator[AsyncClient, None]:
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as sess:
            yield sess

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user_with_token(session: AsyncSession) -> tuple[User, str]:
    token = generate_token()
    user = User(telegram_id=1001, token_hash=hash_token(token))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, token


@pytest_asyncio.fixture
async def another_user_with_token(session: AsyncSession) -> tuple[User, str]:
    token = generate_token()
    user = User(telegram_id=1002, token_hash=hash_token(token))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, token
