"""분석 성공 후 선택적인 임베딩 저장과 콜백 호출을 연결합니다."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
import math

from app.schemas.embedding import BookmarkContent
from app.services.embedding import EmbeddingService

logger = logging.getLogger(__name__)


async def save_embedding_and_notify(
    *,
    build_content: Callable[[], BookmarkContent],
    embedding_service: EmbeddingService,
    notify: Callable[[], Awaitable[None]],
    timeout_seconds: float = 40.0,
) -> bool:
    """임베딩 실패와 관계없이 콜백을 한 번 호출하고 저장 성공 여부를 반환합니다.

    분석 성공 결과를 준비한 호출자가 notify로 전달합니다. 메타데이터 변환도
    실패 범위에 포함합니다. 작업 취소와 콜백 예외는 호출자에게 전파합니다.
    """
    if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("저장 제한 시간은 유한한 양수여야 합니다.")

    saved = False
    try:
        async with asyncio.timeout(timeout_seconds):
            content = build_content()
            await embedding_service.save(content)
        saved = True
    except Exception as error:
        # 예외 본문에는 SQL 매개변수나 분석 원문이 들어갈 수 있습니다.
        logger.warning("임베딩 저장 실패, 요약 콜백 계속 진행: %s", type(error).__name__)

    await notify()
    return saved
