# app/routes.py
from fastapi import APIRouter, HTTPException, status
from app.schemas.llm_output import SummaryRequest, SummaryResponse
from app.services.scraper import WebScraper
from app.services.llm_agent import LLMAgent

router = APIRouter(prefix="/api/ai", tags=["AI"])
llm_agent = LLMAgent()

@router.post("/summary", response_model=SummaryResponse)
async def summarize_bookmark(req: SummaryRequest):
    """
    URL을 받아 본문을 크롤링하고 요약/태그 결과를 즉시 반환합니다. (DB 미사용)
    """
    # 1. URL 크롤링
    title, content = WebScraper.extract_content(req.url)

    if not content or len(content.strip()) < 30:
        return SummaryResponse(
            success=False,
            url=req.url,
            error_message="웹페이지 본문을 추출할 수 없거나 내용이 너무 짧습니다."
        )

    try:
        # 2. Gemini 요약 및 태깅 수행
        analysis = await llm_agent.summarize_and_tag(title=title, content=content)

        return SummaryResponse(
            success=True,
            url=req.url,
            title=title,
            summary=analysis.summary,
            category=analysis.category,
            tags=analysis.tags
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gemini API 처리 중 오류 발생: {str(e)}"
        )