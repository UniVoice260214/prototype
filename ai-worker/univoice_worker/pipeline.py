"""Translation pipeline orchestration."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from .dedupe import DedupeStore
from .models import AudioStatus, SpeechSegment, SttFinalResult, TtsJob
from .rag import RagClient
from .segmenter import SegmentDraft, Segmenter
from .tts_queue import LocaleTtsQueue

logger = logging.getLogger(__name__)

SubtitleSink = Callable[[str, str, SpeechSegment, bool], Awaitable[None]]
AudioStatusSink = Callable[[AudioStatus], Awaitable[None]]
SegmentSink = Callable[[SpeechSegment], Awaitable[None]]
QueueItem = SpeechSegment | None


async def _noop_segment_sink(segment: SpeechSegment) -> None:
    return None


async def _noop_audio_status(status: AudioStatus) -> None:
    return None


class TranslationPipeline:
    def __init__(
        self,
        session_id: str,
        target_locales: list[str],
        segmenter: Segmenter,
        rag: RagClient,
        translator: Any,
        tts: Any,
        publisher: Any,
        on_subtitle: SubtitleSink,
        on_segment: SegmentSink | None = None,
        *,
        on_audio_status: AudioStatusSink | None = None,
        tts_queue: LocaleTtsQueue | None = None,
        dedupe_store: DedupeStore | None = None,
        queue_max_size: int = 100,
        tts_queue_max_size: int = 100,
        enqueue_timeout_ms: int = 250,
        idle_check_interval_ms: int = 100,
        close_publisher_on_stop: bool = True,
    ) -> None:
        self._session_id = session_id
        self._locales = target_locales
        self._segmenter = segmenter
        self._rag = rag
        self._translator = translator
        self._tts = tts
        self._publisher = publisher
        self._on_subtitle = on_subtitle
        self._on_segment = on_segment or _noop_segment_sink
        self._on_audio_status = on_audio_status or _noop_audio_status
        self._tts_queue = tts_queue or LocaleTtsQueue(
            locales=target_locales,
            tts=tts,
            publisher=publisher,
            on_audio_status=self._on_audio_status,
            dedupe_store=dedupe_store,
            queue_max_size=tts_queue_max_size,
        )
        self._close_publisher_on_stop = close_publisher_on_stop
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=max(1, queue_max_size))
        self._enqueue_timeout = max(0.001, enqueue_timeout_ms / 1000)
        self._idle_check_interval = max(0.01, idle_check_interval_ms / 1000)
        self._enqueue_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._consumer_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._stopped = False
        self._next_sequence = 1
        # 워커가 재기동되어도 이전 실행의 segment_id와 겹치지 않도록 실행마다 고유 id를 붙인다.
        # (Redis TTS dedupe TTL이 1시간이라 segment_id가 seg-000001부터 재사용되면 새 발화가
        #  이전 실행의 완료/처리중 키와 충돌해 오진단·스킵된다.)
        self._run_id = uuid.uuid4().hex[:8]

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._consumer_task is not None and not self._consumer_task.done():
                return
            self._stopping = False
            self._stopped = False
            await self._tts_queue.start()
            self._consumer_task = asyncio.create_task(
                self._consumer_loop(), name=f"segment-consumer-{self._session_id}"
            )
            self._idle_task = asyncio.create_task(
                self._idle_flush_loop(), name=f"segment-idle-flush-{self._session_id}"
            )

    async def enqueue_stt_final(self, final_result: SttFinalResult | str) -> None:
        """Add an STT final to the segmenter and enqueue emitted segments in source order."""
        await self.start()
        if self._stopping:
            logger.warning("[%s] dropping STT final after pipeline stop started", self._session_id)
            return
        async with self._enqueue_lock:
            for draft in self._segmenter.push(final_result):
                await self._enqueue_draft(draft, allow_drop=True)

    async def handle_final(self, ko_text: str) -> None:
        """Backward-compatible alias for older callers."""
        await self.enqueue_stt_final(ko_text)

    async def flush_and_stop(self) -> None:
        """Flush segmenter, segment queue, TTS queues, and publisher. Safe to call repeatedly."""
        async with self._lifecycle_lock:
            if self._stopped:
                return
            await self._tts_queue.start()
            if self._consumer_task is None or self._consumer_task.done():
                self._consumer_task = asyncio.create_task(
                    self._consumer_loop(), name=f"segment-consumer-{self._session_id}"
                )
            self._stopping = True
            if self._idle_task is not None:
                self._idle_task.cancel()
                try:
                    await self._idle_task
                except asyncio.CancelledError:
                    pass

            async with self._enqueue_lock:
                for draft in self._segmenter.flush():
                    await self._enqueue_draft(draft, allow_drop=False)

            await self._queue.join()
            await self._queue.put(None)
            if self._consumer_task is not None:
                await self._consumer_task
            await self._tts_queue.flush_and_stop()
            await self._close_publisher()
            self._stopped = True

    async def flush(self) -> None:
        """Backward-compatible alias for older callers."""
        await self.flush_and_stop()

    async def _idle_flush_loop(self) -> None:
        try:
            while not self._stopping:
                await asyncio.sleep(self._idle_check_interval)
                async with self._enqueue_lock:
                    for draft in self._segmenter.pop_idle():
                        await self._enqueue_draft(draft, allow_drop=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[%s] segment idle flush loop failed", self._session_id)

    async def _enqueue_draft(self, draft: SegmentDraft, *, allow_drop: bool) -> bool:
        segment = self._build_segment(draft)
        try:
            if allow_drop:
                await asyncio.wait_for(self._queue.put(segment), timeout=self._enqueue_timeout)
            else:
                await self._queue.put(segment)
        except asyncio.TimeoutError:
            logger.error(
                "[%s] segment queue full for %.3fs; dropping segment %s by backpressure policy",
                self._session_id,
                self._enqueue_timeout,
                segment.segment_id,
            )
            return False
        self._next_sequence += 1
        return True

    def _build_segment(self, draft: SegmentDraft) -> SpeechSegment:
        sequence = self._next_sequence
        return SpeechSegment(
            session_id=self._session_id,
            segment_id=f"{self._session_id}-{self._run_id}-seg-{sequence:06d}",
            sequence=sequence,
            text=draft.text,
            stt_confidence=draft.stt_confidence,
            started_at=draft.started_at,
            ended_at=draft.ended_at,
        )

    async def _consumer_loop(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                await self._handle_segment(item)
            except Exception:  # noqa: BLE001
                logger.exception("[%s] segment processing failed", self._session_id)
            finally:
                self._queue.task_done()

    async def _handle_segment(self, segment: SpeechSegment) -> None:
        try:
            await self._on_segment(segment)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] stt.final segment publish failed: %s", self._session_id, segment.segment_id)

        await self._process_segment(segment)

    async def _process_segment(self, segment: SpeechSegment) -> None:
        hits = self._translator.detect_glossary_hits(segment.text)
        context = await self._rag.retrieve(segment.text, hits)
        translations = await self._translator.translate(segment.text, context)
        translations = translations or {}
        await asyncio.gather(
            *(
                self._safe_emit_locale(loc, translations.get(loc), segment, missing=loc not in translations)
                for loc in self._locales
            )
        )

    async def _safe_emit_locale(
        self,
        locale: str,
        text: str | None,
        segment: SpeechSegment,
        *,
        missing: bool,
    ) -> None:
        try:
            await self._emit_locale(locale, text, segment, missing=missing)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] locale processing failed (%s, %s)",
                self._session_id,
                segment.segment_id,
                locale,
            )
            await self._emit_audio_failed(segment, locale, "LOCALE_DELIVERY_FAILED")

    async def _emit_locale(
        self,
        locale: str,
        text: str | None,
        segment: SpeechSegment,
        *,
        missing: bool,
    ) -> None:
        if missing:
            await self._emit_audio_failed(segment, locale, "TRANSLATION_MISSING")
            return
        if text is None or not text.strip():
            await self._emit_audio_failed(segment, locale, "TRANSLATION_EMPTY")
            return

        try:
            await self._on_subtitle(locale, text, segment, True)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] caption publish failed before TTS enqueue (%s, %s)",
                self._session_id,
                segment.segment_id,
                locale,
            )

        await self._tts_queue.enqueue(
            TtsJob(
                session_id=segment.session_id,
                segment_id=segment.segment_id,
                sequence=segment.sequence,
                locale=locale,
                text=text,
            )
        )

    async def _emit_audio_failed(self, segment: SpeechSegment, locale: str, error_code: str) -> None:
        status = AudioStatus(
            type="audio.failed",
            session_id=segment.session_id,
            segment_id=segment.segment_id,
            sequence=segment.sequence,
            locale=locale,
            duration_ms=None,
            error_code=error_code,
            timestamp=time.time(),
        )
        try:
            result = self._on_audio_status(status)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] audio status publish failed (%s, %s)",
                self._session_id,
                segment.segment_id,
                locale,
            )

    async def _close_publisher(self) -> None:
        if not self._close_publisher_on_stop:
            return
        close = getattr(self._publisher, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
