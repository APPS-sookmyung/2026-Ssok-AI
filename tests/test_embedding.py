import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock

from app.schemas.embedding import BookmarkContent, validate_embedding
from app.services.embedding import EmbeddingService, build_embedding_input


def sample():
    return BookmarkContent(1, 2, " 제목 ", " 요약 ", ("태그", " "), datetime.now(timezone.utc))


class EmbeddingTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_and_save(self):
        provider, store = AsyncMock(), AsyncMock()
        provider.embed_document.return_value = [1, 0, 0]
        content = sample()
        await EmbeddingService(provider, store, 3).save(content)
        provider.embed_document.assert_awaited_once_with("제목: 제목\n요약: 요약\n태그: 태그")
        store.upsert.assert_awaited_once_with(content, (1.0, 0.0, 0.0))

    async def test_invalid_result_never_reaches_storage(self):
        for values in ([1, 2], [float("nan"), 0, 1], [float("inf"), 0, 1],
                       [True, 0, 1], ["1", 0, 1], [0, 0, 0], [1e39, 0, 1]):
            with self.subTest(values=values):
                provider, store = AsyncMock(), AsyncMock()
                provider.embed_document.return_value = values
                with self.assertRaises(ValueError):
                    await EmbeddingService(provider, store, 3).save(sample())
                store.upsert.assert_not_called()

    async def test_provider_failure_and_cancellation(self):
        for error in (RuntimeError("provider failed"), asyncio.CancelledError()):
            provider, store = AsyncMock(), AsyncMock()
            provider.embed_document.side_effect = error
            with self.assertRaises(type(error)):
                await EmbeddingService(provider, store, 3).save(sample())
            store.upsert.assert_not_called()

    async def test_timeout(self):
        async def slow(text):
            await asyncio.Event().wait()
        provider, store = AsyncMock(), AsyncMock()
        provider.embed_document.side_effect = slow
        with self.assertRaises(TimeoutError):
            await EmbeddingService(provider, store, 3, 0.01).save(sample())
        store.upsert.assert_not_called()

    async def test_storage_error_is_reported(self):
        provider, store = AsyncMock(), AsyncMock()
        provider.embed_document.return_value = [1, 0, 0]
        store.upsert.side_effect = RuntimeError("database failed")
        with self.assertRaises(RuntimeError):
            await EmbeddingService(provider, store, 3).save(sample())

    def test_empty_content(self):
        with self.assertRaises(ValueError):
            build_embedding_input(replace(sample(), title=" ", summary="", tags=()))

    def test_invalid_metadata(self):
        for changes in ({"saved_at": datetime.now()}, {"bookmark_id": True},
                        {"space_id": 0}, {"tags": "tag"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(sample(), **changes)

    def test_invalid_dimensions(self):
        for dimensions in (0, -1, True):
            with self.assertRaises(ValueError):
                validate_embedding([1], dimensions)
