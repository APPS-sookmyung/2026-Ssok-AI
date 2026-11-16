# app/main.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.search import router as search_router
from app.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.repositories.content_vectors import ContentVectorRepository
from app.repositories.search import PostgresSearchRepository
from app.routes import router as ai_router
from app.services.embedding import EmbeddingService
from app.services.query_embedding import GeminiEmbeddingProvider
from app.services.retrieval import SearchService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """분석 저장과 검색에 동일한 임베딩 모델을 주입합니다."""
    provider = GeminiEmbeddingProvider()
    app.state.embedding_service = EmbeddingService(
        provider=provider,
        store=ContentVectorRepository(AsyncSessionLocal, settings.EMBEDDING_DIM),
        dimensions=settings.EMBEDDING_DIM,
    )
    app.state.search_service = SearchService(
        provider=provider,
        repository=PostgresSearchRepository(AsyncSessionLocal),
        dimensions=settings.EMBEDDING_DIM,
    )
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="AI Bookmark Core API",
    description="URL 요약·태깅 및 의미 검색 서버",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(ai_router)
app.include_router(search_router)

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Server is running."}
