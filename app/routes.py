# app/routes.py
import asyncio
import logging

import requests
from fastapi import APIRouter, BackgroundTasks, status

from app.schemas.llm_output import AnalysisStatus, SummaryRequest, SummaryResponse
from app.services.scraper import WebScraper
from app.services.llm_agent import LLMAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["AI"])
llm_agent = LLMAgent()

# 동기 크롤링 작업 전체에 부여하는 시간 제한(초)
SCRAPE_TIMEOUT_SECONDS = 15
# 스프링 콜백 전송에 부여하는 시간 제한(초)
CALLBACK_TIMEOUT_SECONDS = 10


async def _send_callback(callback_url: str, result: SummaryResponse) -> None:
    """분석 결과를 콜백 URL로 전송합니다. 콜백 실패는 예외로 전파하지 않고 로그만 남깁니다."""
    try:
        await asyncio.to_thread(
            requests.post,
            callback_url,
            json=result.model_dump(mode="json"),
            timeout=CALLBACK_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.error("콜백 전송 실패 (bookmark_id=%s): %s", result.bookmark_id, e)


async def _analyze_and_notify(req: SummaryRequest) -> None:
    """
    실제 크롤링·요약을 백그라운드에서 수행하고, 결과를 callback_url로 전송합니다.
    (엔드포인트는 이미 202 응답을 반환한 뒤이므로 여기서는 예외를 올리지 않습니다.)
    """
    url = str(req.url)

    # 1. URL 크롤링
    # WebScraper.extract_content는 동기 네트워크/파싱 작업이므로 이벤트 루프를
    # 막지 않도록 별도 스레드에서 실행하고, 전체 작업에 시간 제한을 둡니다.
    try:
        title, content = await asyncio.wait_for(
            asyncio.to_thread(WebScraper.extract_content, url),
            timeout=SCRAPE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = SummaryResponse(
            bookmark_id=req.bookmark_id,
            status=AnalysisStatus.FAILED,
            error_message="웹페이지 응답이 지연되어 요청을 중단했습니다.",
        )
        await _send_callback(str(req.callback_url), result)
        return

    if not content or len(content.strip()) < 30:
        result = SummaryResponse(
            bookmark_id=req.bookmark_id,
            status=AnalysisStatus.FAILED,
            error_message="웹페이지 본문을 추출할 수 없거나 내용이 너무 짧습니다.",
        )
        await _send_callback(str(req.callback_url), result)
        return

    try:
        # 2. Gemini 요약 및 태깅 수행
        analysis = await llm_agent.summarize_and_tag(title=title, content=content)
        result = SummaryResponse(
            bookmark_id=req.bookmark_id,
            status=AnalysisStatus.SUCCESS,
            analysis=analysis,
        )
    except Exception as e:
        result = SummaryResponse(
            bookmark_id=req.bookmark_id,
            status=AnalysisStatus.FAILED,
            error_message=f"Gemini API 처리 중 오류 발생: {str(e)}",
        )

    await _send_callback(str(req.callback_url), result)


@router.post(
    "/analyze",
    response_model=SummaryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_bookmark(req: SummaryRequest, background_tasks: BackgroundTasks):
    """
    URL을 받아 즉시 접수(202) 응답을 반환하고, 크롤링·요약은 백그라운드에서
    수행한 뒤 결과를 req.callback_url로 비동기 전송합니다.
    """
    background_tasks.add_task(_analyze_and_notify, req)
    return SummaryResponse(bookmark_id=req.bookmark_id, status=AnalysisStatus.PROCESSING)
