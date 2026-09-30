import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.content_vectors import ContentVectorRepository
from app.schemas.embedding import BookmarkContent
from app.services.embedding import EmbeddingService


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class VectorStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
        self.connection = await asyncpg.connect(url)
        self.schema = "test_vector_storage_" + uuid4().hex
        await self.connection.execute(f'CREATE SCHEMA "{self.schema}"')
        self.addAsyncCleanup(self.cleanup)
        await self.connection.execute(f'SET search_path TO "{self.schema}", public')
        fixture = Path(__file__).parent / "fixtures" / "content_vectors_metadata.sql"
        await self.connection.execute(fixture.read_text(encoding="utf-8"))
        self.engine = create_async_engine(
            url.replace("postgresql://", "postgresql+asyncpg://", 1),
            connect_args={"server_settings": {"search_path": f"{self.schema},public"}},
        )
        self.store = ContentVectorRepository(async_sessionmaker(self.engine), 768)
        self.content = BookmarkContent(123, 7, "원래 제목", "원래 요약", ("태그",),
                                       datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.vector = [1.0] + [0.0] * 767

    async def cleanup(self):
        if hasattr(self, "engine"):
            await self.engine.dispose()
        await self.connection.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        await self.connection.close()

    async def row(self):
        return await self.connection.fetchrow("SELECT *, embedding::text AS vector_text FROM content_vectors")

    async def test_insert_and_update(self):
        await self.store.upsert(self.content, self.vector)
        before = await self.row()
        changed = replace(self.content, space_id=9, title="새 제목", summary="새 요약",
                          saved_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
        await self.store.upsert(changed, [0.0, 1.0] + [0.0] * 766)
        after = await self.row()
        self.assertEqual(await self.connection.fetchval("SELECT count(*) FROM content_vectors"), 1)
        self.assertEqual((after["space_id"], after["title"], after["summary"], after["saved_at"]),
                         (9, changed.title, changed.summary, changed.saved_at))
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertGreater(after["updated_at"], before["updated_at"])
        self.assertNotEqual(after["vector_text"], before["vector_text"])

    async def test_generation_failure_preserves_existing_row(self):
        await self.store.upsert(self.content, self.vector)
        before = await self.row()
        provider = AsyncMock()
        provider.embed_document.side_effect = RuntimeError("generation failed")
        with self.assertRaises(RuntimeError):
            await EmbeddingService(provider, self.store, 768).save(replace(self.content, title="새 제목"))
        self.assertEqual(await self.row(), before)

    async def test_database_failure_rolls_back_and_session_recovers(self):
        await self.store.upsert(self.content, self.vector)
        before = await self.row()
        await self.connection.execute("ALTER TABLE content_vectors ADD CHECK (space_id <> 999)")
        with self.assertRaises(DBAPIError):
            await self.store.upsert(replace(self.content, space_id=999, title="저장 실패"), self.vector)
        self.assertEqual(await self.row(), before)
        await self.store.upsert(replace(self.content, title="복구 성공"), self.vector)
        self.assertEqual((await self.row())["title"], "복구 성공")

    async def test_invalid_vector_preserves_existing_row(self):
        await self.store.upsert(self.content, self.vector)
        before = await self.row()
        with self.assertRaises(ValueError):
            await self.store.upsert(self.content, [1.0])
        self.assertEqual(await self.row(), before)
