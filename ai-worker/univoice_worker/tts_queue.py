"""Per-locale TTS delivery queues."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable

from .dedupe import DedupeStore, InMemoryDedupeStore, tts_dedupe_key
from .models import AudioStatus, TtsException, TtsJob, TtsResult
from .tts import SAMPLE_RATE

logger = logging.getLogger(__name__)

AudioStatusSink = Callable[[AudioStatus], Awaitable[None]]
QueueItem = TtsJob | None


async def _noop_audio_status(status: AudioStatus) -> None:
    return None


class LocaleTtsQueue:
    """Bounded per-locale TTS queues with one consumer per locale."""

    def __init__(
        self,
        *,
        locales: list[str],
        tts: Any,
        publisher: Any,
        on_audio_status: AudioStatusSink | None = None,
        dedupe_store: DedupeStore | None = None,
        queue_max_size: int = 100,
    ) -> None:
        self._locales = list(locales)
        self._locale_set = set(locales)
        self._tts = tts
        self._publisher = publisher
        self._on_audio_status = on_audio_status or _noop_audio_status
        self._dedupe = dedupe_store or InMemoryDedupeStore()
        self._queues: dict[str, asyncio.Queue[QueueItem]] = {
            locale: asyncio.Queue(maxsize=max(1, queue_max_size)) for locale in self._locales
        }
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._stopping = False
        self._stopped = True

    async def start(self) -> None:
        async with self._lifecycle_lock:
            running = [task for task in self._tasks.values() if not task.done()]
            if len(running) == len(self._queues):
                return
            self._stopping = False
            self._stopped = False
            for locale in self._locales:
                task = self._tasks.get(locale)
                if task is None or task.done():
                    self._tasks[locale] = asyncio.create_task(
                        self._consumer_loop(locale),
                        name=f"tts-consumer-{locale}",
                    )

    async def enqueue(self, job: TtsJob) -> bool:
        if job.locale not in self._locale_set:
            await self._emit_failed(job, "TTS_UNSUPPORTED_LOCALE")
            return False
        if self._stopping or self._stopped:
            if self._stopped:
                await self.start()
            if self._stopping:
                await self._emit_failed(job, "TTS_QUEUE_STOPPING")
                return False

        await self._put_or_drop_oldest(job)
        return True

    async def _put_or_drop_oldest(self, job: TtsJob) -> None:
        """Never block on a full queue. Blocking here would stall the segment
        consumer upstream and cause *newer* segments to be dropped instead —
        the opposite of what a live captioning/dubbing pipeline wants. Instead,
        evict the oldest pending job for this locale so the freshest speech
        always gets synthesized.
        """
        queue = self._queues[job.locale]
        while True:
            try:
                queue.put_nowait(job)
                return
            except asyncio.QueueFull:
                pass
            try:
                dropped = queue.get_nowait()
            except asyncio.QueueEmpty:
                continue  # a consumer freed a slot concurrently; retry the put
            queue.task_done()
            if dropped is None:
                # Shutdown sentinel raced with us; put it back and retry.
                await queue.put(None)
                continue
            logger.warning(
                "[%s] TTS queue overflow (locale=%s); dropping oldest segment %s for %s",
                job.session_id,
                job.locale,
                dropped.segment_id,
                job.segment_id,
            )
            await self._emit_failed(dropped, "TTS_QUEUE_OVERFLOW")

    async def flush_and_stop(self) -> None:
        async with self._lifecycle_lock:
            if self._stopped and not any(not queue.empty() for queue in self._queues.values()):
                return
            if not self._tasks:
                self._stopped = True
                return
            self._stopping = True

        for queue in self._queues.values():
            await queue.join()
        for locale, queue in self._queues.items():
            task = self._tasks.get(locale)
            if task is not None and not task.done():
                await queue.put(None)
        if self._tasks:
            results = await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("TTS consumer stopped with error: %r", result)

        async with self._lifecycle_lock:
            self._tasks.clear()
            self._stopping = False
            self._stopped = True

    async def _consumer_loop(self, locale: str) -> None:
        queue = self._queues[locale]
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                await self._handle_job(item)
            except Exception:  # noqa: BLE001
                logger.exception("TTS job handling failed unexpectedly (locale=%s)", locale)
            finally:
                queue.task_done()

    async def _handle_job(self, job: TtsJob) -> None:
        key = tts_dedupe_key(job.session_id, job.segment_id, job.locale)
        if await self._dedupe.is_done(key):
            await self._emit_completed(job, duration_ms=0)
            return
        if not await self._dedupe.try_acquire(key):
            if await self._dedupe.is_done(key):
                await self._emit_completed(job, duration_ms=0)
            else:
                await self._emit_failed(job, "TTS_DEDUPE_LOCKED")
            return

        await self._emit_started(job)
        try:
            pcm = await self._synthesize(job)
            duration_ms = await self._publish(job, pcm)
        except TtsException as exc:
            await self._dedupe.mark_failed(key)
            await self._emit_failed(job, exc.error_code)
            return
        except Exception as exc:  # noqa: BLE001
            await self._dedupe.mark_failed(key)
            await self._emit_failed(job, getattr(exc, "error_code", "AUDIO_PUBLISH_FAILED"))
            return

        await self._dedupe.mark_done(key)
        await self._emit_completed(job, duration_ms=duration_ms)

    async def _synthesize(self, job: TtsJob) -> bytes:
        if not job.text or not job.text.strip():
            raise TtsException("TTS_EMPTY_TEXT", "TTS text is empty", retryable=False)

        if hasattr(self._tts, "synthesize_job"):
            result = self._tts.synthesize_job(job)
        elif hasattr(self._tts, "synthesize_async"):
            result = self._tts.synthesize_async(job.locale, job.text, job=job)
        else:
            result = self._tts.synthesize(job.locale, job.text)

        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, TtsResult):
            result = result.pcm
        if not isinstance(result, (bytes, bytearray)):
            raise TtsException(
                "TTS_INVALID_RESULT",
                f"TTS returned unsupported result type {type(result).__name__}",
                retryable=False,
            )
        pcm = bytes(result)
        if not pcm:
            raise TtsException("TTS_EMPTY_AUDIO", "TTS returned empty audio", retryable=True)
        return pcm

    async def _publish(self, job: TtsJob, pcm: bytes) -> int:
        result = self._publisher.push_pcm(job.locale, pcm)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            return self._estimate_duration_ms(pcm)
        return int(result)

    @staticmethod
    def _estimate_duration_ms(pcm: bytes) -> int:
        sample_count = len(pcm) // 2
        return int(sample_count * 1000 / SAMPLE_RATE)

    async def _emit_started(self, job: TtsJob) -> None:
        await self._emit_status(
            AudioStatus(
                type="audio.started",
                session_id=job.session_id,
                segment_id=job.segment_id,
                sequence=job.sequence,
                locale=job.locale,
                duration_ms=None,
                error_code=None,
                timestamp=time.time(),
            )
        )

    async def _emit_completed(self, job: TtsJob, *, duration_ms: int) -> None:
        await self._emit_status(
            AudioStatus(
                type="audio.completed",
                session_id=job.session_id,
                segment_id=job.segment_id,
                sequence=job.sequence,
                locale=job.locale,
                duration_ms=duration_ms,
                error_code=None,
                timestamp=time.time(),
            )
        )

    async def _emit_failed(self, job: TtsJob, error_code: str) -> None:
        await self._emit_status(
            AudioStatus(
                type="audio.failed",
                session_id=job.session_id,
                segment_id=job.segment_id,
                sequence=job.sequence,
                locale=job.locale,
                duration_ms=None,
                error_code=error_code,
                timestamp=time.time(),
            )
        )

    async def _emit_status(self, status: AudioStatus) -> None:
        try:
            result = self._on_audio_status(status)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] audio status publish failed (%s, %s)",
                status.session_id,
                status.segment_id,
                status.locale,
            )
