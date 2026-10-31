import math
import os
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.search import PostgresSearchRepository
from app.schemas.search import SearchRequest
from app.search_app import create_app
from app.services.retrieval import SearchService, SearchPolicy


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class SearchDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
        self.connection = await asyncpg.connect(url)
        self.schema = "test_search_" + uuid4().hex
        await self.connection.execute(f'CREATE SCHEMA "{self.schema}"')
        self.addAsyncCleanup(self.cleanup)
        await self.connection.execute(f'SET search_path TO "{self.schema}", public')
        fixture = Path(__file__).parent / "fixtures" / "search_vectors.sql"
        await self.connection.execute(fixture.read_text(encoding="utf-8"))
        self.engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://", 1),
            connect_args={"server_settings": {"search_path": f"{self.schema},public"}})
        self.repository = PostgresSearchRepository(async_sessionmaker(self.engine))
        self.provider = AsyncMock()
        self.provider.embed_query.return_value = [1.0] + [0.0] * 767
        self.service = SearchService(self.provider, self.repository, 768)

    async def cleanup(self):
        if hasattr(self, "engine"):
            await self.engine.dispose()
        await self.connection.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        await self.connection.close()

    async def insert(self, bookmark_id, space_id=3, similarity=1.0, title="일반 문서", summary=None,
                     saved_at="2026-09-30T03:00:00+00:00", zero=False):
        vector = [similarity, math.sqrt(max(0.0, 1 - similarity**2))] + [0.0] * 766
        if zero:
            vector = [0.0] * 768
        await self.connection.execute(
            "INSERT INTO content_vectors (bookmark_id, space_id, embedding, title, summary, saved_at) "
            "VALUES ($1, $2, $3::text::vector, $4, $5, $6)",
            bookmark_id, space_id, "[" + ",".join(map(str, vector)) + "]", title, summary,
            datetime.fromisoformat(saved_at) if saved_at else None,
        )

    async def search(self, **kwargs):
        return await self.service.search(SearchRequest(**{"query": "React", "space_ids": [3], **kwargs}))

    async def test_space_filter_applies_to_both_vector_and_keyword_ranking(self):
        await self.insert(1, space_id=3, similarity=0.8, title="React")
        await self.insert(2, space_id=9, similarity=1.0, title="React")
        await self.insert(3, space_id=8, similarity=0.9, title="React")
        result = await self.search(space_ids=[3, 8], top_k=20)
        self.assertEqual({item.bookmark_id for item in result.results}, {1, 3})
        result = await self.search(space_ids=[9])
        self.assertEqual([item.bookmark_id for item in result.results], [2])

    async def test_keyword_weight_changes_order_but_response_is_cosine(self):
        await self.insert(1, similarity=1.0)
        await self.insert(2, similarity=0.8, title="React 비교")
        result = await self.search()
        self.assertEqual([item.bookmark_id for item in result.results], [2, 1])
        self.assertAlmostEqual(result.results[0].similarity, 0.8, places=5)
        self.service = SearchService(self.provider, self.repository, 768, SearchPolicy(keyword_weight=0))
        result = await self.search()
        self.assertEqual([item.bookmark_id for item in result.results], [1, 2])

    async def test_threshold_and_zero_vectors(self):
        await self.insert(1, similarity=0.49, title="React")
        await self.insert(2, similarity=0.5)
        await self.insert(3, similarity=-1.0, title="React")
        await self.insert(4, zero=True, title="React")
        result = await self.search()
        self.assertEqual([item.bookmark_id for item in result.results], [2])

    async def test_date_bounds_include_korean_day_and_exclude_unknown_date(self):
        await self.insert(1, saved_at="2026-09-29T14:59:59.999999+00:00")
        await self.insert(2, saved_at="2026-09-29T15:00:00+00:00")
        await self.insert(3, saved_at="2026-09-30T14:59:59.999999+00:00")
        await self.insert(4, saved_at="2026-09-30T15:00:00+00:00")
        await self.insert(5, saved_at=None, title=None)
        bounded = await self.search(saved_from="2026-09-30", saved_to="2026-09-30")
        self.assertEqual([item.bookmark_id for item in bounded.results], [2, 3])
        unbounded = await self.search()
        self.assertEqual({item.bookmark_id for item in unbounded.results}, {1, 2, 3, 4, 5})
        start_only = await self.search(saved_from="2026-09-30")
        self.assertEqual({item.bookmark_id for item in start_only.results}, {2, 3, 4})
        end_only = await self.search(saved_to="2026-09-30")
        self.assertEqual({item.bookmark_id for item in end_only.results}, {1, 2, 3})

    async def test_top_k_and_tie_order_are_stable(self):
        for bookmark_id in range(25, 0, -1):
            await self.insert(bookmark_id)
        for top_k in (1, 5, 20):
            with self.subTest(top_k=top_k):
                result = await self.search(top_k=top_k)
                self.assertEqual([item.bookmark_id for item in result.results], list(range(1, top_k + 1)))

    async def test_korean_keyword_in_summary_and_null_metadata(self):
        await self.insert(1, similarity=1.0, title=None)
        await self.insert(2, similarity=0.8, title=None, summary="리액트 버전 비교 자료")
        result = await self.search(query="리액트")
        self.assertEqual([item.bookmark_id for item in result.results], [2, 1])

    async def test_parameterized_query_and_no_matches(self):
        await self.insert(1)
        await self.search(query="'); DROP TABLE content_vectors; -- % _")
        self.assertEqual(await self.connection.fetchval("SELECT count(*) FROM content_vectors"), 1)
        self.assertEqual((await self.search(space_ids=[999])).results, [])
        self.assertEqual((await self.search(query="!!!")).results[0].bookmark_id, 1)

    async def test_api_to_database_flow(self):
        await self.insert(123, title="React", similarity=0.8)
        await self.insert(456, space_id=9, title="React")
        app = create_app(self.service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/ai/search", json={"query": "React", "space_ids": [3]})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["query"], "React")
        self.assertEqual([item["bookmark_id"] for item in payload["results"]], [123])
        self.assertEqual(set(payload["results"][0]), {"bookmark_id", "similarity"})
