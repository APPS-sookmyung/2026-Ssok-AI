"""메타데이터 마이그레이션 적용 후 사용할 벡터 저장소."""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.embedding import BookmarkContent, validate_embedding


_UPSERT = text("""
    INSERT INTO content_vectors
        (bookmark_id, space_id, embedding, title, summary, saved_at)
    VALUES
        (:bookmark_id, :space_id, CAST(:embedding AS vector), :title, :summary, :saved_at)
    ON CONFLICT (bookmark_id) DO UPDATE SET
        space_id = EXCLUDED.space_id,
        embedding = EXCLUDED.embedding,
        title = EXCLUDED.title,
        summary = EXCLUDED.summary,
        saved_at = EXCLUDED.saved_at,
        updated_at = CURRENT_TIMESTAMP
""")


class ContentVectorRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], dimensions: int) -> None:
        if type(dimensions) is not int or dimensions <= 0:
            raise ValueError("벡터 차원은 양의 정수여야 합니다.")
        self.sessions = sessions
        self.dimensions = dimensions

    async def upsert(self, content: BookmarkContent, embedding: Sequence[float]) -> None:
        vector = validate_embedding(embedding, self.dimensions)
        parameters = {
            "bookmark_id": content.bookmark_id,
            "space_id": content.space_id,
            "embedding": "[" + ",".join(str(value) for value in vector) + "]",
            "title": content.title,
            "summary": content.summary,
            "saved_at": content.saved_at,
        }
        async with self.sessions.begin() as session:
            await session.execute(_UPSERT, parameters)
