"""Typed models shared by STT, segmentation, delivery, and status events."""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SttPartialResult:
    text: str


@dataclass(frozen=True)
class SttFinalResult:
    text: str
    confidence: float | None
    offset_ms: int | None
    duration_ms: int | None
    # ── 지연 계측용 (없어도 파이프라인은 동일하게 동작한다) ──
    # received_at: STT final 이 워커에 도착한 시각 (time.monotonic).
    # speech_end_at: 오디오 타임라인(offset+duration)으로 역산한 "실제 발화가 끝난"
    #   시각 (time.monotonic). 이 둘의 차이가 STT 엔진의 침묵 대기 + 인식 + 왕복이다.
    #   오디오 오프셋을 주지 않는 프로바이더(OpenAI 턴 방식)에서는 None 이다.
    received_at: float | None = None
    speech_end_at: float | None = None


@dataclass(frozen=True)
class SpeechSegment:
    session_id: str
    segment_id: str
    sequence: int
    text: str                      # lexicon 교정이 적용된 텍스트. 자막·번역의 단일 출처.
    stt_confidence: float | None
    started_at: float | None
    ended_at: float
    raw_text: str | None = None    # 교정 전 STT 원문 (회귀 분석·QA용)
    # 지연 계측용. 이 세그먼트를 완성시킨 마지막 STT final 기준 (time.monotonic).
    stt_received_at: float | None = None
    speech_end_at: float | None = None


@dataclass(frozen=True)
class TtsJob:
    session_id: str
    segment_id: str
    sequence: int
    locale: str
    text: str
    # 지연 계측용 (time.monotonic). dedupe 키는 session/segment/locale 로만 만들므로
    # 이 필드가 늘어도 중복 판정에는 영향이 없다.
    speech_end_at: float | None = None
    enqueued_at: float | None = None


AudioStatusType = Literal["audio.started", "audio.completed", "audio.failed"]


@dataclass(frozen=True)
class AudioStatus:
    type: AudioStatusType
    session_id: str
    segment_id: str
    sequence: int
    locale: str
    duration_ms: int | None
    error_code: str | None
    timestamp: float


@dataclass(frozen=True)
class TtsResult:
    job: TtsJob
    pcm: bytes


class TtsException(Exception):
    """Typed TTS failure that preserves retry policy and a stable error code."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.message = message
        self.original = original


def audio_status_payload(status: AudioStatus) -> dict[str, Any]:
    """Serialize an audio status dataclass to the DataChannel payload shape."""
    return {
        "type": status.type,
        "sessionId": status.session_id,
        "segmentId": status.segment_id,
        "sequence": status.sequence,
        "locale": status.locale,
        "durationMs": status.duration_ms,
        "errorCode": status.error_code,
        "ts": status.timestamp,
    }
