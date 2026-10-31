import asyncio
from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock

import httpx
from pydantic import ValidationError

from app.schemas.search import SearchRequest, SearchResult
from app.search_app import create_app
from app.services.retrieval import SearchService, SearchPolicy


class SearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider, self.repository = AsyncMock(), AsyncMock()
        self.provider.embed_query.return_value = [1.0, 0.0, 0.0]
        self.repository.search.return_value = [SearchResult(bookmark_id=123, similarity=0.8)]
        self.service = SearchService(self.provider, self.repository, 3)

    async def call_api(self, payload, service=True):
        app = create_app(self.service if service else None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/ai/search", json=payload)

    async def test_contract_and_query_embedding(self):
        response = await self.call_api({"query": "React", "space_ids": [3, 8, 3]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"query": "React", "results": [{"bookmark_id": 123, "similarity": 0.8}]})
        self.provider.embed_query.assert_awaited_once_with("React")
        args = self.repository.search.call_args.kwargs
        self.assertEqual(args["filters"].space_ids, (3, 8))
        self.assertEqual(args["top_k"], 5)
        self.assertEqual(args["terms"], ("react",))

    async def test_empty_spaces_need_no_service(self):
        response = await self.call_api({"query": "React", "space_ids": []}, service=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        result = await self.service.search(SearchRequest(query="React", space_ids=[]))
        self.assertEqual(result.results, [])
        self.provider.embed_query.assert_not_called()
        self.repository.search.assert_not_called()

    async def test_unconfigured_service_returns_503(self):
        response = await self.call_api({"query": "React", "space_ids": [3]}, service=False)
        self.assertEqual(response.status_code, 503)

    async def test_invalid_requests_return_422(self):
        invalid = ({"query": " "}, {"query": 1}, {"space_ids": [True]}, {"space_ids": [0]},
                   {"space_ids": ["3"]}, {"space_ids": [2**63]}, {"top_k": 0}, {"top_k": 21},
                   {"top_k": True}, {"top_k": "5"}, {"saved_from": "2026-10-01", "saved_to": "2026-09-30"},
                   {"saved_from": "2026-02-30"}, {"saved_to": "2026-09-30T00:00:00Z"},
                   {"saved_from": 0}, {"saved_to": "9999-12-31"}, {"space_id": 3})
        for fields in invalid:
            with self.subTest(fields=fields):
                response = await self.call_api({"query": "React", "space_ids": [3], **fields})
                self.assertEqual(response.status_code, 422)
        self.provider.embed_query.assert_not_called()

    async def test_korean_date_bounds_include_entire_final_day(self):
        await self.service.search(SearchRequest(query="React", space_ids=[3],
                                                saved_from=date(2026, 9, 30), saved_to=date(2026, 9, 30)))
        filters = self.repository.search.call_args.kwargs["filters"]
        self.assertEqual(filters.saved_from.astimezone(timezone.utc), datetime(2026, 9, 29, 15, tzinfo=timezone.utc))
        self.assertEqual(filters.saved_before.astimezone(timezone.utc), datetime(2026, 9, 30, 15, tzinfo=timezone.utc))

    async def test_timezone_is_replaceable(self):
        service = SearchService(self.provider, self.repository, 3, SearchPolicy(date_timezone=timezone.utc))
        await service.search(SearchRequest(query="React", space_ids=[3], saved_from=date(2026, 9, 30)))
        self.assertEqual(self.repository.search.call_args.kwargs["filters"].saved_from.hour, 0)
        self.assertEqual(self.repository.search.call_args.kwargs["filters"].saved_from.utcoffset(), timedelta(0))

    async def test_invalid_provider_vectors_return_safe_error(self):
        for values in ([1, 0], [float("nan"), 1, 0], [float("inf"), 0, 1],
                       [True, 0, 1], ["1", 0, 1], [0, 0, 0], [1e39, 0, 1]):
            with self.subTest(values=values):
                self.provider.embed_query.return_value = values
                with self.assertLogs("app.api.search", level="ERROR"):
                    response = await self.call_api({"query": "React", "space_ids": [3]})
                self.assertEqual(response.status_code, 503)
        self.repository.search.assert_not_called()

    async def test_dependency_error_does_not_expose_exception(self):
        self.repository.search.side_effect = RuntimeError("secret-database-url")
        with self.assertLogs("app.api.search", level="ERROR") as logs:
            response = await self.call_api({"query": "React", "space_ids": [3]})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-database-url", response.text + " ".join(logs.output))

    async def test_model_and_database_timeout_return_504(self):
        async def never_finish(*args, **kwargs):
            await asyncio.Event().wait()
        self.service = SearchService(self.provider, self.repository, 3, SearchPolicy(timeout_seconds=0.01))
        for target in (self.provider.embed_query, self.repository.search):
            with self.subTest(target=target):
                target.side_effect = never_finish
                response = await self.call_api({"query": "React", "space_ids": [3]})
                self.assertEqual(response.status_code, 504)
                target.side_effect = None

    async def test_external_cancellation_propagates(self):
        self.provider.embed_query.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.service.search(SearchRequest(query="React", space_ids=[3]))
        self.repository.search.assert_not_called()

    async def test_docs_and_openapi_expose_exact_endpoint(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
            self.assertEqual((await client.get("/docs")).status_code, 200)
            schema = (await client.get("/openapi.json")).json()
        self.assertIn("/api/v1/ai/search", schema["paths"])
        self.assertEqual(schema["components"]["schemas"]["SearchRequest"]["properties"]["top_k"]["maximum"], 20)

    async def test_max_top_k_and_repeated_terms(self):
        await self.service.search(SearchRequest(query="React React", space_ids=[3], top_k=20))
        args = self.repository.search.call_args.kwargs
        self.assertEqual(args["top_k"], 20)
        self.assertEqual(args["terms"], ("react",))
