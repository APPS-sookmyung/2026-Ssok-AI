"""검색 라우터를 독립적으로 확인하기 위한 앱 팩토리."""

from fastapi import FastAPI

from app.api.search import router
from app.services.retrieval import SearchService


def create_app(service: SearchService | None = None) -> FastAPI:
    app = FastAPI(title="SSok 검색 API 개발용")
    app.state.search_service = service
    app.include_router(router)
    return app
