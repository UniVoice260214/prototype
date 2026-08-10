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


@dataclass(frozen=True)
class TtsJob:
    session_id: str
    segment_id: str
    sequence: int
    locale: str
    text: str


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
