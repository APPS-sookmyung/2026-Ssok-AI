# app/routes.py
import asyncio
import logging
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, BackgroundTasks, status

from app.config import settings
from app.schemas.llm_output import AnalysisStatus, SummaryRequest, SummaryResponse
from app.services.scraper import UnsafeUrlError, WebScraper, _assert_safe_url
from app.services.llm_agent import LLMAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["AI"])
llm_agent = LLMAgent()

# 동기 크롤링 작업 전체에 부여하는 시간 제한(초)
SCRAPE_TIMEOUT_SECONDS = 15
# 스프링 콜백 전송에 부여하는 시간 제한(초)
CALLBACK_TIMEOUT_SECONDS = 10
# 콜백 전송 실패 시 재시도 사이의 대기 시간(초). 길이가 재시도 횟수(여기서는 3회)입니다.
CALLBACK_RETRY_DELAYS_SECONDS = (1.0, 3.0, 8.0)


def _is_allowed_callback_target(callback_url: str) -> bool:
    """settings.CALLBACK_ALLOWED_HOSTS에 등록된 호스트(":포트" 포함 가능)인지 확인합니다.

    AI 서버와 스프링 서버를 같은 내부망(예: 같은 EC2)에 배포하면 콜백 주소가
    사설 IP나 localhost로 해석되어 공인 주소만 허용하는 SSRF 검증에 막힌다.
    배포 환경의 실제 콜백 호스트를 설정값으로 등록해두면 그 호스트에 대해서만
    검증을 건너뛴다. 등록된 호스트가 없으면 항상 False를 반환해 기존 정책
    (공인 주소만 허용)을 그대로 쓴다.
    """
    allowed = {h.strip().lower() for h in settings.CALLBACK_ALLOWED_HOSTS.split(",") if h.strip()}
    if not allowed:
        return False
    parsed = urlparse(callback_url)
    return bool(parsed.hostname) and (parsed.hostname.lower() in allowed or parsed.netloc.lower() in allowed)


async def _send_callback(callback_url: str, result: SummaryResponse) -> None:
    """분석 결과를 콜백 URL로 전송합니다. 콜백 실패는 예외로 전파하지 않고 로그만 남깁니다.

    callback_url은 요청자가 직접 지정하므로, settings.CALLBACK_ALLOWED_HOSTS에
    등록되지 않은 호스트라면 scraper의 SSRF 검증을 재사용해 내부망·예약
    주소로의 전송을 막습니다. DNS 조회는 이벤트 루프를 막으므로 별도
    스레드에서 실행하고, 리다이렉트는 재검증 없이 따라가지 않도록 끕니다.

    네트워크 오류나 백엔드 서버 오류(5xx 응답)는 지수 백오프로 재시도합니다.
    4xx 응답은 재시도해도 결과가 같을 가능성이 높아 재시도하지 않습니다.
    """
    if not _is_allowed_callback_target(callback_url):
        try:
            await asyncio.to_thread(_assert_safe_url, callback_url)
        except UnsafeUrlError as e:
            logger.error("콜백 URL이 안전하지 않아 전송을 건너뜁니다 (bookmark_id=%s): %s", result.bookmark_id, e)
            return

    payload = result.model_dump(mode="json")
    total_attempts = len(CALLBACK_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(1, total_attempts + 1):
        try:
            response = await asyncio.to_thread(
                requests.post,
                callback_url,
                json=payload,
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
            title=title,
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
            title=title,
            analysis=analysis,
        )
    except Exception as e:
        result = SummaryResponse(
            bookmark_id=req.bookmark_id,
            status=AnalysisStatus.FAILED,
            title=title,
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
