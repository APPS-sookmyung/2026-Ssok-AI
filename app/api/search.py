"""의미 검색 전용 라우터."""

import logging

from fastapi import APIRouter, HTTPException, Request

from app.schemas.search import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai", tags=["Search"])


@router.post("/search", response_model=SearchResponse, responses={
    503: {"description": "검색 서비스 미설정 또는 의존 서비스 오류"},
    504: {"description": "검색 제한 시간 초과"},
})
async def search_bookmarks(body: SearchRequest, request: Request) -> SearchResponse:
    if not body.space_ids:
        return SearchResponse(query=body.query, results=[])
    service = getattr(request.app.state, "search_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="검색 서비스가 준비되지 않았습니다.")
    try:
        return await service.search(body)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="검색 시간이 초과되었습니다.") from None
    except Exception as error:
        logger.error("검색 처리 실패: %s", type(error).__name__)
        raise HTTPException(status_code=503, detail="검색을 처리할 수 없습니다.") from None
