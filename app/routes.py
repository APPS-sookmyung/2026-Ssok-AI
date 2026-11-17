# app/routes.py
import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import SecretStr

from app.api.service_auth import SpringConnection, get_spring_connection, require_spring
from app.schemas.embedding import BookmarkContent
from app.schemas.llm_output import AnalysisStatus, SummaryRequest, SummaryResponse
from app.services.analysis_completion import save_embedding_and_notify
from app.services.embedding import EmbeddingService
from app.services.scraper import WebScraper
from app.services.llm_agent import LLMAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["AI"], dependencies=[Depends(require_spring)])
llm_agent = LLMAgent()

# 동기 크롤링 작업 전체에 부여하는 시간 제한(초)
SCRAPE_TIMEOUT_SECONDS = 15
# 스프링 콜백 전송에 부여하는 시간 제한(초)
CALLBACK_TIMEOUT_SECONDS = 10
# 콜백 전송 실패 시 재시도 사이의 대기 시간(초). 길이가 재시도 횟수(여기서는 3회)입니다.
CALLBACK_RETRY_DELAYS_SECONDS = (1.0, 3.0, 8.0)


async def _send_callback(callback_url: str, secret: SecretStr, result: SummaryResponse) -> None:
    """설정된 Spring 수신처에만 결과를 전송하고 일시적인 실패를 재시도합니다."""
    payload = result.model_dump(mode="json")
    total_attempts = len(CALLBACK_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(1, total_attempts + 1):
        try:
            response = await asyncio.to_thread(
                requests.post,
                callback_url,
                json=payload,
                headers={"X-AI-Callback-Secret": secret.get_secret_value()},
                timeout=CALLBACK_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            if response.status_code < 500:
                if response.status_code >= 300:
                    # allow_redirects=False라 3xx도 그대로 반환된다. 리다이렉트든
                    # 거부든 재시도하지 않지만, 분석 결과가 전달되지 않았으므로
                    # 운영자가 알 수 있도록 남긴다.
                    logger.error(
                        "콜백이 성공 응답을 받지 못해 재시도하지 않습니다 (bookmark_id=%s): status=%s",
                        result.bookmark_id, response.status_code,
                    )
                return
            logger.warning(
                "콜백 전송 실패, 재시도 예정 (bookmark_id=%s, 시도 %s/%s): status=%s",
                result.bookmark_id, attempt, total_attempts, response.status_code,
            )
        except Exception as e:
            logger.warning(
                "콜백 전송 실패, 재시도 예정 (bookmark_id=%s, 시도 %s/%s): %s",
                result.bookmark_id, attempt, total_attempts, e,
            )

        if attempt <= len(CALLBACK_RETRY_DELAYS_SECONDS):
            await asyncio.sleep(CALLBACK_RETRY_DELAYS_SECONDS[attempt - 1])

    logger.error("콜백 전송이 재시도 횟수를 모두 소진해 실패했습니다 (bookmark_id=%s)", result.bookmark_id)


async def _analyze_and_notify(
    req: SummaryRequest, embedding_service: EmbeddingService | None,
    notify: Callable[[SummaryResponse], Awaitable[None]],
) -> None:
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
        await notify(result)
        return

    if not content or len(content.strip()) < 30:
        result = SummaryResponse(
            bookmark_id=req.bookmark_id,
            status=AnalysisStatus.FAILED,
            title=title,
            error_message="웹페이지 본문을 추출할 수 없거나 내용이 너무 짧습니다.",
        )
        await notify(result)
        return

    try:
        # 2. Gemini 요약 및 태깅 수행
        analysis = await llm_agent.summarize_and_tag(title=title, content=content)
    except Exception as e:
        result = SummaryResponse(
            bookmark_id=req.bookmark_id,
            status=AnalysisStatus.FAILED,
            title=title,
            error_message=f"Gemini API 처리 중 오류 발생: {str(e)}",
        )
        await notify(result)
        return

    result = SummaryResponse(
        bookmark_id=req.bookmark_id, status=AnalysisStatus.SUCCESS, title=title, analysis=analysis,
    )
    if embedding_service is None or req.space_id is None or req.saved_at is None:
        await notify(result)
        return

    await save_embedding_and_notify(
        build_content=lambda: BookmarkContent(
            bookmark_id=req.bookmark_id, space_id=req.space_id, saved_at=req.saved_at,
            title=title or "", summary=analysis.summary, tags=tuple(analysis.tags),
        ),
        embedding_service=embedding_service,
        notify=lambda: notify(result),
    )


@router.post(
    "/analyze",
    response_model=SummaryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_bookmark(req: SummaryRequest, background_tasks: BackgroundTasks, request: Request,
                           spring: Annotated[SpringConnection, Depends(get_spring_connection)]):
    """
    URL을 받아 즉시 접수(202) 응답을 반환하고, 크롤링·요약은 백그라운드에서
    수행한 뒤 결과를 req.callback_url로 비동기 전송합니다.
    """
    target, secret = spring.AI_CALLBACK_URL, spring.AI_CALLBACK_SECRET
    if target is None or secret is None or not secret.get_secret_value().strip():
        raise HTTPException(status_code=503, detail="Spring 콜백이 설정되지 않았습니다.")
    if req.callback_url != target:
        raise HTTPException(status_code=422, detail="등록된 Spring 콜백 주소를 사용해주세요.")
    notify = partial(_send_callback, str(target), secret)
    service = getattr(request.app.state, "embedding_service", None)
    if req.space_id is not None and service is None:
        raise HTTPException(status_code=503, detail="임베딩 저장 서비스가 준비되지 않았습니다.")
    background_tasks.add_task(_analyze_and_notify, req, service, notify)
    return SummaryResponse(bookmark_id=req.bookmark_id, status=AnalysisStatus.PROCESSING)
