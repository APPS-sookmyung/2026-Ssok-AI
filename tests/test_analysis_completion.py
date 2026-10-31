import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock

from app.schemas.embedding import BookmarkContent
from app.services.analysis_completion import save_embedding_and_notify
from app.services.embedding import EmbeddingService


class AnalysisCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.content = BookmarkContent(1, 2, "제목", "요약", ("태그",),
                                       datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.build_content = Mock(return_value=self.content)
        self.provider, self.store = AsyncMock(), AsyncMock()
        self.provider.embed_document.return_value = [1.0, 0.0, 0.0]
        self.service = EmbeddingService(self.provider, self.store, 3)
        self.payload = {"bookmark_id": 1, "status": "SUCCESS",
                        "analysis": {"summary": "요약", "category": "개발/기술", "tags": ["태그"]},
                        "error_message": None}
        self.sender = AsyncMock()

    async def run_completion(self, **kwargs):
        async def notify():
            await self.sender(self.payload)
        return await save_embedding_and_notify(build_content=self.build_content,
                                               embedding_service=self.service,
                                               notify=notify, **kwargs)

    def assert_success_callback(self):
        self.sender.assert_awaited_once_with({
            "bookmark_id": 1, "status": "SUCCESS",
            "analysis": {"summary": "요약", "category": "개발/기술", "tags": ["태그"]},
            "error_message": None,
        })

    async def test_save_precedes_callback(self):
        async def send(payload):
            self.store.upsert.assert_awaited_once_with(self.content, (1.0, 0.0, 0.0))
        self.sender.side_effect = send
        self.assertTrue(await self.run_completion())
        self.assert_success_callback()

    async def test_generation_failure_preserves_success_callback(self):
        self.provider.embed_document.side_effect = RuntimeError("secret input")
        with self.assertLogs("app.services.analysis_completion", level="WARNING") as logs:
            self.assertFalse(await self.run_completion())
        self.assertNotIn("secret input", " ".join(logs.output))
        self.store.upsert.assert_not_called()
        self.assert_success_callback()

    async def test_storage_failure_preserves_success_callback(self):
        self.store.upsert.side_effect = RuntimeError("storage failed")
        with self.assertLogs("app.services.analysis_completion", level="WARNING"):
            self.assertFalse(await self.run_completion())
        self.assert_success_callback()

    async def test_invalid_vector_preserves_success_callback(self):
        self.provider.embed_document.return_value = [float("nan"), 0, 1]
        with self.assertLogs("app.services.analysis_completion", level="WARNING"):
            self.assertFalse(await self.run_completion())
        self.store.upsert.assert_not_called()
        self.assert_success_callback()

    async def test_metadata_failure_preserves_success_callback(self):
        self.build_content.side_effect = ValueError("missing saved_at")
        with self.assertLogs("app.services.analysis_completion", level="WARNING"):
            self.assertFalse(await self.run_completion())
        self.provider.embed_document.assert_not_called()
        self.assert_success_callback()

    async def test_model_and_storage_timeout_still_notify(self):
        async def wait_forever(*args):
            await asyncio.Event().wait()
        for target in (self.provider.embed_document, self.store.upsert):
            with self.subTest(target=target):
                self.sender.reset_mock()
                target.side_effect = wait_forever
                with self.assertLogs("app.services.analysis_completion", level="WARNING"):
                    self.assertFalse(await self.run_completion(timeout_seconds=0.01))
                self.assert_success_callback()
                target.side_effect = None

    async def test_external_cancellation_propagates_without_callback(self):
        started = asyncio.Event()
        async def wait_forever(text):
            started.set()
            await asyncio.Event().wait()
        self.provider.embed_document.side_effect = wait_forever
        task = asyncio.create_task(self.run_completion())
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.sender.assert_not_called()

    async def test_callback_failure_propagates_without_retry(self):
        self.sender.side_effect = RuntimeError("callback failed")
        with self.assertRaisesRegex(RuntimeError, "callback failed"):
            await self.run_completion()
        self.sender.assert_awaited_once()
        self.store.upsert.assert_awaited_once()

    async def test_invalid_timeout_is_configuration_error(self):
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.run_completion(timeout_seconds=value)
        self.build_content.assert_not_called()
        self.sender.assert_not_called()
