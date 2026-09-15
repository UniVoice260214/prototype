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

SubtitleSink = Callable[..., Awaitable[None]]
AudioStatusSink = Callable[[AudioStatus], Awaitable[None]]
SegmentSink = Callable[[SpeechSegment], Awaitable[None]]
# 세그먼트 하나의 최종 전달 결과(로케일별 자막 텍스트 + 폴백 여부).
# DB 저장 등 후처리용이며, 실패해도 실시간 전달을 막으면 안 된다.
TranscriptSink = Callable[[SpeechSegment, dict[str, dict[str, Any]]], Awaitable[None]]
# STT 원문 → (교정문, 치환 건수). lexicon.MajorLexicon.correct_for_display 시그니처.
Corrector = Callable[[str], tuple[str, int]]
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
        corrector: Corrector | None = None,
        on_audio_status: AudioStatusSink | None = None,
        on_transcript: TranscriptSink | None = None,
        tts_queue: LocaleTtsQueue | None = None,
        dedupe_store: DedupeStore | None = None,
        queue_max_size: int = 100,
        tts_queue_max_size: int = 100,
        enqueue_timeout_ms: int = 250,
        idle_check_interval_ms: int = 100,
        flush_timeout_sec: float = 5.0,
        tts_flush_timeout_sec: float = 3.0,
        sequence_start: int = 1,
        close_publisher_on_stop: bool = True,
    ) -> None:
        self._session_id = session_id
        self._locales = target_locales
        self._segmenter = segmenter
        self._rag = rag
        self._translator = translator
        self._tts = tts
        self._publisher = publisher
        self._corrector = corrector
        self._on_subtitle = on_subtitle
        self._subtitle_accepts_fallback = self._sink_accepts_fallback(on_subtitle)
        self._on_segment = on_segment or _noop_segment_sink
        self._on_audio_status = on_audio_status or _noop_audio_status
        self._on_transcript = on_transcript
        self._tts_queue = tts_queue or LocaleTtsQueue(
            locales=target_locales,
            tts=tts,
            publisher=publisher,
            on_audio_status=self._on_audio_status,
            dedupe_store=dedupe_store,
            queue_max_size=tts_queue_max_size,
            flush_timeout_sec=tts_flush_timeout_sec,
        )
        self._close_publisher_on_stop = close_publisher_on_stop
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=max(1, queue_max_size))
        self._enqueue_timeout = max(0.001, enqueue_timeout_ms / 1000)
        self._idle_check_interval = max(0.01, idle_check_interval_ms / 1000)
        self._flush_timeout = max(0.1, flush_timeout_sec)
        self._enqueue_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._consumer_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._stopped = False
        # 워커 런 식별자. segment_id 에 포함되어 (1) 워커 재기동 시 이전 런과의
        # TTS dedupe 키 충돌, (2) transcript_segments 의 segmentId 덮어쓰기를 막는다.
        self._run_id = uuid.uuid4().hex[:8]
        self._next_sequence = max(1, sequence_start)

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

            # 컨슈머가 번역/RAG/TTS enqueue 어딘가에서 막혀 있으면 join 이 영원히
            # 안 끝난다. 세션 종료가 여기 매달리면 pubsub 루프까지 연쇄 정지하므로
            # 제한 시간 후 남은 세그먼트를 폐기한다.
            try:
                await asyncio.wait_for(self._queue.join(), timeout=self._flush_timeout)
            except asyncio.TimeoutError:
                discarded = self._queue.qsize()
                logger.warning(
                    "[%s] 세그먼트 flush 가 %.0f초 내 끝나지 않아 잔여 %d건을 폐기한다",
                    self._session_id,
                    self._flush_timeout,
                    discarded,
                )
                while not self._queue.empty():
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except asyncio.QueueEmpty:  # pragma: no cover - 경합 방어
                        break
            await self._queue.put(None)
            if self._consumer_task is not None:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._consumer_task), timeout=self._flush_timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "[%s] 세그먼트 컨슈머가 종료되지 않아 취소한다", self._session_id
                    )
                    self._consumer_task.cancel()
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
        text = draft.text
        raw_text: str | None = None

        # 여기 한 곳에서 교정하면 자막(sourceKo), 번역 입력, 교수 화면 확정 자막이
        # 모두 SpeechSegment.text 를 통해 같은 교정 결과를 쓰게 된다.
        if self._corrector is not None:
            try:
                corrected, fixed = self._corrector(text)
            except Exception:  # noqa: BLE001 - 교정 실패가 자막을 막으면 안 된다.
                logger.exception("[%s] lexicon 교정 실패; 원문 유지", self._session_id)
            else:
                if fixed:
                    logger.info(
                        "[%s] lexicon 교정 %d건: %r → %r",
                        self._session_id,
                        fixed,
                        text,
                        corrected,
                    )
                    raw_text = text
                    text = corrected

        return SpeechSegment(
            session_id=self._session_id,
            segment_id=f"{self._session_id}-{self._run_id}-seg-{sequence:06d}",
            sequence=sequence,
            text=text,
            stt_confidence=draft.stt_confidence,
            started_at=draft.started_at,
            ended_at=draft.ended_at,
            raw_text=raw_text,
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
        try:
            context = await self._rag.retrieve(segment.text, hits)
        except Exception:  # noqa: BLE001 - RAG 는 번역을 막지 않는 보조 단계다.
            logger.exception("[%s] RAG 조회 실패; 문맥 없이 진행", self._session_id)
            context = None

        # 번역 실패로 예외가 위로 올라가면 _consumer_loop 가 삼켜 세그먼트가 통째로
        # 사라진다. 여기서 잡아 빈 결과로 두면 아래 _emit_locale 의 원문 폴백을 탄다.
        try:
            translations = await self._translator.translate(segment.text, context)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] 번역 실패; 한국어 원문으로 폴백 (%s)",
                self._session_id,
                segment.segment_id,
            )
            translations = {}
        translations = translations or {}
        await asyncio.gather(
            *(
                self._safe_emit_locale(loc, translations.get(loc), segment, missing=loc not in translations)
                for loc in self._locales
            )
        )
        await self._safe_emit_transcript(segment, translations)

    async def _safe_emit_transcript(
        self,
        segment: SpeechSegment,
        translations: dict[str, str],
    ) -> None:
        """학생에게 실제 전달된 모양(폴백 포함)을 저장 sink 로 넘긴다."""
        if self._on_transcript is None:
            return
        entries: dict[str, dict[str, Any]] = {}
        for locale in self._locales:
            text = (translations.get(locale) or "").strip()
            if text:
                entries[locale] = {"text": text, "isFallback": False}
            else:
                fallback = (segment.text or "").strip()
                entries[locale] = {"text": fallback, "isFallback": True}
        try:
            await self._on_transcript(segment, entries)
        except Exception:  # noqa: BLE001 - 저장 실패가 실시간 전달을 막으면 안 된다.
            logger.exception(
                "[%s] transcript sink failed (%s)", self._session_id, segment.segment_id
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
        if missing or text is None or not text.strip():
            # 번역이 없으면 예전에는 자막을 아예 안 보내 문장이 통째로 사라졌다.
            # 학생 입장에서는 앞뒤가 안 맞는 자막이 되므로, 한국어 원문이라도 내보낸다.
            error_code = "TRANSLATION_MISSING" if missing else "TRANSLATION_EMPTY"
            fallback = (segment.text or "").strip()
            if fallback:
                await self._emit_subtitle(locale, fallback, segment, is_fallback=True)
            await self._emit_audio_failed(segment, locale, error_code)
            return

        await self._emit_subtitle(locale, text, segment, is_fallback=False)

        await self._tts_queue.enqueue(
            TtsJob(
                session_id=segment.session_id,
                segment_id=segment.segment_id,
                sequence=segment.sequence,
                locale=locale,
                text=text,
            )
        )

    async def _emit_subtitle(
        self,
        locale: str,
        text: str,
        segment: SpeechSegment,
        *,
        is_fallback: bool,
    ) -> None:
        """자막을 발행한다. 실패해도 TTS 적재는 계속되어야 한다."""
        try:
            if self._subtitle_accepts_fallback:
                await self._on_subtitle(locale, text, segment, True, is_fallback=is_fallback)
            else:
                await self._on_subtitle(locale, text, segment, True)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] caption publish failed (%s, %s, fallback=%s)",
                self._session_id,
                segment.segment_id,
                locale,
                is_fallback,
            )

    @staticmethod
    def _sink_accepts_fallback(sink: SubtitleSink) -> bool:
        """자막 sink 가 is_fallback 키워드를 받는지 한 번만 판정한다.

        구형 sink(위치 인자 4개)와의 호환을 위한 것이다.
        """
        try:
            signature = inspect.signature(sink)
        except (TypeError, ValueError):  # pragma: no cover - 내장/C 콜러블
            return False
        for parameter in signature.parameters.values():
            if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                return True
            if parameter.name == "is_fallback":
                return True
        return False

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
