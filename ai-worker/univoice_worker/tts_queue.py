"""Per-locale TTS delivery queues."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable

from .dedupe import DedupeStore, InMemoryDedupeStore, tts_dedupe_key
from .latency import LatencyLog, default_log, elapsed_ms
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
        enqueue_timeout_sec: float = 1.0,
        flush_timeout_sec: float = 3.0,
        latency_log: LatencyLog | None = None,
    ) -> None:
        self._locales = list(locales)
        self._locale_set = set(locales)
        self._tts = tts
        self._publisher = publisher
        self._on_audio_status = on_audio_status or _noop_audio_status
        self._dedupe = dedupe_store or InMemoryDedupeStore()
        self._latency = latency_log or default_log()
        self._enqueue_timeout = max(0.05, enqueue_timeout_sec)
        self._flush_timeout = max(0.1, flush_timeout_sec)
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

        try:
            # 무제한 put 은 큐가 찼을 때 세그먼트 컨슈머를 영구 블록시켜
            # 파이프라인 flush(queue.join)까지 연쇄로 매달리게 한다.
            # 실시간 자막에서 밀린 음성은 어차피 시효가 지난 것 — 드롭이 맞다.
            await asyncio.wait_for(
                self._queues[job.locale].put(job), timeout=self._enqueue_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[%s] TTS 큐(%s) 가득참 — 세그먼트 %s 음성 드롭",
                job.session_id,
                job.locale,
                job.segment_id,
            )
            await self._emit_failed(job, "TTS_QUEUE_FULL")
            return False
        return True

    async def flush_and_stop(self) -> None:
        async with self._lifecycle_lock:
            if self._stopped and not any(not queue.empty() for queue in self._queues.values()):
                return
            if not self._tasks:
                self._stopped = True
                return
            self._stopping = True

        # 남은 잡을 실시간 재생 속도로 전부 드레인하면 세션 종료가 수십~수백 초
        # 걸린다. NestJS 는 8초 뒤 룸을 지우므로 그 이후의 재생은 무가치하다.
        # 제한 시간 안에 안 끝나면 백로그를 폐기한다.
        try:
            await asyncio.wait_for(
                asyncio.gather(*(queue.join() for queue in self._queues.values())),
                timeout=self._flush_timeout,
            )
        except asyncio.TimeoutError:
            discarded = sum(queue.qsize() for queue in self._queues.values())
            logger.warning(
                "TTS flush 가 %.0f초 내 끝나지 않아 백로그 %d건을 폐기한다",
                self._flush_timeout,
                discarded,
            )
            for task in self._tasks.values():
                if not task.done():
                    task.cancel()
            for queue in self._queues.values():
                while not queue.empty():
                    try:
                        queue.get_nowait()
                        queue.task_done()
                    except asyncio.QueueEmpty:  # pragma: no cover - 경합 방어
                        break
        else:
            for locale, queue in self._queues.items():
                task = self._tasks.get(locale)
                if task is not None and not task.done():
                    await queue.put(None)

        if self._tasks:
            results = await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) and not isinstance(
                    result, asyncio.CancelledError
                ):
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
        t_start = time.monotonic()
        try:
            pcm = await self._synthesize(job)
            t_synth = time.monotonic()
            duration_ms = await self._publish(job, pcm)
        except TtsException as exc:
            await self._dedupe.mark_failed(key)
            await self._emit_failed(job, exc.error_code)
            return
        except Exception as exc:  # noqa: BLE001
            await self._dedupe.mark_failed(key)
            await self._emit_failed(job, getattr(exc, "error_code", "AUDIO_PUBLISH_FAILED"))
            return

        t_published = time.monotonic()
        await self._dedupe.mark_done(key)
        await self._emit_completed(job, duration_ms=duration_ms)
        self._record_latency(job, t_start=t_start, t_synth=t_synth, t_published=t_published)

    def _record_latency(
        self,
        job: TtsJob,
        *,
        t_start: float,
        t_synth: float,
        t_published: float,
    ) -> None:
        """음성 경로 지연. e2eAudioMs 가 "발화 종료 → 학생 귀에 들어가기 시작"이다."""
        if not self._latency.enabled:
            return
        self._latency.record(
            "audio",
            sessionId=job.session_id,
            segmentId=job.segment_id,
            sequence=job.sequence,
            locale=job.locale,
            chars=len(job.text),
            ttsQueueMs=elapsed_ms(job.enqueued_at, t_start),
            ttsSynthMs=elapsed_ms(t_start, t_synth),
            ttsPublishMs=elapsed_ms(t_synth, t_published),
            e2eAudioMs=elapsed_ms(job.speech_end_at, t_published),
        )

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
