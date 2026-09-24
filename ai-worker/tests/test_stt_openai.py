"""OpenAI Realtime STT 어댑터 단위 테스트 (네트워크 없이).

test_stt_tuning.py 방식대로 순수 함수와 이벤트→콜백 매핑을 검증한다.
"""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from univoice_worker.models import SttFinalResult, SttPartialResult
from univoice_worker.stt_openai import (
    OpenAiRealtimeStt,
    build_transcription_session_payload,
    pseudo_confidence,
    resample_16k_to_24k,
    select_keywords,
    to_iso639_1,
)


# ── 순수 함수 ─────────────────────────────────────────────────────────


def test_language_converts_to_iso639_1() -> None:
    assert to_iso639_1("ko-KR") == "ko"
    assert to_iso639_1("vi-VN") == "vi"
    assert to_iso639_1("") == "ko"  # 빈 값은 한국어 강의 기본


def test_resample_ratio_is_two_thirds() -> None:
    # 10ms @16kHz = 160샘플(320바이트) → 24kHz 에서 240샘플(480바이트)
    pcm = (b"\x01\x00" * 160)
    out = resample_16k_to_24k(pcm)
    assert len(out) == 240 * 2


def test_resample_preserves_constant_signal() -> None:
    import array

    pcm = array.array("h", [1000] * 160).tobytes()
    out = array.array("h")
    out.frombytes(resample_16k_to_24k(pcm))
    assert all(sample == 1000 for sample in out)


def test_resample_empty_is_empty() -> None:
    assert resample_16k_to_24k(b"") == b""


def test_select_keywords_dedupes_and_caps() -> None:
    phrases = ["역전파", "역전파", "LSTM", " lstm ", "", "K-평균 군집화"]
    assert select_keywords(phrases, 2) == ["역전파", "LSTM"]
    assert select_keywords(phrases, 10) == ["역전파", "LSTM", "K-평균 군집화"]


def test_pseudo_confidence_folds_logprobs() -> None:
    logprobs = [SimpleNamespace(logprob=-0.1), SimpleNamespace(logprob=-0.3)]
    value = pseudo_confidence(logprobs)
    assert value is not None
    assert value == pytest.approx(math.exp(-0.2))
    assert pseudo_confidence(None) is None
    assert pseudo_confidence([]) is None
    assert pseudo_confidence([{"logprob": -0.5}]) == pytest.approx(math.exp(-0.5))


def test_session_payload_shape() -> None:
    payload = build_transcription_session_payload(
        model="gpt-4o-transcribe",
        language="ko-KR",
        prompt="한국어 대학 강의. 다음 전공 용어가 등장할 수 있다: 역전파",
        silence_ms=800,
        include_logprobs=True,
    )
    assert payload["type"] == "transcription"
    audio_input = payload["audio"]["input"]
    assert audio_input["format"] == {"type": "audio/pcm", "rate": 24000}
    assert audio_input["transcription"]["model"] == "gpt-4o-transcribe"
    assert audio_input["transcription"]["language"] == "ko"
    # keywords 필드는 gpt-4o-transcribe 미지원(실측) — prompt 로 힌트한다.
    assert "keywords" not in audio_input["transcription"]
    assert "역전파" in audio_input["transcription"]["prompt"]
    # 환청 억제: 노이즈 감소 + VAD 감도 상향 (소음 턴이 발화로 오인되면
    # 모델이 prompt 용어를 지어내는 것이 실측됨).
    assert audio_input["noise_reduction"] == {"type": "near_field"}
    assert audio_input["turn_detection"]["threshold"] == 0.6
    assert audio_input["turn_detection"]["silence_duration_ms"] == 800
    assert payload["include"] == ["item.input_audio_transcription.logprobs"]


def test_session_payload_omits_optionals() -> None:
    payload = build_transcription_session_payload(
        model="gpt-4o-mini-transcribe",
        language="ko-KR",
        prompt="",
        silence_ms=50,  # 하한 보정
        include_logprobs=False,
    )
    assert "prompt" not in payload["audio"]["input"]["transcription"]
    assert payload["audio"]["input"]["turn_detection"]["silence_duration_ms"] == 100
    assert "include" not in payload


def test_prompt_compression_caps_length() -> None:
    from univoice_worker.stt_openai import compress_phrases_to_prompt

    prompt = compress_phrases_to_prompt(["역전파", "LSTM", "매우긴용어" * 100], max_chars=30)
    assert "역전파" in prompt and "LSTM" in prompt
    assert "매우긴용어" not in prompt  # 상한 초과분 절단
    assert compress_phrases_to_prompt([]) == ""


