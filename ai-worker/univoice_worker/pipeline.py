"""Translation pipeline orchestration."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .dedupe import DedupeStore
from .latency import LatencyLog, default_log, elapsed_ms
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

DEFAULT_TRANSLATE_MAX_CONCURRENCY = 3


@dataclass
class _SegmentWork:
    """번역 태스크 하나와 그 계측 시각. emit 큐에 sequence 순서대로 쌓인다."""

    segment: SpeechSegment
    t_dequeue: float
    task: "asyncio.Task[dict[str, str]] | None" = None
    t_slot: float | None = None
    t_glossary: float | None = None
    t_rag: float | None = None
    t_translate: float | None = None
    translations: dict[str, str] = field(default_factory=dict)


EmitItem = _SegmentWork | None


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
        latency_log: LatencyLog | None = None,
        translate_max_concurrency: int = DEFAULT_TRANSLATE_MAX_CONCURRENCY,
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
        self._latency = latency_log or default_log()
        self._tts_queue = tts_queue or LocaleTtsQueue(
            locales=target_locales,
            tts=tts,
            publisher=publisher,
            on_audio_status=self._on_audio_status,
            dedupe_store=dedupe_store,
            queue_max_size=tts_queue_max_size,
            flush_timeout_sec=tts_flush_timeout_sec,
            latency_log=self._latency,
        )
        self._close_publisher_on_stop = close_publisher_on_stop
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=max(1, queue_max_size))
        self._enqueue_timeout = max(0.001, enqueue_timeout_ms / 1000)
        self._idle_check_interval = max(0.01, idle_check_interval_ms / 1000)
        self._flush_timeout = max(0.1, flush_timeout_sec)
        self._enqueue_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._consumer_task: asyncio.Task[None] | None = None
        self._emitter_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        # 세그먼트 dequeue → stt.final 발행은 컨슈머가 순서대로 하고, RAG + 번역은
        # 세마포어 상한 안에서 병렬로 돈다. 발행 순서는 emit 큐(FIFO)가 보장한다:
        # 컨슈머가 (segment, task) 를 sequence 순서로 넣고, emitter 가 하나씩 꺼내
        # 그 태스크를 기다린 뒤 발행한다. 한 STT final 에 문장이 여러 개 들어와도
        # 뒷문장이 앞문장 번역 완료를 기다렸다가 "시작"하지 않는다.
        self._translate_slots = asyncio.Semaphore(max(1, translate_max_concurrency))
        # 무제한이지만 실질 상한이 있다: 번역 중인 항목은 세마포어로, 번역이 끝난
        # 항목은 emitter 가 바로 소비한다(발행 단계는 TTS enqueue 타임아웃으로 유계).
        self._emit_q: asyncio.Queue[EmitItem] = asyncio.Queue()
        self._inflight: set[asyncio.Task[dict[str, str]]] = set()
        self._translate_kwargs = self._accepted_kwargs(
            getattr(translator, "translate", None), ("sequence", "glossary_hits")
        )
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
            self._ensure_workers()
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
            self._ensure_workers()
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

            # 세그먼트 큐 → 번역 태스크 → emit 큐 전체가 하나의 제한 시간을 나눠 쓴다.
            # 단계마다 따로 flush_timeout 을 주면 세션 정리 상한(10초)을 넘긴다.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._flush_timeout

            def remaining() -> float:
                return max(0.1, deadline - loop.time())

            # 컨슈머가 번역/RAG/TTS enqueue 어딘가에서 막혀 있으면 join 이 영원히
            # 안 끝난다. 세션 종료가 여기 매달리면 pubsub 루프까지 연쇄 정지하므로
            # 제한 시간 후 남은 세그먼트를 폐기한다.
            try:
                await asyncio.wait_for(self._queue.join(), timeout=remaining())
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
                        asyncio.shield(self._consumer_task), timeout=remaining()
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "[%s] 세그먼트 컨슈머가 종료되지 않아 취소한다", self._session_id
                    )
                    self._consumer_task.cancel()

            # 컨슈머가 멈췄으니 emit 큐에 더 들어올 것이 없다. 남은 번역 태스크와
            # 발행 대기분을 같은 기한 안에 드레인하고, 넘기면 폐기한다.
            await self._emit_q.put(None)
            if self._emitter_task is not None:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._emitter_task), timeout=remaining()
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "[%s] 번역/자막 발행 드레인이 %.0f초 내 끝나지 않아 "
                        "진행 중 %d건, 대기 %d건을 폐기한다",
                        self._session_id,
                        self._flush_timeout,
                        len(self._inflight),
                        self._emit_q.qsize(),
                    )
                    self._emitter_task.cancel()
            # 정상 종료면 비어 있다. 컨슈머가 취소된 경우 emit 큐에 오르지 못한
            # 고아 태스크가 남을 수 있어 항상 정리한다.
            self._discard_pending_emits()
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
            stt_received_at=draft.stt_received_at,
            speech_end_at=draft.speech_end_at,
        )

    def _ensure_workers(self) -> None:
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(
                self._consumer_loop(), name=f"segment-consumer-{self._session_id}"
            )
        if self._emitter_task is None or self._emitter_task.done():
            self._emitter_task = asyncio.create_task(
                self._emitter_loop(), name=f"segment-emitter-{self._session_id}"
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
        """stt.final 을 순서대로 발행하고, 번역 태스크를 띄워 emit 큐에 순서대로 싣는다."""
        try:
            await self._on_segment(segment)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] stt.final segment publish failed: %s", self._session_id, segment.segment_id)

        work = _SegmentWork(segment=segment, t_dequeue=time.monotonic())
        # 슬롯을 컨슈머에서 잡는다. 태스크 안에서 잡으면 태스크가 무한정 쌓이고,
        # 여기서 막히면 세그먼트 큐가 차서 기존 백프레셔(드롭) 정책이 그대로 동작한다.
        await self._translate_slots.acquire()
        work.t_slot = time.monotonic()
        try:
            task = asyncio.create_task(
                self._translate_work(work),
                name=f"segment-translate-{segment.segment_id}",
            )
        except BaseException:
            self._translate_slots.release()
            raise
        work.task = task
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        self._emit_q.put_nowait(work)

    async def _translate_work(self, work: _SegmentWork) -> dict[str, str]:
        """RAG + 번역. 슬롯은 번역이 끝나는 즉시 반납한다 (발행 대기까지 쥐지 않는다)."""
        segment = work.segment
        try:
            hits = self._translator.detect_glossary_hits(segment.text)
            work.t_glossary = time.monotonic()
            try:
                context = await self._rag.retrieve(segment.text, hits)
            except Exception:  # noqa: BLE001 - RAG 는 번역을 막지 않는 보조 단계다.
                logger.exception("[%s] RAG 조회 실패; 문맥 없이 진행", self._session_id)
                context = None
            work.t_rag = time.monotonic()

            # 번역 실패가 위로 올라가면 세그먼트가 통째로 사라진다. 빈 결과로 두면
            # _emit_locale 의 원문 폴백을 탄다.
            try:
                translations = await self._call_translate(segment, context, hits)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[%s] 번역 실패; 한국어 원문으로 폴백 (%s)",
                    self._session_id,
                    segment.segment_id,
                )
                translations = {}
            work.t_translate = time.monotonic()
            work.translations = translations or {}
            return work.translations
        finally:
            self._translate_slots.release()

    async def _call_translate(
        self,
        segment: SpeechSegment,
        context: str | None,
        hits: list[str],
    ) -> dict[str, str]:
        kwargs: dict[str, Any] = {}
        if "sequence" in self._translate_kwargs:
            # 병렬 번역에서도 직전 문맥(history)이 sequence 순서로 쌓이게 한다.
            kwargs["sequence"] = segment.sequence
        if "glossary_hits" in self._translate_kwargs:
            kwargs["glossary_hits"] = hits
        return await self._translator.translate(segment.text, context, **kwargs)

    async def _emitter_loop(self) -> None:
        while True:
            work = await self._emit_q.get()
            try:
                if work is None:
                    return
                await self._emit_work(work)
            except Exception:  # noqa: BLE001
                logger.exception("[%s] segment emit failed", self._session_id)
            finally:
                self._emit_q.task_done()

    async def _emit_work(self, work: _SegmentWork) -> None:
        segment = work.segment
        task = work.task
        if task is not None:
            # `await task` 는 태스크가 취소된 경우와 emitter 자신이 취소된 경우를
            # 구분할 수 없다. wait 로 끝나기만 기다리고 결과는 따로 꺼낸다.
            await asyncio.wait({task})
            if task.cancelled():
                translations: dict[str, str] = {}
            elif task.exception() is not None:
                logger.error(
                    "[%s] 번역 태스크 실패; 한국어 원문으로 폴백 (%s): %r",
                    self._session_id,
                    segment.segment_id,
                    task.exception(),
                )
                translations = {}
            else:
                translations = task.result() or {}
        else:  # pragma: no cover - 방어
            translations = {}
        t_emit_start = time.monotonic()
        await asyncio.gather(
            *(
                self._safe_emit_locale(loc, translations.get(loc), segment, missing=loc not in translations)
                for loc in self._locales
            )
        )
        t_emit = time.monotonic()
        self._record_segment_latency(
            work,
            t_emit_start=t_emit_start,
            t_emit=t_emit,
        )
        await self._safe_emit_transcript(segment, translations)

    def _discard_pending_emits(self) -> None:
        for task in list(self._inflight):
            task.cancel()
        while not self._emit_q.empty():
            try:
                work = self._emit_q.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - 경합 방어
                break
            if work is not None and work.task is not None:
                work.task.cancel()
            self._emit_q.task_done()

    @staticmethod
    def _accepted_kwargs(func: Any, names: tuple[str, ...]) -> frozenset[str]:
        """번역기가 받는 선택 키워드만 추린다. 테스트 fake 등 구형 시그니처 호환용."""
        if func is None:
            return frozenset()
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):  # pragma: no cover - 내장/C 콜러블
            return frozenset()
        params = signature.parameters
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return frozenset(names)
        return frozenset(name for name in names if name in params)

    def _record_segment_latency(
        self,
        work: _SegmentWork,
        *,
        t_emit_start: float,
        t_emit: float,
    ) -> None:
        """자막 경로 지연을 한 줄로 남긴다. 계측이 꺼져 있으면 즉시 반환한다.

        emit_ms 는 자막 발행 + TTS 큐 적재를 함께 포함한다. 정상 상태에서는 큐
        적재가 1ms 미만이지만, 백프레셔가 걸리면 여기서 드러난다.
        """
        if not self._latency.enabled:
            return
        segment = work.segment
        # 번역이 예외로 끝나 시각이 비었으면 발행 직전 시각으로 메운다.
        t_glossary = work.t_glossary or work.t_slot or t_emit_start
        t_rag = work.t_rag or t_glossary
        t_translate = work.t_translate or t_emit_start
        self._latency.record(
            "caption",
            sessionId=self._session_id,
            segmentId=segment.segment_id,
            sequence=segment.sequence,
            chars=len(segment.text),
            locales=len(self._locales),
            # 구간별
            sttMs=elapsed_ms(segment.speech_end_at, segment.stt_received_at),
            segmentMs=elapsed_ms(segment.stt_received_at, segment.ended_at),
            queueMs=elapsed_ms(segment.ended_at, work.t_dequeue),
            # 번역 동시성 상한에 걸려 슬롯을 기다린 시간
            translateSlotMs=elapsed_ms(work.t_dequeue, work.t_slot),
            glossaryMs=elapsed_ms(work.t_slot, t_glossary),
            # RAG 가 꺼져 있으면 0 을 기록하지 않는다. 0ms 로 남으면 "RAG 가 공짜"로
            # 읽히지만 실제로는 호출 자체가 없었던 것이다 (None → 리포트에서 제외).
            ragMs=elapsed_ms(t_glossary, t_rag)
            if getattr(self._rag, "latency_enabled", True)
            else None,
            translateMs=elapsed_ms(t_rag, t_translate),
            # 번역은 끝났지만 앞 세그먼트 발행을 기다린 시간 (순서 보장 비용)
            orderWaitMs=elapsed_ms(t_translate, t_emit_start),
            emitMs=elapsed_ms(t_emit_start, t_emit),
            # 누적
            workerMs=elapsed_ms(segment.stt_received_at, t_emit),
            e2eCaptionMs=elapsed_ms(segment.speech_end_at, t_emit),
        )

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
                speech_end_at=segment.speech_end_at,
                enqueued_at=time.monotonic(),
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
