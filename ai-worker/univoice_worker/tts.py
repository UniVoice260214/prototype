"""Azure Neural Voice TTS with async timeout, retry, and concurrency control."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

try:  # pragma: no cover - the SDK is supplied in production, faked in tests
    import azure.cognitiveservices.speech as speechsdk
except ImportError:  # pragma: no cover
    speechsdk = None  # type: ignore[assignment]

from .models import TtsException, TtsJob

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
DEFAULT_TTS_TIMEOUT_SEC = 15.0
DEFAULT_TTS_MAX_RETRIES = 2
DEFAULT_TTS_RETRY_BASE_DELAY_MS = 500
DEFAULT_TTS_MAX_CONCURRENCY = 3
# 스트리밍 합성 시 한 번에 읽는 PCM 크기: 16kHz 16bit mono 에서 100ms.
# 오디오 프레임(10ms = 320B)의 배수여야 publisher 가 중간에 무음 패딩을 넣지 않는다.
STREAM_CHUNK_BYTES = 3200

ChunkSink = Callable[[bytes], None]

_TRANSIENT_MARKERS = (
    "timeout",
    "temporar",
    "network",
    "connection",
    "connect",
    "throttl",
    "too many requests",
    "rate",
    "429",
    "500",
    "502",
    "503",
    "504",
    "busy",
    "unavailable",
)
_PERMANENT_MARKERS = (
    "invalid",
    "bad request",
    "unsupported",
    "not found",
    "401",
    "403",
    "unauthor",
    "forbidden",
    "authentication",
    "subscription",
    "region",
)


class TtsSynthesizer:
    def __init__(
        self,
        key: str,
        region: str,
        voice_map: dict[str, str],
        *,
        timeout_sec: float = DEFAULT_TTS_TIMEOUT_SEC,
        max_retries: int = DEFAULT_TTS_MAX_RETRIES,
        retry_base_delay_ms: int = DEFAULT_TTS_RETRY_BASE_DELAY_MS,
        max_concurrency: int = DEFAULT_TTS_MAX_CONCURRENCY,
        streaming: bool = True,
    ) -> None:
        self._key = key
        self._streaming = streaming
        self._region = region
        self._voice_map = voice_map
        self._timeout_sec = max(0.001, timeout_sec)
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = max(0, retry_base_delay_ms) / 1000
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._synthesizers: dict[str, Any] = {}
        # 예열로 미리 연 연결. 참조를 쥐고 있어야 GC 로 닫히지 않는다.
        self._connections: dict[str, Any] = {}
        # 로케일 synthesizer 하나에 합성 요청이 겹치지 않게 한다. 선합성(다음 job 을
        # 앞 job 재생 중에 시작)이 같은 synthesizer 를 동시에 쓰는 것을 막는다.
        self._locale_locks: dict[str, threading.Lock] = {}
        self._locale_locks_guard = threading.Lock()

    def _get(self, locale: str) -> Any:
        if locale in self._synthesizers:
            return self._synthesizers[locale]
        if speechsdk is None:
            raise TtsException(
                "TTS_AZURE_SDK_MISSING",
                "Azure Speech SDK is not installed",
                retryable=False,
            )
        voice = self._voice_map.get(locale)
        if not voice:
            raise TtsException(
                "TTS_UNSUPPORTED_LOCALE",
                f"No Azure TTS voice configured for locale {locale}",
                retryable=False,
            )

        cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
        cfg.speech_synthesis_voice_name = voice
        cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
        )
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        self._synthesizers[locale] = synth
        return synth

    async def warmup(self, locales: list[str]) -> None:
        """로케일별 synthesizer 를 만들고 서비스 연결을 미리 연다.

        synthesizer 생성과 Connection.open 은 모두 blocking 이라 스레드에서 돈다.
        로케일 하나의 실패는 로그만 남기고, 전부 실패했을 때만 예외를 올린다.
        """
        if not locales:
            return
        results = await asyncio.gather(
            *(asyncio.to_thread(self._open_connection, locale) for locale in locales),
            return_exceptions=True,
        )
        failures: list[tuple[str, BaseException]] = []
        for locale, result in zip(locales, results):
            if isinstance(result, BaseException):
                failures.append((locale, result))
                logger.warning("TTS 예열 실패 (locale=%s): %r", locale, result)
        if failures and len(failures) == len(locales):
            raise failures[0][1]

    def _open_connection(self, locale: str) -> None:
        synth = self._get(locale)
        connection_cls = getattr(speechsdk, "Connection", None)
        if connection_cls is None:  # pragma: no cover - 구버전 SDK
            return
        connection = connection_cls.from_speech_synthesizer(synth)
        connection.open(True)
        self._connections[locale] = connection

    def synthesize(self, locale: str, text: str) -> bytes:
        """Blocking Azure synthesis. Raises TtsException on typed failure."""
        if not text or not text.strip():
            raise TtsException("TTS_EMPTY_TEXT", "TTS text is empty", retryable=False)

        try:
            synth = self._get(locale)
            result = synth.speak_text_async(text).get()
        except TtsException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._classify_exception(exc) from exc

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio = bytes(getattr(result, "audio_data", b"") or b"")
            if not audio:
                raise TtsException(
                    "TTS_EMPTY_AUDIO",
                    "Azure TTS completed without audio data",
                    retryable=True,
                )
            return audio

        if result.reason == speechsdk.ResultReason.Canceled:
            raise self._canceled_exception(getattr(result, "cancellation_details", None))

        raise TtsException(
            "TTS_UNKNOWN_RESULT",
            f"Unexpected Azure TTS result reason: {result.reason}",
            retryable=True,
        )

    def _canceled_exception(self, details: Any) -> TtsException:
        reason = str(getattr(details, "reason", "canceled"))
        error_details = str(getattr(details, "error_details", ""))
        error_code, retryable = self._classify_failure(reason, error_details)
        message = f"{reason}: {error_details}".strip(": ")
        return TtsException(error_code, message, retryable=retryable)

    async def synthesize_job(self, job: TtsJob) -> bytes:
        return await self.synthesize_async(job.locale, job.text, job=job)

    # ── 스트리밍 합성 ─────────────────────────────────────────────────────

    @property
    def streaming_supported(self) -> bool:
        """설치된 SDK 가 청크 단위 합성(start_speaking + AudioDataStream)을 지원하는가."""
        return (
            self._streaming
            and speechsdk is not None
            and hasattr(speechsdk, "AudioDataStream")
            and hasattr(getattr(speechsdk, "SpeechSynthesizer", None), "start_speaking_text_async")
        )

    async def stream_job(self, job: TtsJob, on_chunk: ChunkSink) -> None:
        """합성되는 PCM 을 청크 단위로 on_chunk 에 넘긴다 (이벤트 루프에서 호출).

        - 오디오 전체가 끝나길 기다리지 않는다. 첫 청크는 합성 시작 직후 나온다.
        - 재시도는 첫 청크 전 실패에만 한다. 이미 일부를 내보냈으면 다시 합성할 수
          없으므로(앞부분이 재생 중) 그대로 실패를 올린다.
        - 타임아웃은 청크 간 간격 기준이다 (첫 청크 대기 포함).
        - 스트리밍을 못 쓰는 환경이면 기존 synthesize_job 결과를 한 청크로 넘긴다.
        """
        if not self.streaming_supported:
            on_chunk(await self.synthesize_job(job))
            return
        if not job.text or not job.text.strip():
            raise TtsException("TTS_EMPTY_TEXT", "TTS text is empty", retryable=False)

        attempts = self._max_retries + 1
        async with self._semaphore:
            for attempt in range(1, attempts + 1):
                delivered = False

                def deliver(chunk: bytes) -> None:
                    nonlocal delivered
                    delivered = True
                    on_chunk(chunk)

                try:
                    await self._stream_once(job.locale, job.text, deliver)
                    return
                except TtsException as exc:
                    failure = exc
                except Exception as exc:  # noqa: BLE001
                    failure = self._classify_exception(exc)

                if delivered or not failure.retryable or attempt >= attempts:
                    raise failure
                self._log_retry(job, job.locale, attempt, failure)
                await asyncio.sleep(self._retry_delay(attempt))

        raise TtsException("TTS_UNKNOWN", "TTS synthesis exited unexpectedly", retryable=True)

    async def _stream_once(self, locale: str, text: str, deliver: ChunkSink) -> None:
        loop = asyncio.get_running_loop()
        items: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        stop = threading.Event()

        def put(kind: str, payload: Any) -> None:
            try:
                loop.call_soon_threadsafe(items.put_nowait, (kind, payload))
            except RuntimeError:  # 루프가 이미 닫힘 — 종료 경합
                stop.set()

        def run() -> None:
            try:
                self._stream_blocking(locale, text, lambda chunk: put("chunk", chunk), stop)
                put("done", None)
            except BaseException as exc:  # noqa: BLE001 - 루프 쪽에서 분류한다.
                put("error", exc)

        worker = asyncio.ensure_future(asyncio.to_thread(run))
        received = 0
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(items.get(), timeout=self._timeout_sec)
                except asyncio.TimeoutError as exc:
                    raise TtsException(
                        "TTS_TIMEOUT",
                        f"TTS stream stalled for {self._timeout_sec:.3f}s",
                        retryable=True,
                        original=exc,
                    ) from exc
                if kind == "chunk":
                    received += len(payload)
                    deliver(payload)
                elif kind == "done":
                    if not received:
                        raise TtsException(
                            "TTS_EMPTY_AUDIO",
                            "Azure TTS stream completed without audio data",
                            retryable=True,
                        )
                    return
                else:
                    if isinstance(payload, TtsException):
                        raise payload
                    raise self._classify_exception(payload)
        finally:
            # 소비가 멈추면(타임아웃/취소) 스레드도 다음 read 에서 빠져나오게 한다.
            stop.set()
            if not worker.done():
                worker.add_done_callback(lambda f: f.cancelled() or f.exception())

    def _locale_lock(self, locale: str) -> threading.Lock:
        with self._locale_locks_guard:
            return self._locale_locks.setdefault(locale, threading.Lock())

    def _stream_blocking(
        self,
        locale: str,
        text: str,
        emit: ChunkSink,
        stop: threading.Event,
    ) -> None:
        """Blocking Azure 스트리밍 합성. 스레드에서 돈다."""
        with self._locale_lock(locale):
            if stop.is_set():
                return
            try:
                synth = self._get(locale)
                result = synth.start_speaking_text_async(text).get()
            except TtsException:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._classify_exception(exc) from exc

            if result.reason == speechsdk.ResultReason.Canceled:
                raise self._canceled_exception(getattr(result, "cancellation_details", None))

            stream = speechsdk.AudioDataStream(result)
            buffer = bytes(STREAM_CHUNK_BYTES)
            while not stop.is_set():
                filled = stream.read_data(buffer)
                if not filled:
                    break
                # read_data 는 (불변인) bytes buffer 를 C 에서 제자리로 덮어쓴다.
                # buffer[:filled] 는 꽉 찬 경우 같은 객체를 돌려주므로(CPython 최적화)
                # memoryview 로 항상 새 복사본을 만든다.
                emit(bytes(memoryview(buffer)[:filled]))

            if stop.is_set():
                try:
                    synth.stop_speaking_async().get()
                except Exception:  # noqa: BLE001
                    logger.debug("TTS stop_speaking 실패", exc_info=True)
                return

            if stream.status == speechsdk.StreamStatus.Canceled:
                raise self._canceled_exception(getattr(stream, "cancellation_details", None))

    async def synthesize_async(
        self,
        locale: str,
        text: str,
        *,
        job: TtsJob | None = None,
    ) -> bytes:
        """Run blocking Azure synthesis off-loop with retry and timeout."""
        attempts = self._max_retries + 1
        async with self._semaphore:
            for attempt in range(1, attempts + 1):
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(self.synthesize, locale, text),
                        timeout=self._timeout_sec,
                    )
                except asyncio.TimeoutError as exc:
                    failure = TtsException(
                        "TTS_TIMEOUT",
                        f"TTS synthesis exceeded {self._timeout_sec:.3f}s",
                        retryable=True,
                        original=exc,
                    )
                except TtsException as exc:
                    failure = exc
                except Exception as exc:  # noqa: BLE001
                    failure = self._classify_exception(exc)

                if not failure.retryable or attempt >= attempts:
                    raise failure

                self._log_retry(job, locale, attempt, failure)
                await asyncio.sleep(self._retry_delay(attempt))

        raise TtsException("TTS_UNKNOWN", "TTS synthesis exited unexpectedly", retryable=True)

    def _retry_delay(self, attempt: int) -> float:
        return self._retry_base_delay * (2 ** (attempt - 1))

    def _log_retry(
        self,
        job: TtsJob | None,
        locale: str,
        attempt: int,
        failure: TtsException,
    ) -> None:
        logger.warning(
            "[%s] TTS retry segment=%s sequence=%s locale=%s attempt=%s error=%s message=%s",
            job.session_id if job else "-",
            job.segment_id if job else "-",
            job.sequence if job else "-",
            job.locale if job else locale,
            attempt,
            failure.error_code,
            failure.message,
        )

    def _classify_exception(self, exc: BaseException) -> TtsException:
        if isinstance(exc, asyncio.TimeoutError):
            return TtsException("TTS_TIMEOUT", str(exc) or "TTS timed out", retryable=True, original=exc)
        error_code, retryable = self._classify_failure(type(exc).__name__, str(exc))
        return TtsException(error_code, str(exc) or type(exc).__name__, retryable=retryable, original=exc)

    def _classify_failure(self, reason: str, details: str) -> tuple[str, bool]:
        text = f"{reason} {details}".lower()
        if "voice" in text or "locale" in text or "language" in text:
            return "TTS_BAD_VOICE_OR_LOCALE", False
        if any(marker in text for marker in _PERMANENT_MARKERS):
            return "TTS_PERMANENT_ERROR", False
        if "429" in text or "throttl" in text or "too many requests" in text or "rate" in text:
            return "TTS_RATE_LIMIT", True
        if "timeout" in text:
            return "TTS_TIMEOUT", True
        if any(marker in text for marker in _TRANSIENT_MARKERS):
            return "TTS_TRANSIENT_ERROR", True
        return "TTS_AZURE_CANCELED", True
