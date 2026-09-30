"""모델 호출과 저장소를 주입받는 임베딩 저장 서비스."""

import asyncio
from collections.abc import Sequence
from typing import Protocol

from app.schemas.embedding import BookmarkContent, validate_embedding


class EmbeddingProvider(Protocol):
    async def embed_document(self, text: str) -> Sequence[float]: ...


class VectorStore(Protocol):
    async def upsert(self, content: BookmarkContent, embedding: Sequence[float]) -> None: ...


def build_embedding_input(content: BookmarkContent) -> str:
    fields = (
        ("제목", content.title.strip()),
        ("요약", content.summary.strip()),
        ("태그", ", ".join(tag.strip() for tag in content.tags if tag.strip())),
    )
    text = "\n".join(f"{label}: {value}" for label, value in fields if value)
    if not text:
        raise ValueError("임베딩할 제목, 요약 또는 태그가 필요합니다.")
    return text


class EmbeddingService:
    def __init__(self, provider: EmbeddingProvider, store: VectorStore,
                 dimensions: int, timeout_seconds: float = 30.0) -> None:
        if type(dimensions) is not int or dimensions <= 0:
            raise ValueError("벡터 차원은 양의 정수여야 합니다.")
        if not 0 < timeout_seconds < float("inf"):
            raise ValueError("모델 호출 제한 시간은 유한한 양수여야 합니다.")
        self.provider = provider
        self.store = store
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    async def save(self, content: BookmarkContent) -> None:
        """생성이 끝난 후 저장합니다. 실패와 취소는 호출자에게 전달합니다."""
        text = build_embedding_input(content)
        async with asyncio.timeout(self.timeout_seconds):
            embedding = await self.provider.embed_document(text)
        vector = validate_embedding(embedding, self.dimensions)
        await self.store.upsert(content, vector)
