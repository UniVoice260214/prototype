"""STT 취소 사유 분류 회귀 테스트.

예전 분류기는 "key", "invalid", "language" 같은 짧은 부분문자열을 permanent 로
보고 transient 보다 **먼저** 검사했다. 그래서 "invalid session state" 같은 일시적
메시지가 재시도 불가로 판정돼, 세션 중간에 STT 가 조용히 영구 정지했다.
"""

from __future__ import annotations

import pytest

from univoice_worker.stt import classify_stt_error


@pytest.mark.parametrize(
    "details",
    [
        "invalid session state",
        "websocket upgrade invalid",
        "Connection was reset by peer",
        "recognition timeout",
        "service unavailable (503)",
        "temporary network failure",
        "connection closed unexpectedly",
    ],
)
def test_transient_messages_stay_retryable(details: str) -> None:
    error = classify_stt_error("CancelledByService", details)
    assert error.retryable is True
    assert error.category == "transient"


@pytest.mark.parametrize(
    "details",
    [
        "Authentication failed for the subscription",
        "Forbidden",
        "quota exceeded for this resource",
        "unsupported language: ko-XX",
    ],
)
def test_genuine_config_errors_are_permanent(details: str) -> None:
    error = classify_stt_error("CancelledByService", details)
    assert error.retryable is False
    assert error.category == "permanent"
    assert error.error_code == "STT_PERMANENT_ERROR"


def test_unknown_reason_defaults_to_retryable() -> None:
    """분류할 수 없으면 재시도 쪽으로 기운다. 잘못 죽는 손해가 더 크다."""
    error = classify_stt_error("SomethingNew", "")
    assert error.retryable is True
    assert error.error_code == "STT_CANCELED"


def test_message_preserves_reason_and_details() -> None:
    error = classify_stt_error("CancelledByService", "recognition timeout")
    assert "CancelledByService" in error.message
    assert "recognition timeout" in error.message
    assert error.details == "recognition timeout"


# ── cancellation_details 추출 (401 인증 실패 실장애 회귀) ────────────────

from univoice_worker.stt import extract_cancellation


class _FakeCancellationDetails:
    def __init__(self, reason, error_code, error_details):
        self.reason = reason
        self.error_code = error_code
        self.error_details = error_details


class _FakeCanceledEvent:
    def __init__(self, details):
        self.cancellation_details = details


def test_extract_cancellation_reads_sdk_cancellation_details() -> None:
    evt = _FakeCanceledEvent(
        _FakeCancellationDetails(
            reason="CancellationReason.Error",
            error_code="CancellationErrorCode.AuthenticationFailure",
            error_details="WebSocket upgrade failed: Authentication error (401).",
        )
    )

    reason, details = extract_cancellation(evt)

    assert reason == "CancellationReason.Error"
    assert "401" in details
    assert "AuthenticationFailure" in details
    # 401 은 permanent 로 분류되어 무의미한 재시도를 멈춰야 한다.
    error = classify_stt_error(reason, details)
    assert error.retryable is False


def test_extract_cancellation_falls_back_to_event_attrs() -> None:
    class _Legacy:
        reason = "canceled"
        error_details = "timeout"

    reason, details = extract_cancellation(_Legacy())

    assert reason == "canceled"
    assert details == "timeout"
