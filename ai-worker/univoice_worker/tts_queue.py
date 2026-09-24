"""Per-locale TTS delivery queues.

한 로케일의 job 은 한 컨슈머가 sequence 순서대로 "재생(publish)"한다 — 같은 로케일
안에서 오디오 발행이 겹치지 않는다는 보장은 그대로다. 달라진 점:

- 합성(producer)과 발행(consumer)을 분리했다. 스트리밍 합성기(stream_job)면
  청크가 나오는 즉시 push 한다 — 합성 완료를 기다리지 않는다.
- 앞 job 의 첫 청크를 push 하는 시점에 큐의 다음 job 을 미리 꺼내 합성을
  시작한다(선합성). 발행은 여전히 앞 job 이 끝난 뒤에만 시작한다.
- 스트리밍을 지원하지 않는 합성기(테스트 fake 등)는 기존처럼 한 번에 합성해
  한 번에 push 한다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .dedupe import DedupeStore, InMemoryDedupeStore, tts_dedupe_key
from .latency import LatencyLog, default_log, elapsed_ms
from .models import AudioStatus, TtsException, TtsJob, TtsResult
from .tts import SAMPLE_RATE

logger = logging.getLogger(__name__)

AudioStatusSink = Callable[[AudioStatus], Awaitable[None]]
QueueItem = TtsJob | None

# LiveKit 오디오 프레임(10ms) 바이트 수. push 단위를 이 배수로 맞춰야 publisher 가
# 청크마다 마지막 프레임을 0 으로 패딩해 문장 중간에 무음 틱이 끼지 않는다.
FRAME_BYTES = SAMPLE_RATE // 100 * 2
_END = object()


@dataclass
class _PreparedJob:
    """dedupe 를 통과하고 합성이 시작된(또는 건너뛸) job."""

    job: TtsJob
    key: str
    skip: str | None = None  # "done" | "locked"
    streaming: bool = False
    chunks: "asyncio.Queue[Any]" = field(default_factory=asyncio.Queue)
    producer: "asyncio.Task[None] | None" = None
    t_start: float = 0.0
    t_first_chunk: float | None = None
    t_synth: float | None = None

    def cancel(self) -> None:
        if self.producer is not None and not self.producer.done():
            self.producer.cancel()


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
        prefetch: bool = True,
    ) -> None:
        self._prefetch = prefetch
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
        # 선합성으로 미리 꺼낸 다음 항목. 큐에서 이미 get 했으므로 task_done 을
        # 정확히 한 번 해줘야 한다 (안 하면 다음 flush 의 join 이 매달린다).
        has_next = False
        next_item: QueueItem = None
        next_task: asyncio.Task[_PreparedJob] | None = None

        def prefetch() -> None:
            nonlocal has_next, next_item, next_task
            if not self._prefetch or has_next or queue.empty():
                return
            try:
                next_item = queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - 경합 방어
                return
            has_next = True
            if next_item is not None:
                next_task = asyncio.create_task(
                    self._prepare(next_item), name=f"tts-prefetch-{locale}"
                )

        try:
            while True:
                if has_next:
                    item, prepare_task = next_item, next_task
                    has_next, next_item, next_task = False, None, None
                else:
                    item, prepare_task = await queue.get(), None
                try:
                    if item is None:
                        return
                    prepared = await (prepare_task or self._prepare(item))
                    await self._play(prepared, on_playback_start=prefetch)
                except Exception:  # noqa: BLE001
                    logger.exception("TTS job handling failed unexpectedly (locale=%s)", locale)
                finally:
                    queue.task_done()
        finally:
            # 종료 폐기(cancel) 경로: 미리 꺼낸 항목의 합성을 멈추고 회계를 맞춘다.
            if has_next:
                if next_task is not None:
                    if next_task.done() and not next_task.cancelled() and next_task.exception() is None:
                        next_task.result().cancel()
                    else:
                        next_task.cancel()
                queue.task_done()

    async def _prepare(self, job: TtsJob) -> _PreparedJob:
        """dedupe 확인 후 합성을 시작한다. 발행은 하지 않는다."""
        key = tts_dedupe_key(job.session_id, job.segment_id, job.locale)
        if await self._dedupe.is_done(key):
            return _PreparedJob(job=job, key=key, skip="done")
        if not await self._dedupe.try_acquire(key):
            skip = "done" if await self._dedupe.is_done(key) else "locked"
            return _PreparedJob(job=job, key=key, skip=skip)

        prepared = _PreparedJob(
            job=job,
            key=key,
            streaming=self._supports_streaming(),
            t_start=time.monotonic(),
        )
        prepared.producer = asyncio.create_task(
            self._produce(prepared), name=f"tts-synth-{job.locale}-{job.sequence}"
        )
        return prepared

    def _supports_streaming(self) -> bool:
        return hasattr(self._tts, "stream_job") and bool(
            getattr(self._tts, "streaming_supported", False)
        )

    async def _produce(self, prepared: _PreparedJob) -> None:
        """합성 결과를 청크 큐로 흘린다. 끝은 _END, 실패는 예외 객체로 알린다."""
        job = prepared.job

        def on_chunk(chunk: bytes) -> None:
            if not chunk:
                return
            if not isinstance(chunk, (bytes, bytearray)):
                raise TtsException(
                    "TTS_INVALID_RESULT",
                    f"TTS stream returned unsupported chunk type {type(chunk).__name__}",
                    retryable=False,
                )
            if prepared.t_first_chunk is None:
                prepared.t_first_chunk = time.monotonic()
            prepared.chunks.put_nowait(bytes(chunk))

        try:
            if prepared.streaming:
                if not job.text or not job.text.strip():
                    raise TtsException("TTS_EMPTY_TEXT", "TTS text is empty", retryable=False)
                await self._tts.stream_job(job, on_chunk)
                if prepared.t_first_chunk is None:
                    raise TtsException(
                        "TTS_EMPTY_AUDIO", "TTS stream produced no audio", retryable=True
                    )
            else:
                on_chunk(await self._synthesize(job))
        except asyncio.CancelledError:
            prepared.chunks.put_nowait(
                TtsException("TTS_CANCELLED", "TTS synthesis cancelled", retryable=True)
            )
            raise
        except Exception as exc:  # noqa: BLE001 - 발행 쪽에서 기존 규칙대로 분류한다.
            prepared.chunks.put_nowait(exc)
        else:
            prepared.chunks.put_nowait(_END)
        finally:
            prepared.t_synth = time.monotonic()

    async def _play(
        self,
        prepared: _PreparedJob,
        *,
        on_playback_start: Callable[[], None] | None = None,
    ) -> None:
        """청크가 도착하는 대로 순서대로 push 한다. 이 로케일에서 동시에 하나만 돈다."""
        job = prepared.job
        if prepared.skip == "done":
            await self._emit_completed(job, duration_ms=0)
            return
        if prepared.skip == "locked":
            await self._emit_failed(job, "TTS_DEDUPE_LOCKED")
            return

        await self._emit_started(job)
        pending = bytearray()
        duration_ms = 0
        t_first_push: float | None = None
        try:
            while True:
                item = await prepared.chunks.get()
                if item is _END:
                    break
                if isinstance(item, BaseException):
                    raise item
                if prepared.streaming:
                    pending += item
                    aligned = len(pending) - len(pending) % FRAME_BYTES
                    if not aligned:
                        continue
                    pcm = bytes(pending[:aligned])
                    del pending[:aligned]
                else:
                    pcm = item
                if t_first_push is None:
                    t_first_push = time.monotonic()
                    # 재생이 시작됐다 — 이 동안 다음 job 합성을 미리 시작한다.
                    if on_playback_start is not None:
                        on_playback_start()
                duration_ms += await self._publish(job, pcm)
            if pending:
                if t_first_push is None:
                    t_first_push = time.monotonic()
                    if on_playback_start is not None:
                        on_playback_start()
                duration_ms += await self._publish(job, bytes(pending))
        except TtsException as exc:
            prepared.cancel()
            await self._dedupe.mark_failed(prepared.key)
            await self._emit_failed(job, exc.error_code)
            return
        except Exception as exc:  # noqa: BLE001
            prepared.cancel()
            await self._dedupe.mark_failed(prepared.key)
            await self._emit_failed(job, getattr(exc, "error_code", "AUDIO_PUBLISH_FAILED"))
            return
        finally:
            # 취소(종료 폐기) 시 합성도 멈춘다. 정상 경로에서는 이미 끝나 있다.
            prepared.cancel()

        t_published = time.monotonic()
        await self._dedupe.mark_done(prepared.key)
        await self._emit_completed(job, duration_ms=duration_ms)
        self._record_latency(prepared, t_first_push=t_first_push, t_published=t_published)

    async def _handle_job(self, job: TtsJob) -> None:
        """job 하나를 선합성 없이 처리한다 (직접 호출용)."""
        await self._play(await self._prepare(job))

    def _record_latency(
        self,
        prepared: _PreparedJob,
        *,
        t_first_push: float | None,
        t_published: float,
    ) -> None:
        """음성 경로 지연.

        e2eFirstAudioMs 가 "발화 종료 → 학생 귀에 들어가기 시작"이고,
        e2eAudioMs 는 기존 정의(오디오 push 완료)를 유지한다.
        """
        if not self._latency.enabled:
            return
        job = prepared.job
        t_start = prepared.t_start
        t_synth = prepared.t_synth or t_published
        self._latency.record(
            "audio",
            sessionId=job.session_id,
            segmentId=job.segment_id,
            sequence=job.sequence,
            locale=job.locale,
            chars=len(job.text),
            streaming=prepared.streaming,
            ttsQueueMs=elapsed_ms(job.enqueued_at, t_start),
            ttsSynthMs=elapsed_ms(t_start, t_synth),
            # 스트리밍 합성: 합성 시작 → 첫 청크
            ttsFirstChunkMs=elapsed_ms(t_start, prepared.t_first_chunk),
            # 첫 청크는 준비됐지만 앞 job 재생이 끝나길 기다린 시간 (선합성 효과)
            ttsPlayWaitMs=elapsed_ms(prepared.t_first_chunk, t_first_push),
            ttsPublishMs=elapsed_ms(t_synth, t_published)
            if t_published >= t_synth
            else 0.0,
            e2eFirstAudioMs=elapsed_ms(job.speech_end_at, t_first_push),
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
