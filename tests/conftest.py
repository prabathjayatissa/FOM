"""Pytest configuration and async fixtures."""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an in-memory SQLite session for tests."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    TestSessionLocal = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    await test_engine.dispose()
