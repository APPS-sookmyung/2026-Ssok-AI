"""Spring이 삭제 커밋 후 호출하는 벡터 삭제 API."""

import asyncio
import logging
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_session
from app.repositories.vector_deletions import delete_vectors


delete_key = APIKeyHeader(name="X-AI-Secret", auto_error=False)
logger = logging.getLogger(__name__)
DELETE_TIMEOUT_SECONDS = 10


def authorize_delete(token: Annotated[str | None, Security(delete_key)]) -> None:
    configured = settings.VECTOR_DELETE_SECRET
    if configured is None or not configured.get_secret_value().strip():
        raise HTTPException(status_code=503, detail="벡터 삭제 인증이 설정되지 않았습니다.")
    if token is None or not compare_digest(token.encode(), configured.get_secret_value().encode()):
        raise HTTPException(status_code=401, detail="벡터 삭제 인증에 실패했습니다.")


router = APIRouter(
    prefix="/api/v1/ai/vectors", tags=["Vectors"], dependencies=[Depends(authorize_delete)],
    responses={401: {"description": "인증 실패"}, 503: {"description": "인증 미설정 또는 DB 오류"},
               504: {"description": "삭제 제한 시간 초과"}},
)


async def delete_target(session: AsyncSession, scope: Literal["bookmark", "space"], target_id: int) -> Response:
    try:
        async with asyncio.timeout(DELETE_TIMEOUT_SECONDS):
            await delete_vectors(session, scope, target_id)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="벡터 삭제 시간이 초과되었습니다.") from None
    except SQLAlchemyError as error:
        logger.error("벡터 삭제 DB 오류 (%s, %s): %s", scope, target_id, type(error).__name__)
        raise HTTPException(status_code=503, detail="벡터를 삭제할 수 없습니다.") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_bookmark_vector(
    bookmark_id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    return await delete_target(session, "bookmark", bookmark_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_space_vectors(
    space_id: Annotated[int, Query(gt=0, le=2**63 - 1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    return await delete_target(session, "space", space_id)
