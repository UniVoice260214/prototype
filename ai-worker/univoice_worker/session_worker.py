"""Session worker for one UniVoice LiveKit room."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import Any, Awaitable, Callable, Coroutine

try:  # pragma: no cover - LiveKit is runtime-provided; tests inject fakes.
    from livekit import api, rtc
except ImportError:  # pragma: no cover
    api = None  # type: ignore[assignment]
    rtc = None  # type: ignore[assignment]

from .audio_publisher import LocaleAudioPublisher
from .config import WorkerConfig
from .dedupe import InMemoryDedupeStore, RedisDedupeStore
from .glossary import GlossaryEntry
from .lexicon import MajorLexicon, build_phrase_list
from .models import AudioStatus, SpeechSegment, SttFinalResult, SttPartialResult, audio_status_payload
from .pipeline import TranslationPipeline
from .rag import NoOpRagClient, RagClient
from .segmenter import Segmenter
from .stt import AzureStreamingStt, SttError, SttTuning
from .translator import Translator
from .tts import TtsSynthesizer
from .worker_status import NoOpWorkerStatusStore, WorkerStatusStore

logger = logging.getLogger(__name__)

PROFESSOR_IDENTITY_PREFIX = "professor-"
STT_TOPIC = "stt"
CAPTION_TOPIC = "caption"
AUDIO_STATUS_TOPIC = "audio-status"
# NestJS TranscriptSubscriber 가 구독하는 자막 저장 채널 (events.types.ts 와 동기화).
TRANSCRIPTS_SEGMENT_CHANNEL = "transcripts.segment"

SttFactory = Callable[
    [Callable[[SttPartialResult], None], Callable[[SttFinalResult], None], Callable[[SttError], None]],
    Any,
]
AudioStreamFactory = Callable[[Any], Any]


class SessionWorker:
    def __init__(
        self,
        config: WorkerConfig,
        session_id: str,
        room_name: str,
        target_locales: list[str],
        glossary: list[GlossaryEntry],
        rag: RagClient | None = None,
        *,
        lexicon: MajorLexicon | None = None,
        status_store: WorkerStatusStore | None = None,
        transcript_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        sequence_start: int = 1,
        # preflight_rag() 결과: ready | off | unreachable | no-index. 교수 화면 진단값으로 나간다.
        rag_status: str = "off",
        room: Any | None = None,
        stt_factory: SttFactory | None = None,
        audio_stream_factory: AudioStreamFactory | None = None,
        publisher_factory: Callable[[Any, list[str]], Any] = LocaleAudioPublisher,
        pipeline_factory: Callable[..., Any] = TranslationPipeline,
    ) -> None:
        self._config = config
        self._session_id = session_id
        self._room_name = room_name
        self._target_locales = target_locales
        self._glossary = glossary
        self._lexicon = lexicon
        self._rag = rag or NoOpRagClient()
        self._rag_status = rag_status
        self._loop = asyncio.get_running_loop()

        # PhraseList 는 세션 시작 시 한 번만 합성해 두고 STT 재생성 때마다 재사용한다.
        self._phrase_list, phrase_stats = build_phrase_list(
            glossary_terms=[g.term for g in glossary],
            lexicon=lexicon,
            max_items=config.stt_phrase_list_max_items,
            max_chars=config.stt_phrase_list_max_chars,
        )
        logger.info(
            "[%s] STT phrase list: glossary=%d lexicon=%s(%d패턴) merged=%d dropped=%d "
            "chars=%d weight=%.1f",
            session_id,
            phrase_stats["glossary"],
            lexicon.major if lexicon is not None else "NONE",
            phrase_stats["lexicon"],
            phrase_stats["merged"],
            phrase_stats["dropped"],
            phrase_stats["chars"],
            config.stt_phrase_list_weight,
        )
        if not self._phrase_list:
            logger.error(
                "[%s] STT phrase list 가 비어 있다 — 전공 용어 인식이 사실상 불가능하다. "
                "glossary 시드와 rag_assets/lexicon_*.json 을 확인하라.",
                session_id,
            )
        self._room = room if room is not None else self._create_room()
        self._status_store = status_store or NoOpWorkerStatusStore()
        self._transcript_publisher = transcript_publisher
        self._sequence_start = max(1, sequence_start)
        self._stt_factory = stt_factory
        self._audio_stream_factory = audio_stream_factory
        self._publisher_factory = publisher_factory
        self._pipeline_factory = pipeline_factory

        self._stt: Any | None = None
        self._audio_task: asyncio.Task[None] | None = None
        self._publisher: Any | None = None
        self._pipeline: Any | None = None
        self._current_track: Any | None = None
        self._current_track_key: str | None = None
        self._current_professor_identity: str | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._stt_reconnect_attempts = 0

        self._stopped = asyncio.Event()
        self._cleanup_lock = asyncio.Lock()
        self._attach_lock = asyncio.Lock()
        self._cleaned_up = False
        self._stopping = False
        self._failed = False

    async def run(self) -> None:
        await self._set_worker_status("starting")
        try:
            token = self._build_token()
            self._register_room_handlers()

            await self._room.connect(self._config.livekit_url, token)
            logger.info("[%s] joined room '%s'", self._session_id, self._room_name)

            self._publisher = self._publisher_factory(self._room, self._target_locales)
            await self._publisher.start()

            translator = Translator(
                self._config, self._target_locales, self._glossary, self._lexicon
            )
            tts = TtsSynthesizer(
                self._config.azure_speech_key,
                self._config.azure_speech_region,
                self._config.voice_map,
                timeout_sec=self._config.tts_timeout_sec,
                max_retries=self._config.tts_max_retries,
                retry_base_delay_ms=self._config.tts_retry_base_delay_ms,
                max_concurrency=self._config.tts_max_concurrency,
            )
            try:
                dedupe_store = RedisDedupeStore.from_url(
                    self._config.redis_url,
                    ttl_sec=self._config.tts_dedupe_ttl_sec,
                    failed_ttl_sec=self._config.tts_failed_dedupe_ttl_sec,
                )
            except RuntimeError:
                logger.warning(
                    "[%s] redis package unavailable; falling back to in-memory TTS dedupe",
                    self._session_id,
                )
                dedupe_store = InMemoryDedupeStore(
                    ttl_sec=self._config.tts_dedupe_ttl_sec,
                    failed_ttl_sec=self._config.tts_failed_dedupe_ttl_sec,
                )
            self._pipeline = self._pipeline_factory(
                session_id=self._session_id,
                target_locales=self._target_locales,
                segmenter=Segmenter(
                    max_chars=self._config.segment_max_chars,
                    idle_flush_ms=self._config.segment_idle_flush_ms,
                    min_chars=self._config.segment_min_chars,
                    split_korean_endings=self._config.segment_split_korean_endings,
                ),
                rag=self._rag,
                translator=translator,
                tts=tts,
                publisher=self._publisher,
                corrector=(
                    self._lexicon.correct_for_display if self._lexicon is not None else None
                ),
                on_subtitle=self._publish_translation,
                on_audio_status=self._publish_audio_status,
                on_segment=self._publish_segment_final,
                on_transcript=(
                    self._publish_transcript
                    if self._transcript_publisher is not None
                    else None
                ),
                dedupe_store=dedupe_store,
                queue_max_size=self._config.segment_queue_max_size,
                tts_queue_max_size=self._config.tts_queue_max_size,
                enqueue_timeout_ms=self._config.segment_enqueue_timeout_ms,
                flush_timeout_sec=self._config.pipeline_flush_timeout_sec,
                tts_flush_timeout_sec=self._config.tts_flush_timeout_sec,
                sequence_start=self._sequence_start,
            )
            await self._pipeline.start()
            await self._set_worker_status("ready")
            logger.info("[%s] pipeline ready (locales=%s)", self._session_id, self._target_locales)

            await self._stopped.wait()
        except Exception as exc:  # noqa: BLE001
            self._failed = True
            await self._set_worker_status("failed", error=str(exc))
            logger.exception("[%s] session worker failed", self._session_id)
            raise
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        if self._cleaned_up:
            return
        self._stopping = True
        await self._set_worker_status("stopping")
        self._stopped.set()
        await self._cleanup()

    def _create_room(self) -> Any:
        if rtc is None:
            raise RuntimeError("LiveKit SDK is not installed")
        return rtc.Room()

    def _build_token(self) -> str:
        if api is None:
            raise RuntimeError("LiveKit API SDK is not installed")
        return (
            api.AccessToken(self._config.livekit_api_key, self._config.livekit_api_secret)
            .with_identity(f"ai-worker-{self._session_id}")
            .with_name("AI Worker")
            .with_metadata(json.dumps({"role": "ai-worker", "sessionId": self._session_id}))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self._room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )

    def _register_room_handlers(self) -> None:
        self._room.on("track_subscribed", self._on_track_subscribed)
        self._room.on("track_unsubscribed", self._on_track_unsubscribed)
        self._room.on("participant_disconnected", self._on_participant_disconnected)
        self._room.on("disconnected", self._on_room_disconnected)

    def _on_track_subscribed(self, track: Any, publication: Any, participant: Any) -> None:
        self._schedule(
            self._attach_professor_track(
                track,
                participant,
                track_key=self._track_key(track, publication),
            )
        )

    def _on_track_unsubscribed(self, track: Any, publication: Any, participant: Any) -> None:
        self._schedule(
            self._detach_professor_track(
                reason="track_unsubscribed",
                track_key=self._track_key(track, publication),
                participant_identity=getattr(participant, "identity", None),
            )
        )

    def _on_participant_disconnected(self, participant: Any) -> None:
        self._schedule(
            self._detach_professor_track(
                reason="participant_disconnected",
                participant_identity=getattr(participant, "identity", None),
            )
        )

    def _on_room_disconnected(self, *_: Any) -> None:
        self._schedule(self.stop())

    async def _attach_professor_track(self, track: Any, participant: Any, *, track_key: str) -> bool:
        if not self._is_professor_audio_track(track, participant):
            return False
        async with self._attach_lock:
            if self._stopping:
                return False
            if self._current_track_key == track_key:
                logger.info("[%s] duplicate professor track ignored: %s", self._session_id, track_key)
                return False

            await self._cancel_reconnect_locked()
            await self._cancel_audio_task_locked()
            self._stop_stt_locked()

            self._current_track = track
            self._current_track_key = track_key
            self._current_professor_identity = getattr(participant, "identity", None)
            self._stt_reconnect_attempts = 0
            self._stt = self._new_stt()
            self._stt.start()
            self._audio_task = asyncio.create_task(
                self._pump_audio(track, track_key),
                name=f"audio-pump-{self._session_id}",
            )
            logger.info("[%s] professor audio track attached (%s)", self._session_id, track_key)
            return True

    async def _detach_professor_track(
        self,
        *,
        reason: str,
        track_key: str | None = None,
        participant_identity: str | None = None,
        cancel_audio_task: bool = True,
    ) -> None:
        async with self._attach_lock:
            if track_key is not None and track_key != self._current_track_key:
                return
            if participant_identity is not None and participant_identity != self._current_professor_identity:
                return
            await self._cancel_reconnect_locked()
            if cancel_audio_task:
                await self._cancel_audio_task_locked()
            self._stop_stt_locked()
            self._current_track = None
            self._current_track_key = None
            self._current_professor_identity = None
            self._stt_reconnect_attempts = 0
            logger.info("[%s] professor audio detached (%s)", self._session_id, reason)

    async def _pump_audio(self, track: Any, track_key: str) -> None:
        stream = self._new_audio_stream(track)
        try:
            async for event in stream:
                stt = self._stt
                if stt is not None:
                    stt.write(event.frame.data.tobytes())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[%s] audio stream interrupted", self._session_id)
        finally:
            await self._close_stream(stream)
            if not self._stopping:
                # 여기서 detach 를 직접 await 하면 안 된다. 이 태스크를 cancel 한
                # 쪽(_cancel_audio_task_locked)이 _attach_lock 을 쥔 채 우리를
                # await 하고 있는데, detach 는 같은 락을 다시 요청하므로
                # 자기교착이 된다 — 락 보유자와 락 대기자가 서로를 기다리는 구조.
                # (이 데드락이 걸리면 세션 종료가 영구 정지하고, 직렬 pubsub 루프가
                # 막혀 다음 수업의 sessions.started 를 영영 처리하지 못한다.)
                # 파이어-앤-포겟으로 스케줄하면 락 획득 시도가 이 태스크 밖에서
                # 일어나고, detach 의 track_key 가드 덕분에 이미 처리된 뒤에는
                # no-op 이라 멱등하다.
                self._schedule(
                    self._detach_professor_track(
                        reason="audio_pump_finished",
                        track_key=track_key,
                        cancel_audio_task=False,
                    )
                )

    async def _on_stt_error(self, error: SttError | str) -> None:
        if isinstance(error, str):
            error = SttError(
                error_code="STT_TRANSIENT_ERROR",
                retryable=True,
                message=error,
                category="transient",
            )
        logger.warning("[%s] STT error: %s", self._session_id, error.message)
        if self._stopping:
            return
        if not error.retryable:
            self._failed = True
            await self._set_worker_status("failed", error=error.message)
            return

        async with self._attach_lock:
            if self._current_track is None or self._current_track_key is None:
                return
            if self._stt_reconnect_attempts >= self._config.stt_max_reconnects:
                self._failed = True
                await self._set_worker_status("failed", error=error.message)
                return
            if self._reconnect_task is not None and not self._reconnect_task.done():
                return
            self._stt_reconnect_attempts += 1
            attempt = self._stt_reconnect_attempts
            track_key = self._current_track_key
            self._reconnect_task = asyncio.create_task(
                self._reconnect_stt_after_delay(track_key, attempt, error),
                name=f"stt-reconnect-{self._session_id}",
            )

    async def _reconnect_stt_after_delay(self, track_key: str, attempt: int, error: SttError) -> None:
        delay = (self._config.stt_reconnect_base_delay_ms / 1000) * (2 ** (attempt - 1))
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._attach_lock:
            if self._stopping or self._current_track_key != track_key or self._current_track is None:
                return
            try:
                self._stop_stt_locked()
                self._stt = self._new_stt()
                self._stt.start()
                logger.info(
                    "[%s] STT recognizer reconnected (track=%s attempt=%s)",
                    self._session_id,
                    track_key,
                    attempt,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("[%s] STT reconnect failed", self._session_id)
                if attempt >= self._config.stt_max_reconnects:
                    self._failed = True
                    await self._set_worker_status("failed", error=str(exc))
                else:
                    self._stt_reconnect_attempts += 1
                    next_attempt = self._stt_reconnect_attempts
                    self._reconnect_task = asyncio.create_task(
                        self._reconnect_stt_after_delay(
                            track_key,
                            next_attempt,
                            SttError(
                                error_code="STT_RECONNECT_FAILED",
                                retryable=True,
                                message=str(exc),
                                category="transient",
                            ),
                        ),
                        name=f"stt-reconnect-{self._session_id}",
                    )
            finally:
                if self._reconnect_task is asyncio.current_task():
                    self._reconnect_task = None

    def _new_stt(self) -> Any:
        if self._stt_factory is not None:
            return self._stt_factory(
                lambda result: self._schedule(self._on_partial(result)),
                lambda result: self._schedule(self._on_final(result)),
                lambda error: self._schedule(self._on_stt_error(error)),
            )
        if self._config.stt_provider == "openai":
            # STT_PROVIDER=openai — Azure 경로(아래)는 문자 그대로 유지된다.
            from .stt_openai import OpenAiRealtimeStt

            return OpenAiRealtimeStt(
                api_key=self._config.openai_api_key,
                model=self._config.stt_openai_model,
                language=self._config.stt_language,
                phrases=self._phrase_list,
                on_partial=lambda result: self._schedule(self._on_partial(result)),
                on_final=lambda result: self._schedule(self._on_final(result)),
                on_error=lambda error: self._schedule(self._on_stt_error(error)),
                silence_ms=self._config.stt_openai_silence_ms,
                include_logprobs=self._config.stt_openai_logprobs,
                keywords_max=self._config.stt_openai_keywords_max,
                vad_threshold=self._config.stt_openai_vad_threshold,
                min_confidence=self._config.stt_openai_min_confidence,
            )
        return AzureStreamingStt(
            key=self._config.azure_speech_key,
            region=self._config.azure_speech_region,
            language=self._config.stt_language,
            phrases=self._phrase_list,
            on_partial=lambda result: self._schedule(self._on_partial(result)),
            on_final=lambda result: self._schedule(self._on_final(result)),
            on_error=lambda error: self._schedule(self._on_stt_error(error)),
            tuning=SttTuning(
                segmentation_silence_ms=self._config.stt_segmentation_silence_ms,
                segmentation_max_time_ms=self._config.stt_segmentation_max_time_ms,
                initial_silence_ms=self._config.stt_initial_silence_ms,
                end_silence_ms=self._config.stt_end_silence_ms,
                true_text=self._config.stt_true_text,
                profanity_raw=self._config.stt_profanity_raw,
                endpoint_id=self._config.stt_endpoint_id,
                phrase_list_weight=self._config.stt_phrase_list_weight,
            ),
        )

    def _new_audio_stream(self, track: Any) -> Any:
        if self._audio_stream_factory is not None:
            return self._audio_stream_factory(track)
        if rtc is None:
            raise RuntimeError("LiveKit SDK is not installed")
        return rtc.AudioStream(track, sample_rate=16000, num_channels=1)

    async def _cancel_reconnect_locked(self) -> None:
        task = self._reconnect_task
        self._reconnect_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cancel_audio_task_locked(self) -> None:
        task = self._audio_task
        if task is None:
            return
        self._audio_task = None
        if task is asyncio.current_task():
            return
        if not task.done():
            task.cancel()
        try:
            # 무한 대기 금지 — 펌프의 정리(_close_stream 등)가 미지의 이유로 막혀도
            # 세션 종료 체인 전체를 볼모로 잡으면 안 된다.
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning(
                "[%s] audio task 가 5초 내 종료되지 않아 대기를 포기한다", self._session_id
            )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] audio task cleanup failed", self._session_id)

    def _stop_stt_locked(self) -> None:
        stt = self._stt
        self._stt = None
        if stt is None:
            return
        try:
            stt.stop()
        except Exception:  # noqa: BLE001
            logger.exception("[%s] STT stop failed", self._session_id)

    def _is_professor_audio_track(self, track: Any, participant: Any) -> bool:
        identity = getattr(participant, "identity", "")
        if not identity.startswith(PROFESSOR_IDENTITY_PREFIX):
            return False
        kind = getattr(track, "kind", None)
        if rtc is not None:
            audio_kind = getattr(getattr(rtc, "TrackKind", object), "KIND_AUDIO", None)
            return kind == audio_kind
        return kind in ("audio", "KIND_AUDIO", None)

    @staticmethod
    def _track_key(track: Any, publication: Any | None = None) -> str:
        for source in (publication, track):
            for attr in ("sid", "track_sid", "name"):
                value = getattr(source, attr, None)
                if value:
                    return str(value)
        return str(id(track))

    async def _close_stream(self, stream: Any) -> None:
        close = getattr(stream, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def _schedule(self, coro: Coroutine[object, object, None]) -> None:
        self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(coro))

    async def _on_partial(self, result: SttPartialResult) -> None:
        # 확정 자막(_build_segment)과 같은 교정을 적용해야 교수 화면에서 partial 과
        # final 이 서로 다른 표기로 보이지 않는다. 정규식 치환이라 비용은 무시할 만하다.
        text = result.text
        if self._lexicon is not None:
            text, _ = self._lexicon.correct_for_display(text)
        await self._publish_stt("stt.partial", text, reliable=False)

    async def _on_final(self, result: SttFinalResult) -> None:
        # 인식이 실제로 돌아왔다는 증거가 있을 때만 재연결 카운터를 리셋한다.
        # 재연결 성공 직후 바로 리셋하면 플래핑 루프가 생긴다.
        if self._stt_reconnect_attempts:
            logger.info(
                "[%s] STT 인식 재개 확인 — 재연결 카운터 리셋 (%d회 → 0)",
                self._session_id,
                self._stt_reconnect_attempts,
            )
            self._stt_reconnect_attempts = 0
        if result.confidence is not None and result.confidence < self._config.stt_low_confidence_warn:
            logger.warning(
                "[%s] 낮은 STT 신뢰도 %.3f: %r",
                self._session_id,
                result.confidence,
                result.text,
            )
        if self._pipeline is not None:
            await self._pipeline.enqueue_stt_final(result)
        else:
            logger.warning(
                "[%s] 파이프라인 준비 전 STT final 폐기: %r", self._session_id, result.text
            )

    async def _publish_stt(self, kind: str, text: str, reliable: bool) -> None:
        payload = json.dumps(
            {
                "type": kind,
                "sessionId": self._session_id,
                "lang": self._config.stt_language,
                "text": text,
                "ts": time.time(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await self._room.local_participant.publish_data(
                payload, reliable=reliable, topic=STT_TOPIC
            )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] STT payload publish failed", self._session_id)

    async def _publish_segment_final(self, segment: SpeechSegment) -> None:
        payload = json.dumps(
            {
                "type": "stt.final",
                "sessionId": self._session_id,
                "segmentId": segment.segment_id,
                "sequence": segment.sequence,
                "lang": self._config.stt_language,
                "text": segment.text,
                "sttConfidence": segment.stt_confidence,
                "ts": time.time(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await self._room.local_participant.publish_data(
                payload, reliable=True, topic=STT_TOPIC
            )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] segment STT final publish failed", self._session_id)

    async def _publish_translation(
        self,
        locale: str,
        text: str,
        segment: SpeechSegment,
        is_final: bool,
        *,
        is_fallback: bool = False,
    ) -> None:
        payload = json.dumps(
            {
                "type": "caption.final" if is_final else "caption.partial",
                "sessionId": self._session_id,
                "segmentId": segment.segment_id,
                "sequence": segment.sequence,
                "locale": locale,
                "text": text,
                "sourceKo": segment.text,
                # 번역이 실패해 한국어 원문을 그대로 내보낸 경우. 학생 화면이 이를 구분해 표시한다.
                "isFallback": is_fallback,
                "sttConfidence": segment.stt_confidence,
                "ts": time.time(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await self._room.local_participant.publish_data(
                payload, reliable=is_final, topic=CAPTION_TOPIC
            )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] caption publish failed (%s)", self._session_id, locale)

    async def _publish_transcript(
        self,
        segment: SpeechSegment,
        translations: dict[str, dict[str, Any]],
    ) -> None:
        """번역 완료된 세그먼트를 Redis 로 발행한다. NestJS 가 받아 DB 에 저장한다."""
        if self._transcript_publisher is None:
            return
        payload = {
            "type": "transcript.segment",
            "sessionId": self._session_id,
            "segmentId": segment.segment_id,
            "sequence": segment.sequence,
            "textKo": segment.text,
            "rawTextKo": segment.raw_text,
            "sttConfidence": segment.stt_confidence,
            "translations": translations,
            "ts": time.time(),
        }
        try:
            await self._transcript_publisher(payload)
        except Exception:  # noqa: BLE001 - 저장 실패가 실시간 전달을 막으면 안 된다.
            logger.exception(
                "[%s] transcript publish failed (%s)",
                self._session_id,
                segment.segment_id,
            )

    async def _publish_audio_status(self, status: AudioStatus) -> None:
        payload = json.dumps(
            audio_status_payload(status),
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await self._room.local_participant.publish_data(
                payload, reliable=True, topic=AUDIO_STATUS_TOPIC
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] audio status publish failed (%s, %s)",
                self._session_id,
                status.segment_id,
                status.locale,
            )

    async def _cleanup(self) -> None:
        async with self._cleanup_lock:
            if self._cleaned_up:
                return
            self._cleaned_up = True
            self._stopping = True
            errors: list[str] = []

            async with self._attach_lock:
                await self._cancel_reconnect_locked()
                self._stop_stt_locked()
                audio_task = self._audio_task
                self._audio_task = None
                self._current_track = None
                self._current_track_key = None
                self._current_professor_identity = None

            # 종료 체인의 어느 한 단계도 세션 정리를 볼모로 잡으면 안 된다.
            # 정리가 hang 하면 end_session → pubsub 루프까지 연쇄로 멈춰
            # 다음 수업이 영영 활성화되지 않는 것이 실제 관측된 장애다.
            async def _bounded(label: str, awaitable: Any, timeout: float) -> None:
                try:
                    await asyncio.wait_for(awaitable, timeout=timeout)
                except asyncio.TimeoutError:
                    errors.append(f"{label}: timeout {timeout}s")
                    logger.warning(
                        "[%s] %s 정리가 %.0f초 내 끝나지 않아 건너뛴다",
                        self._session_id,
                        label,
                        timeout,
                    )
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{label}: {exc}")
                    logger.exception("[%s] %s cleanup failed", self._session_id, label)

            if self._pipeline is not None:
                await _bounded("pipeline", self._pipeline.flush_and_stop(), 10)

            # HttpRagClient 는 커넥션을 재사용하므로 세션 종료 시 닫아야 한다.
            # (여기서 세션 통틀어 RAG on=0 이었는지도 함께 보고된다.)
            rag_close = getattr(self._rag, "aclose", None)
            if rag_close is not None:
                result = rag_close()
                if inspect.isawaitable(result):
                    await _bounded("rag", result, 5)

            if audio_task is not None:
                if not audio_task.done():
                    audio_task.cancel()
                await _bounded("audio", asyncio.shield(audio_task), 5)

            if self._publisher is not None:
                await _bounded("publisher", self._publisher.aclose(), 5)

            await _bounded("room", self._room.disconnect(), 5)

            if self._failed or errors:
                await self._set_worker_status("failed", error="; ".join(errors) or "worker failed")
            else:
                await self._set_worker_status("stopped")
            logger.info("[%s] session worker stopped", self._session_id)

    def _diagnostics(self) -> dict[str, object]:
        """교수 화면이 그대로 읽는 진단 요약.

        glossary 0개 / lexicon 없음 / RAG 미동작은 자막만 봐서는 알 수 없다.
        RAG 는 설정값(on/off)이 아니라 preflight 결과를 내보낸다 — 켜 놓고 서비스가
        죽어 있거나 인덱스가 없어도 fail-open 이라 겉으로는 똑같이 번역되기 때문이다.
        """
        return {
            "glossary": len(self._glossary),
            "lexicon": self._lexicon.major if self._lexicon is not None else None,
            "phraseList": len(self._phrase_list),
            "rag": self._rag_status,
        }

    async def _set_worker_status(self, status: str, *, error: str | None = None) -> None:
        try:
            await self._status_store.set_status(  # type: ignore[arg-type]
                self._session_id,
                status,
                error=error,
                diagnostics=self._diagnostics(),
            )
        except TypeError:
            # 구형 status store (diagnostics 미지원) 호환
            try:
                await self._status_store.set_status(self._session_id, status, error=error)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[%s] worker status update failed: %s", self._session_id, status
                )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] worker status update failed: %s", self._session_id, status)
