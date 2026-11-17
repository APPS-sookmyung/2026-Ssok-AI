import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
import httpx
from pydantic import HttpUrl, SecretStr, ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.schemas.llm_output import LLMAnalysisOutput, SummaryRequest
from app.api.service_auth import SpringConnection


REQUEST = {
    "bookmark_id": 123,
    "url": "https://example.org/react",
    "callback_url": "http://localhost:8080/api/v1/bookmarks/ai-result",
}
METADATA = {"space_id": 7, "saved_at": "2026-11-14T00:30:00+09:00"}


class AnalysisMetadataTests(unittest.TestCase):
    def test_legacy_and_timezone_aware_requests(self):
        self.assertIsNone(SummaryRequest(**REQUEST).saved_at)
        for stamp in [METADATA["saved_at"], "2026-11-13T15:30:00Z"]:
            parsed = SummaryRequest(**REQUEST, space_id=7, saved_at=stamp)
            self.assertEqual(parsed.saved_at, datetime.fromisoformat(METADATA["saved_at"]))

    def test_reject_partial_invalid_or_unzoned_metadata(self):
        for fields in [
            {"space_id": 7}, {"saved_at": METADATA["saved_at"]},
            {**METADATA, "saved_at": "2026-11-14T00:30:00"}, {**METADATA, "saved_at": 1794600000},
            {**METADATA, "space_id": True}, {**METADATA, "space_id": 0},
            {**METADATA, "space_id": 2**63}, {**METADATA, "bookmark_id": -1},
        ]:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                SummaryRequest.model_validate({**REQUEST, **fields})

    def test_bookmark_id_is_a_positive_json_integer_in_both_modes(self):
        for fields in ({}, METADATA):
            for value in (True, "123", 1.0, 0, -1, 2**63):
                with self.subTest(fields=fields, value=value), self.assertRaises(ValidationError):
                    SummaryRequest.model_validate({**REQUEST, **fields, "bookmark_id": value})
            for value in (1, 2**63 - 1):
                parsed = SummaryRequest.model_validate({**REQUEST, **fields, "bookmark_id": value})
                self.assertEqual(parsed.bookmark_id, value)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class AnalyzeSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
        async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        with patch.dict(os.environ, {"DATABASE_URL": async_url, "GOOGLE_API_KEY": "unused-test-key"}):
            from app.main import app

        conn = await asyncpg.connect(url)
        self.addAsyncCleanup(conn.close)
        self.db = conn
        schema = "test_analysis_" + uuid4().hex
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        self.addAsyncCleanup(conn.execute, f'DROP SCHEMA "{schema}" CASCADE')
        await conn.execute(f'SET search_path TO "{schema}", public')
        for migration in sorted((Path(__file__).resolve().parents[1] / "sql").glob("[0-9]*.sql")):
            await conn.execute(migration.read_text(encoding="utf-8"))
        engine = create_async_engine(async_url, connect_args={"server_settings": {"search_path": f"{schema},public"}})
        self.enterContext(patch("app.main.AsyncSessionLocal", async_sessionmaker(engine)))
        self.enterContext(patch("app.main.engine", engine))

        sdk = self.enterContext(patch("app.services.query_embedding.GoogleGenerativeAIEmbeddings", autospec=True))
        self.sdk = sdk.return_value
        vector = [1.0] + [0.0] * 767
        self.sdk.aembed_documents.return_value = [vector]
        self.sdk.aembed_query.return_value = vector

        article = "리액트 버전별 렌더링 동작과 컴포넌트 업데이트 시점을 구체적인 예제로 비교합니다."
        html = f'<html><head><meta charset="utf-8"><title>리액트 비교</title></head><body><article><p>{article}</p></article></body></html>'
        self.fetch_html = self.enterContext(patch("app.services.scraper._fetch_html", return_value=html.encode()))
        self.analysis = LLMAnalysisOutput(summary=article, category="개발", tags=["리액트"])
        self.summarize = self.enterContext(patch("app.routes.llm_agent.summarize_and_tag", new_callable=AsyncMock))
        self.summarize.return_value = self.analysis
        self.spring = SpringConnection(AI_SERVICE_SECRET=SecretStr("spring-test"),
                                       AI_CALLBACK_URL=HttpUrl(REQUEST["callback_url"]),
                                       AI_CALLBACK_SECRET=SecretStr("callback-test"))
        self.enterContext(patch.object(app.state, "spring_connection", self.spring, create=True))
        self.callback = self.enterContext(patch("app.routes.requests.post"))
        self.callback.return_value.status_code = 200
        await self.enterAsyncContext(app.router.lifespan_context(app))
        self.app = app
        self.client = await self.enterAsyncContext(httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"X-AI-Service-Secret": "spring-test"},
        ))

    async def analyze(self, fields):
        response = await self.client.post("/api/v1/ai/analyze", json={**REQUEST, **fields})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "PROCESSING")

    async def search(self, spaces):
        response = await self.client.post("/api/v1/ai/search", json={"query": "리액트", "space_ids": spaces})
        self.assertEqual(response.status_code, 200, response.text)
        return [row["bookmark_id"] for row in response.json()["results"]]

    async def test_analyze_then_search_only_in_own_space(self):
        await self.analyze(METADATA)
        self.callback.assert_called_once()
        self.assertEqual(self.callback.call_args.args[0], REQUEST["callback_url"])
        self.assertEqual(self.callback.call_args.kwargs["headers"], {"X-AI-Callback-Secret": "callback-test"})
        self.assertFalse(self.callback.call_args.kwargs["allow_redirects"])
        self.assertEqual(self.callback.call_args.kwargs["json"]["status"], "SUCCESS")
        self.sdk.aembed_documents.assert_awaited_once_with(
            [f"제목: 리액트 비교\n요약: {self.analysis.summary}\n태그: 리액트"],
            task_type="RETRIEVAL_DOCUMENT", output_dimensionality=768,
        )
        self.assertEqual(await self.search([7]), [123])
        self.sdk.aembed_query.assert_awaited_once_with("리액트", task_type="RETRIEVAL_QUERY", output_dimensionality=768)
        self.assertEqual(await self.search([8]), [])
        self.assertEqual(await self.search([]), [])

        self.analysis.summary = "수정된 요약"
        await self.analyze({**METADATA, "saved_at": "2026-11-16T12:00:00+09:00"})
        rows = await self.db.fetch("SELECT bookmark_id, space_id, summary, saved_at FROM content_vectors")
        self.assertEqual([tuple(r) for r in rows], [(123, 7, "수정된 요약", datetime.fromisoformat(METADATA["saved_at"]))])

    async def test_only_authenticated_spring_can_start_analysis_or_search(self):
        for endpoint, body in [("analyze", {**REQUEST, **METADATA}), ("search", {"query": "검색", "space_ids": [7]})]:
            del self.client.headers["X-AI-Service-Secret"]
            for headers in ({}, {"X-AI-Service-Secret": "other"}):
                response = await self.client.post(f"/api/v1/ai/{endpoint}", json=body, headers=headers)
                self.assertEqual(response.status_code, 401)
            self.client.headers["X-AI-Service-Secret"] = "spring-test"
            with patch.object(self.spring, "AI_SERVICE_SECRET", None):
                response = await self.client.post(f"/api/v1/ai/{endpoint}", json=body)
                self.assertEqual(response.status_code, 503)
        self.fetch_html.assert_not_called()
        self.callback.assert_not_called()
        self.sdk.aembed_query.assert_not_awaited()

    async def test_requires_configured_exact_callback_before_accepting_work(self):
        for target in (REQUEST["callback_url"] + "/other", "https://example.org/result"):
            response = await self.client.post("/api/v1/ai/analyze", json={**REQUEST, "callback_url": target})
            self.assertEqual(response.status_code, 422)
        for name in ("AI_CALLBACK_URL", "AI_CALLBACK_SECRET"):
            with patch.object(self.spring, name, None):
                response = await self.client.post("/api/v1/ai/analyze", json=REQUEST)
                self.assertEqual(response.status_code, 503)
        self.fetch_html.assert_not_called()
        self.callback.assert_not_called()

    async def test_summary_only_can_finish_without_storage_service(self):
        with patch.object(self.app.state, "embedding_service", None):
            await self.analyze({})
            response = await self.client.post("/api/v1/ai/analyze", json={**REQUEST, **METADATA})
            self.assertEqual(response.status_code, 503)
        self.callback.assert_called_once()

    async def test_missing_page_title_is_omitted_from_embedding(self):
        self.fetch_html.return_value = b"<html><body><article><p>A full article with enough text to summarize and index for retrieval.</p></article></body></html>"
        await self.analyze(METADATA)
        document, = self.sdk.aembed_documents.await_args.args[0]
        self.assertNotIn("제목:", document)
        self.assertIn(self.analysis.summary, document)

    async def test_legacy_and_invalid_requests(self):
        await self.analyze({})
        self.assertEqual(self.callback.call_args.kwargs["json"]["status"], "SUCCESS")
        for fields in [{"space_id": 7}, {"saved_at": METADATA["saved_at"]}, {**METADATA, "saved_at": "2026-11-14"}]:
            response = await self.client.post("/api/v1/ai/analyze", json={**REQUEST, **fields})
            self.assertEqual(response.status_code, 422)
        self.callback.assert_called_once()
        self.sdk.aembed_documents.assert_not_awaited()
        self.assertEqual(await self.db.fetchval("SELECT count(*) FROM content_vectors"), 0)

    async def test_embedding_failure_preserves_row_and_success_callback(self):
        await self.analyze(METADATA)
        self.callback.reset_mock()
        original_summary = self.analysis.summary
        self.analysis.summary = "저장에 실패할 요약"
        self.sdk.aembed_documents.side_effect = RuntimeError("model unavailable")
        await self.analyze(METADATA)
        self.callback.assert_called_once()
        self.assertEqual(self.callback.call_args.kwargs["json"]["status"], "SUCCESS")
        summary = await self.db.fetchval("SELECT summary FROM content_vectors WHERE bookmark_id = 123")
        self.assertEqual(summary, original_summary)
        self.assertEqual(await self.search([7]), [123])

    async def test_failed_analysis_does_not_index(self):
        self.summarize.side_effect = RuntimeError("summarization unavailable")
        await self.analyze(METADATA)
        self.callback.assert_called_once()
        self.assertEqual(self.callback.call_args.kwargs["json"]["status"], "FAILED")
        self.sdk.aembed_documents.assert_not_awaited()
        self.assertEqual(await self.search([7]), [])
