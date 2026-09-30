"""스페이스와 날짜로 제한한 정확 벡터 검색 및 키워드 순위 보정."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.search import SearchResult
from app.services.retrieval import SearchFilter, SearchPolicy


_SEARCH = text("""
    WITH candidates AS (
        SELECT bookmark_id,
               1 - (embedding <=> CAST(:vector AS vector)) AS similarity,
               CASE WHEN cardinality(CAST(:terms AS text[])) = 0 THEN 0.0
                    ELSE (SELECT count(*)::float / cardinality(CAST(:terms AS text[]))
                          FROM unnest(CAST(:terms AS text[])) AS word(term)
                          WHERE strpos(lower(coalesce(title, '') || ' ' || coalesce(summary, '')), term) > 0)
               END AS keyword_score
        FROM content_vectors
        WHERE space_id = ANY(CAST(:space_ids AS bigint[]))
          AND (CAST(:saved_from AS timestamptz) IS NULL OR saved_at >= CAST(:saved_from AS timestamptz))
          AND (CAST(:saved_before AS timestamptz) IS NULL OR saved_at < CAST(:saved_before AS timestamptz))
          AND (embedding <#> embedding) < 0
    )
    SELECT bookmark_id, greatest(-1.0, least(1.0, similarity)) AS similarity
    FROM candidates
    WHERE similarity >= :min_similarity AND similarity <= 1.000001
    ORDER BY ((1 - CAST(:keyword_weight AS double precision)) * similarity
              + CAST(:keyword_weight AS double precision) * keyword_score) DESC,
             similarity DESC, bookmark_id ASC
    LIMIT :top_k
""")


class PostgresSearchRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def search(self, *, vector: tuple[float, ...], terms: tuple[str, ...],
                     filters: SearchFilter, top_k: int,
                     policy: SearchPolicy) -> list[SearchResult]:
        if not filters.space_ids:
            return []
        async with self.sessions() as session:
            rows = await session.execute(_SEARCH, {
                "vector": "[" + ",".join(str(value) for value in vector) + "]",
                "terms": list(terms), "space_ids": list(filters.space_ids),
                "saved_from": filters.saved_from, "saved_before": filters.saved_before,
                "min_similarity": policy.min_similarity,
                "keyword_weight": policy.keyword_weight, "top_k": top_k,
            })
            return [SearchResult(**row) for row in rows.mappings()]
