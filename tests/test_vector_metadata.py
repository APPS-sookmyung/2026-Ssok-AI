"""전용 pgvector DB에서만 실행하는 스키마 마이그레이션 회귀 테스트."""
import os
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch

import asyncpg
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "전용 TEST_DATABASE_URL을 지정해야 합니다.")
class VectorMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(TEST_DATABASE_URL)
        self.conn = await asyncpg.connect(
            host=url.host, port=url.port or 5432, user=url.username,
            password=url.password, database=url.database, timeout=10,
        )
        self.addAsyncCleanup(self.conn.close)
        self.schema = "test_vector_metadata_" + uuid4().hex
        await self.conn.execute(f'CREATE SCHEMA "{self.schema}"')
        self.addAsyncCleanup(self.drop_schema)
        await self.conn.execute(
            "SELECT set_config('search_path', $1, false)",
            self.schema + ",public",
        )
        self.vector = "[" + ",".join(["0.1"] * 768) + "]"

    async def drop_schema(self):
        # UUID로 생성한 이 테스트 소유 schema만 제거합니다.
        await self.conn.execute(f'DROP SCHEMA "{self.schema}" CASCADE')

    async def run_sql(self, filename):
        await self.conn.execute((ROOT / filename).read_text(encoding="utf-8"))

    async def columns(self):
        return await self.conn.fetch(
            """SELECT column_name, data_type, is_nullable, column_default
               FROM information_schema.columns
               WHERE table_schema = $1 AND table_name = 'content_vectors'
               ORDER BY column_name""", self.schema,
        )

    async def test_existing_row_survives_repeated_migration(self):
        await self.run_sql("tests/fixtures/content_vectors_legacy.sql")
        await self.conn.execute(
            """INSERT INTO content_vectors
               (bookmark_id, space_id, embedding, created_at, updated_at)
               VALUES (1, 8, $1::vector, '2026-05-12T03:00:00Z',
                       '2026-05-13T03:00:00Z')""", self.vector,
        )
        before = await self.conn.fetchrow(
            """SELECT bookmark_id, space_id, embedding::text AS embedding,
                      created_at, updated_at FROM content_vectors WHERE bookmark_id=1"""
        )
        await self.run_sql("sql/002_add_vector_metadata.sql")
        await self.run_sql("sql/002_add_vector_metadata.sql")
        after = await self.conn.fetchrow(
            """SELECT bookmark_id, space_id, embedding::text AS embedding,
                      created_at, updated_at FROM content_vectors WHERE bookmark_id=1"""
        )
        self.assertEqual(dict(before), dict(after))
        row = await self.conn.fetchrow(
            "SELECT title, summary, saved_at FROM content_vectors WHERE bookmark_id=1"
        )
        self.assertEqual(dict(row), dict(title=None, summary=None, saved_at=None))
        self.assertEqual(await self.conn.fetchval("SELECT count(*) FROM content_vectors"), 1)

    async def test_fresh_and_migrated_columns_match(self):
        await self.run_sql("tests/fixtures/content_vectors_legacy.sql")
        await self.run_sql("sql/002_add_vector_metadata.sql")
        migrated = [dict(row) for row in await self.columns()]
        await self.conn.execute("DROP TABLE content_vectors")
        await self.run_sql("sql/001_init_pgvector.sql")
        self.assertEqual(migrated, [dict(row) for row in await self.columns()])
        # 001로 새로 만든 DB에서도 002 적용이 안전해야 합니다.
        await self.run_sql("sql/002_add_vector_metadata.sql")

    async def test_saved_at_nullable_without_default_and_indexed(self):
        await self.run_sql("sql/001_init_pgvector.sql")
        fields = {row["column_name"]: row for row in await self.columns()}
        for name in ("title", "summary", "saved_at"):
            self.assertEqual(fields[name]["is_nullable"], "YES")
            self.assertIsNone(fields[name]["column_default"])
        self.assertEqual(fields["saved_at"]["data_type"], "timestamp with time zone")
        index = await self.conn.fetchval(
            """SELECT indexdef FROM pg_indexes
               WHERE schemaname=$1 AND tablename='content_vectors'
                 AND indexname='idx_content_vectors_saved_at'""", self.schema,
        )
        self.assertIsNotNone(index)
        self.assertIn("(saved_at)", index)

    async def test_orm_round_trip_and_legacy_writer(self):
        await self.run_sql("sql/001_init_pgvector.sql")
        url = make_url(TEST_DATABASE_URL).set(drivername="postgresql+asyncpg")
        # Settings가 로컬 .env/API 키에 의존하지 않도록 테스트용 값만 주입합니다.
        with patch.dict(os.environ, {
            "DATABASE_URL": url.render_as_string(hide_password=False),
            "GOOGLE_API_KEY": "unused-test-key", "EMBEDDING_DIM": "768",
        }):
            from app.models.content_vector import ContentVector

        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": self.schema + ",public"}}
        )
        self.addAsyncCleanup(engine.dispose)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        saved_at = datetime(2026, 5, 15, 12, 30, tzinfo=timezone(timedelta(hours=9)))
        async with sessions() as session:
            session.add(ContentVector(
                bookmark_id=2, space_id=8, embedding=[0.1] * 768,
                title="한글 제목: 미디어 논문", summary="한국어 검색 검증용 요약",
                saved_at=saved_at,
            ))
            session.add(ContentVector(bookmark_id=3, space_id=8, embedding=[0.1] * 768))
            await session.commit()
        async with sessions() as session:
            row = await session.get(ContentVector, 2)
            self.assertEqual(row.title, "한글 제목: 미디어 논문")
            self.assertEqual(row.summary, "한국어 검색 검증용 요약")
            self.assertEqual(row.saved_at, saved_at)
            self.assertIsNotNone(row.saved_at.tzinfo)
            legacy = await session.get(ContentVector, 3)
            self.assertIsNone(legacy.title)
            self.assertIsNone(legacy.summary)
            self.assertIsNone(legacy.saved_at)
            matches = (await session.scalars(
                select(ContentVector.bookmark_id).where(
                    ContentVector.saved_at >= datetime(2026, 5, 15, tzinfo=timezone.utc),
                    ContentVector.saved_at < datetime(2026, 5, 16, tzinfo=timezone.utc),
                )
            )).all()
            self.assertEqual(matches, [2])


if __name__ == "__main__":
    unittest.main()
