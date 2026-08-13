"""Azure Speech streaming STT adapter."""

from __future__ import annotations

import json
import logging
import threading
import time
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


# 재시도해도 소용없는, 설정/자격 증명 문제. 짧은 낱말이 아니라 정확한 구문으로 좁힌다.
# 예전에는 "key", "invalid", "language" 같은 부분문자열을 썼는데, 그러면
# "invalid session state", "websocket upgrade invalid" 같은 **일시적** 메시지까지
# permanent 로 분류돼 재시도 없이 STT 가 영구 정지했다.
_PERMANENT_MARKERS = (
    "authentication failed",
    "authentication error",
    "unauthorized",
    "forbidden",
    "subscription key is invalid",
    "invalid subscription key",
    "invalid subscription",
    "quota exceeded",
    "unsupported language",
    "unsupported locale",
    "bad request",
    "401",
    "403",
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
    "reset",
    "closed",
)


def extract_cancellation(evt: Any) -> tuple[Any, Any]:
    """SDK 취소 이벤트에서 (reason, details) 를 뽑아낸다.

    Python SDK 는 상세를 evt.cancellation_details 에 담는다 — evt.error_details 를
    읽으면 항상 None 이라 로그가 "STT canceled: canceled" 로만 남고, 401 인증 오류가
    transient 로 오분류되어 의미 없는 재시도를 반복한다 (실제 장애에서 확인).
    """
    details_obj = getattr(evt, "cancellation_details", None)
    reason = getattr(details_obj, "reason", None) or getattr(evt, "reason", None)
    details = getattr(details_obj, "error_details", None) or getattr(
        evt, "error_details", None
    )
    error_code = getattr(details_obj, "error_code", None)
    if error_code is not None:
        details = f"{error_code}: {details}" if details else str(error_code)
    return reason, details