# ── 어댑터 동작 ───────────────────────────────────────────────────────


def make_adapter(**overrides):
    partials: list[SttPartialResult] = []
    finals: list[SttFinalResult] = []
    errors: list[object] = []
    adapter = OpenAiRealtimeStt(
        api_key="sk-test",
        model="gpt-4o-transcribe",
        language="ko-KR",
        phrases=["역전파", "LSTM"],
        on_partial=partials.append,
        on_final=finals.append,
        on_error=errors.append,
        **overrides,
    )
    return adapter, partials, finals, errors


def test_delta_events_accumulate_per_item() -> None:
    adapter, partials, finals, _ = make_adapter()
    adapter.handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.delta",
            item_id="item-1",
            delta="안녕",
        )
    )
    adapter.handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.delta",
            item_id="item-1",
            delta="하세요",
        )
    )
    # Azure partial 과 같은 의미(현재 발화 전체)로 누적 전달된다.
    assert [p.text for p in partials] == ["안녕", "안녕하세요"]
    assert not finals


def test_completed_event_emits_final_with_confidence() -> None:
    adapter, _, finals, _ = make_adapter()
    adapter.handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item-1",
            transcript="안녕하세요.",
            logprobs=[SimpleNamespace(logprob=-0.2)],
        )
    )
    assert len(finals) == 1
    assert finals[0].text == "안녕하세요."
    assert finals[0].confidence == pytest.approx(math.exp(-0.2))
    assert finals[0].offset_ms is None


def test_error_event_maps_to_stt_error() -> None:
    adapter, _, _, errors = make_adapter()
    adapter.handle_event(
        SimpleNamespace(
            type="error",
            error=SimpleNamespace(message="Rate limit reached (429)"),
        )
    )
    assert len(errors) == 1
    assert errors[0].retryable is True  # 429 는 transient


@pytest.mark.asyncio
async def test_write_drops_oldest_on_overflow() -> None:
    adapter, _, _, _ = make_adapter(queue_max_frames=10)
    for i in range(15):
        adapter.write(bytes([i % 256]) * 2)
    assert adapter._audio_q.qsize() == 10
    # 가장 오래된 프레임이 밀려나고 최신이 남는다.
    first = adapter._audio_q.get_nowait()
    assert first != b"\x00\x00"


@pytest.mark.asyncio
async def test_write_after_stop_is_ignored() -> None:
    adapter, _, _, _ = make_adapter()
    adapter.stop()
    adapter.write(b"\x01\x00")
    assert adapter._audio_q.qsize() == 0


def test_keywords_come_from_phrase_list() -> None:
    adapter, _, _, _ = make_adapter()
    assert adapter.keyword_count == 2


def test_speech_started_shows_listening_indicator() -> None:
    """발화 감지 즉시 '인식 중' 표시 — 턴 방식이라 전사 전까지 화면이 침묵하므로."""
    adapter, partials, finals, _ = make_adapter()
    adapter.handle_event(SimpleNamespace(type="input_audio_buffer.speech_started"))
    assert [p.text for p in partials] == ["…"]
    assert not finals


def test_low_confidence_transcript_is_dropped_as_hallucination() -> None:
    """소음 턴 환청(프롬프트 용어 지어내기)은 자막·TTS 로 내보내지 않는다."""
    adapter, partials, finals, _ = make_adapter(min_confidence=0.5)
    adapter.handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item-1",
            transcript="역전파 LSTM 역전파",
            logprobs=[SimpleNamespace(logprob=-2.0)],  # exp(-2)≈0.14 < 0.5
        )
    )
    assert not finals
    # 표시 중이던 "인식 중"을 지우는 빈 partial 이 나간다.
    assert partials[-1].text == ""


def test_confidence_guard_disabled_when_zero() -> None:
    adapter, _, finals, _ = make_adapter(min_confidence=0.0)
    adapter.handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item-1",
            transcript="역전파",
            logprobs=[SimpleNamespace(logprob=-2.0)],
        )
    )
    assert len(finals) == 1  # 가드 꺼짐 — 저신뢰여도 통과


def test_empty_transcript_clears_indicator() -> None:
    adapter, partials, finals, _ = make_adapter()
    adapter.handle_event(SimpleNamespace(type="input_audio_buffer.speech_started"))
    adapter.handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item-1",
            transcript="",
            logprobs=None,
        )
    )
    assert not finals
    assert partials[-1].text == ""
