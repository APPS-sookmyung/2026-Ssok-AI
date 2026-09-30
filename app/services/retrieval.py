"""교체 가능한 검색어 임베딩과 검색 저장소를 연결합니다."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone, tzinfo
import math
from numbers import Real
import re
from typing import Protocol

from app.schemas.search import SearchRequest, SearchResponse, SearchResult


class QueryEmbeddingProvider(Protocol):
    async def embed_query(self, query: str) -> Sequence[float]: ...


@dataclass(frozen=True)
class SearchPolicy:
    min_similarity: float = 0.5
    keyword_weight: float = 0.2
    date_timezone: tzinfo = timezone(timedelta(hours=9))
    timeout_seconds: float = 30.0

    def __post_init__(self):
        if not math.isfinite(self.min_similarity) or not -1 <= self.min_similarity <= 1:
            raise ValueError("유사도 기준값은 -1부터 1 사이여야 합니다.")
        if not math.isfinite(self.keyword_weight) or not 0 <= self.keyword_weight <= 1:
            raise ValueError("키워드 가중치는 0부터 1 사이여야 합니다.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("검색 제한 시간은 유한한 양수여야 합니다.")


@dataclass(frozen=True)
class SearchFilter:
    space_ids: tuple[int, ...]
    saved_from: datetime | None
    saved_before: datetime | None


class SearchRepository(Protocol):
    async def search(self, *, vector: tuple[float, ...], terms: tuple[str, ...],
                     filters: SearchFilter, top_k: int,
                     policy: SearchPolicy) -> list[SearchResult]: ...


def validate_query_vector(values: Sequence[float], dimensions: int) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)) or len(values) != dimensions:
        raise ValueError("검색어 벡터 차원이 설정과 다릅니다.")
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("검색어 벡터 원소는 숫자여야 합니다.")
        number = float(value)
        if not math.isfinite(number) or abs(number) > 3.4028234663852886e38:
            raise ValueError("검색어 벡터 원소가 float32 범위를 벗어났습니다.")
        result.append(number)
    if not any(abs(value) >= 1.401298464324817e-45 for value in result):
        raise ValueError("영벡터로 검색할 수 없습니다.")
    return tuple(result)


class SearchService:
    def __init__(self, provider: QueryEmbeddingProvider, repository: SearchRepository,
                 dimensions: int, policy: SearchPolicy | None = None):
        if type(dimensions) is not int or dimensions <= 0:
            raise ValueError("벡터 차원은 양의 정수여야 합니다.")
        self.provider = provider
        self.repository = repository
        self.dimensions = dimensions
        self.policy = policy or SearchPolicy()

    async def search(self, request: SearchRequest) -> SearchResponse:
        if not request.space_ids:
            return SearchResponse(query=request.query, results=[])
        zone = self.policy.date_timezone
        filters = SearchFilter(
            space_ids=tuple(request.space_ids),
            saved_from=datetime.combine(request.saved_from, time.min, zone) if request.saved_from else None,
            saved_before=datetime.combine(request.saved_to + timedelta(days=1), time.min, zone)
            if request.saved_to else None,
        )
        terms = tuple(dict.fromkeys(re.findall(r"\w+", request.query.casefold())))
        async with asyncio.timeout(self.policy.timeout_seconds):
            values = await self.provider.embed_query(request.query.strip())
            vector = validate_query_vector(values, self.dimensions)
            results = await self.repository.search(vector=vector, terms=terms, filters=filters,
                                                   top_k=request.top_k, policy=self.policy)
        return SearchResponse(query=request.query, results=results)
