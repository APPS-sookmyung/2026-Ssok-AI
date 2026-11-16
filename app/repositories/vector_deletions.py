"""삭제 기록과 벡터를 같은 트랜잭션에서 관리합니다."""

from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class VectorTargetDeleted(Exception):
    """Spring이 삭제한 북마크나 스페이스에는 벡터를 다시 저장할 수 없습니다."""


async def check_vector_target(session: AsyncSession, bookmark_id: int, space_id: int) -> None:
    # 양수 키는 북마크, 음수 키는 스페이스입니다. 저장끼리는 공유 잠금을 사용합니다.
    params = {"bookmark_id": bookmark_id, "space_id": space_id}
    await session.execute(text("""
        SELECT pg_advisory_xact_lock_shared(-CAST(:space_id AS bigint)),
               pg_advisory_xact_lock_shared(CAST(:bookmark_id AS bigint))
    """), params)
    # READ COMMITTED의 새 스냅샷에서 잠금 대기 중 커밋된 삭제까지 확인합니다.
    deleted = await session.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM vector_deletions
            WHERE (scope = 'bookmark' AND target_id = :bookmark_id)
               OR (scope = 'space' AND target_id = :space_id)
        )
    """), params)
    if deleted:
        raise VectorTargetDeleted


_DELETE = {
    "bookmark": text("DELETE FROM content_vectors WHERE bookmark_id = :target_id"),
    "space": text("DELETE FROM content_vectors WHERE space_id = :target_id"),
}


async def delete_vectors(session: AsyncSession, scope: Literal["bookmark", "space"], target_id: int) -> None:
    lock_key = target_id if scope == "bookmark" else -target_id
    async with session.begin():
        await session.execute(text("SELECT pg_advisory_xact_lock(CAST(:key AS bigint))"), {"key": lock_key})
        await session.execute(text("""
            INSERT INTO vector_deletions (scope, target_id) VALUES (:scope, :target_id)
            ON CONFLICT (scope, target_id) DO NOTHING
        """), {"scope": scope, "target_id": target_id})
        await session.execute(_DELETE[scope], {"target_id": target_id})
