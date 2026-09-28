# app/db/session.py
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # 유휴 커넥션이 끊겼을 때 자동 재연결
    pool_size=5,
    max_overflow=5,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성으로 주입할 DB 세션."""
    async with AsyncSessionLocal() as session:
        yield session
