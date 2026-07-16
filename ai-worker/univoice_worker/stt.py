"""Azure Speech streaming STT adapter."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable

try:  # pragma: no cover - Azure SDK is runtime-provided; tests use fakes.
    import azure.cognitiveservices.speech as speechsdk
except ImportError:  # pragma: no cover
    speechsdk = None  # type: ignore[assignment]

from .models import SttFinalResult, SttPartialResult

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BITS_PER_SAMPLE = 16
CHANNELS = 1

PartialCallback = Callable[[SttPartialResult], None]
FinalCallback = Callable[[SttFinalResult], None]
ErrorCallback = Callable[["SttError"], None]


@dataclass(frozen=True)
class SttError:
    error_code: str
    retryable: bool
    message: str
    category: str
    details: str | None = None


_PERMANENT_MARKERS = (
    "authentication",
    "unauthorized",
    "forbidden",
    "subscription",
    "key",
    "region",
    "invalid",
    "bad request",
    "language",
)
_TRANSIENT_MARKERS = (
    "timeout",
    "network",
    "connection",
    "connect",
    "temporar",
    "throttl",
    "rate",
    "429",
    "500",
    "502",
    "503",
    "504",
    "service",
    "unavailable",
    "session",
)


def classify_stt_error(reason: Any, details: Any) -> SttError:
    reason_text = str(reason or "canceled")
    details_text = str(details or "")
    combined = f"{reason_text} {details_text}".lower()
    if any(marker in combined for marker in _PERMANENT_MARKERS):
        return SttError(
            error_code="STT_PERMANENT_ERROR",
            retryable=False,
            message=f"STT canceled: {reason_text} {details_text}".strip(),
            category="permanent",
            details=details_text or None,
        )
    if any(marker in combined for marker in _TRANSIENT_MARKERS):
        return SttError(
            error_code="STT_TRANSIENT_ERROR",
            retryable=True,
            message=f"STT canceled: {reason_text} {details_text}".strip(),
            category="transient",
            details=details_text or None,
        )
    return SttError(
        error_code="STT_CANCELED",
        retryable=True,
        message=f"STT canceled: {reason_text} {details_text}".strip(),
        category="transient",
        details=details_text or None,
    )


def _ticks_to_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value) // 10_000
    except (TypeError, ValueError):
        return None


def _result_property(result: Any, property_id: Any) -> str | None:
    properties = getattr(result, "properties", None)
    if properties is None:
        return None
    for getter_name in ("get", "get_property"):
        getter = getattr(properties, getter_name, None)
        if getter is None:
            continue
        try:
            value = getter(property_id)
        except Exception:  # noqa: BLE001 - SDK property bags vary by version.
            continue
        if value:
            return str(value)
    return None


def _parse_detailed_result(result: Any) -> tuple[float | None, int | None, int | None]:
    """Extract confidence/timing from Azure detailed JSON without breaking STT."""
    confidence: float | None = None
    offset_ms: int | None = _ticks_to_ms(getattr(result, "offset", None))
    duration_ms: int | None = _ticks_to_ms(getattr(result, "duration", None))

    raw_json = _result_property(result, speechsdk.PropertyId.SpeechServiceResponse_JsonResult)
    if not raw_json:
        return confidence, offset_ms, duration_ms

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.debug("Failed to parse Azure STT detailed JSON", exc_info=True)
        return confidence, offset_ms, duration_ms

    nbest = data.get("NBest")
    if isinstance(nbest, list) and nbest:
        first = nbest[0]
        if isinstance(first, dict):
            raw_confidence = first.get("Confidence")
            if raw_confidence is not None:
                try:
                    confidence = float(raw_confidence)
                except (TypeError, ValueError):
                    confidence = None

    offset_ms = _ticks_to_ms(data.get("Offset")) if data.get("Offset") is not None else offset_ms
    duration_ms = (
        _ticks_to_ms(data.get("Duration")) if data.get("Duration") is not None else duration_ms
    )
    return confidence, offset_ms, duration_ms


class AzureStreamingStt:
    def __init__(
        self,
        key: str,
        region: str,
        language: str,
        phrases: Iterable[str],
        on_partial: PartialCallback,
        on_final: FinalCallback,
        on_error: ErrorCallback | None = None,
    ) -> None:
        if speechsdk is None:
            raise RuntimeError("Azure Speech SDK is not installed")
        self._on_error = on_error
        self._stop_lock = threading.Lock()
        self._stopped = False

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=SAMPLE_RATE,
            bits_per_sample=BITS_PER_SAMPLE,
            channels=CHANNELS,
        )
        self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)

        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_recognition_language = language
        speech_config.output_format = speechsdk.OutputFormat.Detailed

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=speechsdk.audio.AudioConfig(stream=self._push_stream),
        )

        phrase_list = speechsdk.PhraseListGrammar.from_recognizer(self._recognizer)
        for phrase in phrases:
            if phrase:
                phrase_list.addPhrase(phrase)

        self._recognizer.recognizing.connect(
            lambda evt: evt.result.text and on_partial(SttPartialResult(text=evt.result.text))
        )
        self._recognizer.recognized.connect(lambda evt: self._handle_recognized(evt, on_final))
        self._recognizer.canceled.connect(self._handle_canceled)

    def _handle_recognized(
        self,
        evt: Any,
        on_final: FinalCallback,
    ) -> None:
        result = evt.result
        if result.reason != speechsdk.ResultReason.RecognizedSpeech or not result.text:
            return
        confidence, offset_ms, duration_ms = _parse_detailed_result(result)
        on_final(
            SttFinalResult(
                text=result.text,
                confidence=confidence,
                offset_ms=offset_ms,
                duration_ms=duration_ms,
            )
        )

    def _handle_canceled(self, evt: Any) -> None:
        error = classify_stt_error(
            getattr(evt, "reason", None),
            getattr(evt, "error_details", None),
        )
        logger.warning("%s", error.message)
        if self._on_error is not None:
            self._on_error(error)

    def start(self) -> None:
        self._recognizer.start_continuous_recognition_async().get()

    def write(self, pcm: bytes) -> None:
        with self._stop_lock:
            if self._stopped:
                return
        self._push_stream.write(pcm)

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        try:
            self._push_stream.close()
        except Exception:  # noqa: BLE001 - shutdown is best-effort.
            logger.exception("STT push stream close failed")
        try:
            self._recognizer.stop_continuous_recognition_async().get()
        except Exception:  # noqa: BLE001 - shutdown is best-effort.
            logger.exception("STT stop failed")
