import asyncio
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
import httpx
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.content_vectors import ContentVectorRepository
from app.repositories.search import PostgresSearchRepository
from app.repositories.vector_deletions import check_vector_target
from app.schemas.embedding import BookmarkContent
from app.services.analysis_completion import save_embedding_and_notify
from app.services.embedding import EmbeddingService
from app.services.retrieval import SearchService


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class VectorDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
        async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        with patch.dict(os.environ, {"DATABASE_URL": async_url, "GOOGLE_API_KEY": "unused-test-key"}):
            from app.config import settings
            from app.db.session import get_session
            from app.main import app

        self.db = await asyncpg.connect(url)
        self.addAsyncCleanup(self.db.close)
        schema = "test_delete_" + uuid4().hex
        await self.db.execute(f'CREATE SCHEMA "{schema}"')
        self.addAsyncCleanup(self.db.execute, f'DROP SCHEMA "{schema}" CASCADE')
        await self.db.execute(f'SET search_path TO "{schema}", public')
        for migration in sorted((Path(__file__).resolve().parents[1] / "sql").glob("[0-9]*.sql")):
            await self.db.execute(migration.read_text(encoding="utf-8"))

        engine = create_async_engine(async_url, connect_args={"server_settings": {"search_path": f"{schema},public"}})
        self.addAsyncCleanup(engine.dispose)
        self.sessions = async_sessionmaker(engine)
        self.store = ContentVectorRepository(self.sessions, 768)
        self.vector = [1.0] + [0.0] * 767

        async def test_session():
            async with self.sessions() as session:
                yield session

        self.enterContext(patch.dict(app.dependency_overrides, {get_session: test_session}))
        provider = AsyncMock()
        provider.embed_query.return_value = self.vector
        service = SearchService(provider, PostgresSearchRepository(self.sessions), 768)
        self.enterContext(patch.object(app.state, "search_service", service, create=True))
        self.enterContext(patch.object(settings, "VECTOR_DELETE_SECRET", SecretStr("unit-test-only")))
        self.client = await self.enterAsyncContext(httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
        ))
        self.headers = {"X-AI-Secret": "unit-test-only"}
        self.url = "/api/v1/ai/vectors"

    def content(self, bookmark_id, space_id):
        return BookmarkContent(bookmark_id, space_id, "리액트", "렌더링 요약", ("리액트",),
                               datetime(2026, 11, 14, tzinfo=timezone.utc))

    async def search(self, space_ids):
        response = await self.client.post("/api/v1/ai/search", json={"query": "리액트", "space_ids": space_ids})
        self.assertEqual(response.status_code, 200, response.text)
        return sorted(item["bookmark_id"] for item in response.json()["results"])

    async def delete(self, path):
        response = await self.client.delete(self.url + path, headers=self.headers)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")

    async def test_bookmark_then_space_deletion_is_scoped_and_idempotent(self):
        for bookmark_id, space_id in [(11, 7), (12, 7), (13, 8)]:
            await self.store.upsert(self.content(bookmark_id, space_id), self.vector)
        await self.delete("/11")
        await self.delete("/11")
        self.assertEqual(await self.search([7, 8]), [12, 13])
        await self.delete("?space_id=7")
        await self.delete("?space_id=7")
        self.assertEqual(await self.search([7]), [])
        self.assertEqual(await self.search([8]), [13])
        await self.delete("/999")
        await self.delete("?space_id=999")
        markers = await self.db.fetch("SELECT scope, target_id FROM vector_deletions ORDER BY scope, target_id")
        self.assertEqual([tuple(row) for row in markers], [("bookmark", 11), ("bookmark", 999), ("space", 7), ("space", 999)])

    async def test_authentication_and_invalid_ids_leave_data_intact(self):
        await self.store.upsert(self.content(11, 7), self.vector)
        for path in ["/11", "?space_id=7"]:
            for headers in [{}, {"X-AI-Secret": "incorrect"}]:
                response = await self.client.delete(self.url + path, headers=headers)
                self.assertEqual(response.status_code, 401)
        with patch("app.api.vectors.settings.VECTOR_DELETE_SECRET", None):
            response = await self.client.delete(self.url + "/11", headers=self.headers)
            self.assertEqual(response.status_code, 503)
        for path in ["", "/0", "/-1", "?space_id=0", f"?space_id={2**63}", "?space_id="]:
            response = await self.client.delete(self.url + path, headers=self.headers)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(await self.search([7]), [11])
        self.assertEqual(await self.db.fetchval("SELECT count(*) FROM vector_deletions"), 0)

    async def test_delete_during_first_embedding_prevents_reinsertion(self):
        for bookmark_id, space_id, path in [(21, 7, "/21"), (22, 8, "?space_id=8")]:
            with self.subTest(path=path):
                entered, resume = asyncio.Event(), asyncio.Event()

                async def embed_document(_text):
                    entered.set()
                    await resume.wait()
                    return self.vector

                provider, notify = AsyncMock(), AsyncMock()
                provider.embed_document.side_effect = embed_document
                content = self.content(bookmark_id, space_id)
                async with asyncio.TaskGroup() as jobs:
                    pending = jobs.create_task(save_embedding_and_notify(
                        build_content=lambda: content,
                        embedding_service=EmbeddingService(provider, self.store, 768), notify=notify,
                    ))
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    await self.delete(path)
                    resume.set()
                self.assertFalse(pending.result())
                notify.assert_awaited_once_with()
                self.assertEqual(await self.search([space_id]), [])

    async def test_delete_waits_for_writer_and_removes_committed_row(self):
        await self.store.upsert(self.content(31, 7), self.vector)
        async with asyncio.TaskGroup() as jobs:
            async with self.sessions.begin() as writer:
                await check_vector_target(writer, 31, 7)
                await writer.execute(text("UPDATE content_vectors SET title = '수정' WHERE bookmark_id = 31"))
                jobs.create_task(self.delete("/31"))
                async with asyncio.timeout(5):
                    while not await self.db.fetchval("""
                        SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory'
                                       AND objid = 31 AND NOT granted)
                    """):
                        await asyncio.sleep(0.01)
        self.assertEqual(await self.search([7]), [])

    async def test_failed_delete_rolls_back_marker_and_can_retry(self):
        await self.store.upsert(self.content(41, 7), self.vector)
        await self.db.execute("CREATE TABLE held_bookmark (id bigint REFERENCES content_vectors(bookmark_id))")
        await self.db.execute("INSERT INTO held_bookmark VALUES (41)")
        response = await self.client.delete(self.url + "/41", headers=self.headers)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(await self.search([7]), [41])
        self.assertEqual(await self.db.fetchval("SELECT count(*) FROM vector_deletions"), 0)
        await self.db.execute("DELETE FROM held_bookmark WHERE id = 41")
        await self.delete("/41")
        self.assertEqual(await self.search([7]), [])
