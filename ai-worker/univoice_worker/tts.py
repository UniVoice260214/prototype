"""Azure Neural Voice TTS with async timeout, retry, and concurrency control."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
    ) -> None:
        self._key = key
        self._region = region
        self._voice_map = voice_map
        self._timeout_sec = max(0.001, timeout_sec)
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = max(0, retry_base_delay_ms) / 1000
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._synthesizers: dict[str, Any] = {}

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
            details = getattr(result, "cancellation_details", None)
            reason = str(getattr(details, "reason", "canceled"))
            error_details = str(getattr(details, "error_details", ""))
            error_code, retryable = self._classify_failure(reason, error_details)
            message = f"{reason}: {error_details}".strip(": ")
            raise TtsException(error_code, message, retryable=retryable)

        raise TtsException(
            "TTS_UNKNOWN_RESULT",
            f"Unexpected Azure TTS result reason: {result.reason}",
            retryable=True,
        )

    async def synthesize_job(self, job: TtsJob) -> bytes:
        return await self.synthesize_async(job.locale, job.text, job=job)

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
                except TimeoutError as exc:
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
        if isinstance(exc, TimeoutError):
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