def classify_stt_error(reason: Any, details: Any) -> SttError:
    """취소 사유를 재시도 가능/불가로 나눈다.

    permanent 를 먼저 보되, 마커가 **정밀한 구문**이라 오분류 위험이 낮다.
    (transient 를 먼저 보면 안 된다 — Azure 의 취소 사유가 문자열
    `CancelledByService` 라서 transient 마커 "service" 에 항상 걸린다.)
    분류가 애매하면 재시도 쪽으로 기운다. 잘못 죽어 자막이 끊기는 손해가 더 크다.
    """
    reason_text = str(reason or "canceled")
    details_text = str(details or "")
    combined = f"{reason_text} {details_text}".lower()
    message = f"STT canceled: {reason_text} {details_text}".strip()
    if any(marker in combined for marker in _PERMANENT_MARKERS):
        logger.error("STT permanent error (재시도 안 함): %s", message)
        return SttError(
            error_code="STT_PERMANENT_ERROR",
            retryable=False,
            message=message,
            category="permanent",
            details=details_text or None,
        )
    if any(marker in combined for marker in _TRANSIENT_MARKERS):
        return SttError(
            error_code="STT_TRANSIENT_ERROR",
            retryable=True,
            message=message,
            category="transient",
            details=details_text or None,
        )
    return SttError(
        error_code="STT_CANCELED",
        retryable=True,
        message=message,
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


@dataclass(frozen=True)
class SttTuning:
    """한국어 강의 발화에 맞춘 Azure Speech 인식 파라미터.

    기본값은 Azure 기본 설정이 아니라 **강의용으로 조정한 값**이다.
    Azure 기본 segmentation timeout(~500ms)은 한국어 강의체의 어절/조사 뒤 휴지를
    문장 끝으로 오인해 절 중간을 자른다.
    """

    segmentation_silence_ms: int = 800
    initial_silence_ms: int = 15000
    end_silence_ms: int = 1000
    # 쉼 없이 이어지는 발화의 강제 확정 상한. 침묵(800ms)만 기다리면 긴 발화에서
    # final 이 계속 미뤄져 자막이 늘어진다. 0 이면 끄기. Azure 허용 범위 20~70초.
    segmentation_max_time_ms: int = 20000
    true_text: bool = True
    profanity_raw: bool = True
    endpoint_id: str = ""            # Custom Speech. 빈 값이면 미사용.
    phrase_list_weight: float = 1.0


# Azure Speech 가 허용하는 Speech_SegmentationMaximumTimeMs 범위.
SEGMENTATION_MAX_TIME_RANGE_MS = (20_000, 70_000)


def clamp_segmentation_max_time(value_ms: int) -> int:
    """시간 기반 분할 상한을 Azure 허용 범위로 보정한다. 0 이하는 비활성(0)."""
    if value_ms <= 0:
        return 0
    low, high = SEGMENTATION_MAX_TIME_RANGE_MS
    clamped = min(max(value_ms, low), high)
    if clamped != value_ms:
        logger.warning(
            "STT_SEGMENTATION_MAX_TIME_MS=%d 는 Azure 허용 범위(%d~%d) 밖이라 %d 로 보정",
            value_ms,
            low,
            high,
            clamped,
        )
    return clamped


def _configure_speech(speech_config: Any, language: str, tuning: SttTuning) -> None:
    """SpeechConfig 에 강의용 튜닝을 적용한다.

    속성 하나가 SDK 버전 차이로 실패해도 STT 자체는 떠야 하므로 개별 예외를 삼킨다.
    """
    speech_config.speech_recognition_language = language
    # Detailed 는 NBest[0].Confidence 수집에 필요하다. 끄면 confidence 계측이 죽는다.
    speech_config.output_format = speechsdk.OutputFormat.Detailed

    properties: list[tuple[str, Any, str]] = [
        (
            "segmentation_silence_ms",
            getattr(speechsdk.PropertyId, "Speech_SegmentationSilenceTimeoutMs", None),
            str(tuning.segmentation_silence_ms),
        ),
        (
            "initial_silence_ms",
            getattr(
                speechsdk.PropertyId,
                "SpeechServiceConnection_InitialSilenceTimeoutMs",
                None,
            ),
            str(tuning.initial_silence_ms),
        ),
        (
            "end_silence_ms",
            getattr(
                speechsdk.PropertyId,
                "SpeechServiceConnection_EndSilenceTimeoutMs",
                None,
            ),
            str(tuning.end_silence_ms),
        ),
    ]
    max_time_ms = clamp_segmentation_max_time(tuning.segmentation_max_time_ms)
    if max_time_ms:
        # 침묵 없이 이어지는 발화도 max_time 마다 강제로 final 을 받는다.
        # 최대 시간 분할은 Time 전략에서만 동작한다 (SDK 1.41+).
        properties.append(
            (
                "segmentation_strategy",
                getattr(speechsdk.PropertyId, "Speech_SegmentationStrategy", None),
                "Time",
            )
        )
        properties.append(
            (
                "segmentation_max_time_ms",
                getattr(
                    speechsdk.PropertyId, "Speech_SegmentationMaximumTimeMs", None
                ),
                str(max_time_ms),
            )
        )
    if tuning.true_text:
        # 문장부호·대소문자 후처리. 이게 없으면 ko-KR 결과에 문장부호가 거의 안 붙어
        # segmenter 의 문장 분리가 max_chars/idle 폴백으로만 동작한다.
        properties.append(
            (
                "true_text",
                getattr(
                    speechsdk.PropertyId,
                    "SpeechServiceResponse_PostProcessingOption",
                    None,
                ),
                "TrueText",
            )
        )

    for name, property_id, value in properties:
        if property_id is None:
            logger.warning("Azure Speech SDK에 %s 속성이 없어 건너뜀", name)
            continue
        try:
            speech_config.set_property(property_id, value)
        except Exception:  # noqa: BLE001 - 속성 하나 때문에 STT를 못 띄우면 안 된다.
            logger.exception("STT 속성 적용 실패: %s=%s", name, value)

    if tuning.profanity_raw:
        # 기본값 Masked 는 전공어가 비속어로 오분류될 때 '****' 로 자막을 망친다.
        try:
            speech_config.set_profanity(speechsdk.ProfanityOption.Raw)
        except Exception:  # noqa: BLE001
            logger.exception("STT profanity 설정 실패")

    if tuning.endpoint_id:
        try:
            speech_config.endpoint_id = tuning.endpoint_id
            logger.info("Custom Speech 엔드포인트 사용: %s", tuning.endpoint_id)
        except Exception:  # noqa: BLE001
            logger.exception("Custom Speech endpoint_id 적용 실패: %s", tuning.endpoint_id)


def _apply_phrase_list(recognizer: Any, phrases: Iterable[str], weight: float) -> int:
    """PhraseListGrammar 에 구문을 주입하고 실제로 넣은 개수를 반환한다.

    호출부에서 이미 중복 제거/상한 절단을 마친 목록이 온다고 가정하지 않고,
    여기서도 방어적으로 정규화한다.
    """
    grammar = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
    seen: set[str] = set()
    added = 0
    for phrase in phrases:
        text = " ".join(str(phrase or "").split())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        grammar.addPhrase(text)
        added += 1

    if added and weight and weight != 1.0:
        setter = getattr(grammar, "setWeight", None) or getattr(grammar, "set_weight", None)
        if setter is None:
            logger.warning("PhraseListGrammar 에 weight 설정 API가 없어 건너뜀")
        else:
            try:
                setter(weight)
            except Exception:  # noqa: BLE001
                logger.exception("PhraseList weight 설정 실패: %s", weight)
    return added


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
        *,
        tuning: SttTuning | None = None,
    ) -> None:
        if speechsdk is None:
            raise RuntimeError("Azure Speech SDK is not installed")
        self._on_error = on_error
        self._stop_lock = threading.Lock()
        self._stopped = False
        # Azure 가 주는 offset 은 오디오 스트림 시작 기준이다. 이 앵커가 있어야
        # "발화가 실제로 끝난 시각"을 monotonic 시간축으로 되돌릴 수 있다.
        self._stream_started_at: float | None = None
        tuning = tuning or SttTuning()

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=SAMPLE_RATE,
            bits_per_sample=BITS_PER_SAMPLE,
            channels=CHANNELS,
        )
        self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)

        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        _configure_speech(speech_config, language, tuning)

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=speechsdk.audio.AudioConfig(stream=self._push_stream),
        )

        self.phrase_count = _apply_phrase_list(
            self._recognizer, phrases, tuning.phrase_list_weight
        )

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
        received_at = time.monotonic()
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
                received_at=received_at,
                speech_end_at=self._speech_end_at(offset_ms, duration_ms),
            )
        )

    def _speech_end_at(self, offset_ms: int | None, duration_ms: int | None) -> float | None:
        """오디오 타임라인 기준 발화 종료 지점을 monotonic 시각으로 환산한다."""
        anchor = self._stream_started_at
        if anchor is None or offset_ms is None or duration_ms is None:
            return None
        return anchor + (offset_ms + duration_ms) / 1000

    def _handle_canceled(self, evt: Any) -> None:
        reason, details = extract_cancellation(evt)
        error = classify_stt_error(reason, details)
        logger.warning("%s", error.message)
        if self._on_error is not None:
            self._on_error(error)

    def start(self) -> None:
        # 재기동 시 오디오 오프셋도 0부터 다시 세므로 앵커를 비워 첫 write 에서 다시 잡는다.
        self._stream_started_at = None
        self._recognizer.start_continuous_recognition_async().get()

    def write(self, pcm: bytes) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            # 오디오 오프셋 0 은 start() 가 아니라 "첫 오디오가 들어간 순간"이다.
            if self._stream_started_at is None:
                self._stream_started_at = time.monotonic()
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
