# app/main.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.search import router as search_router
from app.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.repositories.search import PostgresSearchRepository
from app.routes import router as ai_router
from app.services.query_embedding import GeminiQueryEmbeddingProvider
from app.services.retrieval import SearchService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """검색 서비스를 앱 수명 동안 한 번만 만들어 공유하고, 종료 시 DB 연결을 정리합니다."""
    app.state.search_service = SearchService(
        provider=GeminiQueryEmbeddingProvider(),
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