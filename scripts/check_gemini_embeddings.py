"""운영 어댑터로 Gemini 문서·검색어 임베딩을 한 번씩 확인합니다."""

import asyncio
import json
import math

from app.config import settings
from app.schemas.embedding import validate_embedding
from app.services.query_embedding import GeminiEmbeddingProvider


async def main() -> None:
    provider = GeminiEmbeddingProvider()
    async with asyncio.timeout(60):
        document = validate_embedding(
            await provider.embed_document("제목: 북마크 검색\n요약: 저장한 링크를 스페이스 안에서 찾는다."),
            settings.EMBEDDING_DIM,
        )
        query = validate_embedding(await provider.embed_query("저장한 링크 찾기"), settings.EMBEDDING_DIM)
    cosine = sum(a * b for a, b in zip(document, query)) / (math.hypot(*document) * math.hypot(*query))
    print(json.dumps({"model": settings.EMBEDDING_MODEL, "document_dimensions": len(document),
                      "query_dimensions": len(query), "cosine": cosine}))


if __name__ == "__main__":
    asyncio.run(main())
