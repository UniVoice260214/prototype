"""번역 실패 시 재요청 검증.

- 실패(예외·빈 번역)한 세그먼트는 한 번 재요청하고, 그래도 실패할 때만 원문 폴백.
- 재요청하는 동안 뒤 세그먼트는 병렬로 번역되어 대기하다가, 앞 세그먼트가
  끝나는 즉시 sequence 순서대로 나간다.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from univoice_worker.models import SpeechSegment
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter

from fakes import FakeAudioPublisher, FakeRagClient, FakeTts, stt_final

LOCALES = ["vi-VN", "zh-CN"]


class FakeApiError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class ScriptedTranslator:
    """문장별로 시도 순서에 따른 동작을 정한다.

    script[sentence] = [동작1, 동작2, ...] — 동작은 Exception(던짐), "empty"(빈 번역),
    "hang"(멈춤), dict(그대로 반환), None(정상 번역). 스크립트가 없거나 다 쓰면 정상.
    """

    def __init__(self, script: dict[str, list[Any]], *, delay: float = 0.02) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.delay = delay
        self.calls: list[str] = []
        self.events: list[tuple[str, str, float]] = []

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        self.calls.append(sentence)
        self.events.append(("start", sentence, time.monotonic()))
        await asyncio.sleep(self.delay)
        steps = self.script.get(sentence) or []
        action = steps.pop(0) if steps else None
        try:
            if isinstance(action, BaseException):
                raise action
            if action == "hang":
                await asyncio.sleep(60)
            if action == "empty":
                return {loc: "" for loc in LOCALES}
            if isinstance(action, dict):
                return action
            return {loc: f"{loc}:{sentence}" for loc in LOCALES}
        finally:
            self.events.append(("end", sentence, time.monotonic()))


class StreamingFlakyTranslator:
    """첫 시도: vi-VN 만 스트리밍으로 확정한 뒤 끊김. 두 번째: 전부 성공."""

    def __init__(self) -> None:
        self.calls = 0

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    async def translate(self, sentence, rag_context, *, on_locale=None) -> dict[str, str]:
        self.calls += 1
        if self.calls == 1:
            if on_locale is not None:
                on_locale("vi-VN", "vi:first")
            raise ConnectionError("stream dropped")
        if on_locale is not None:
            on_locale("vi-VN", "vi:second")
            on_locale("zh-CN", "zh:second")
        return {"vi-VN": "vi:second", "zh-CN": "zh:second"}


def make_pipeline(translator: Any, **kwargs: Any):
    captions: list[tuple[str, str, int, bool]] = []
    transcripts: list[tuple[int, dict]] = []
    emitted_at: dict[int, float] = {}

    async def on_subtitle(locale, text, segment, is_final, *, is_fallback=False) -> None:
        captions.append((locale, text, segment.sequence, is_fallback))
        emitted_at.setdefault(segment.sequence, time.monotonic())

    async def on_transcript(segment: SpeechSegment, entries: dict) -> None:
        transcripts.append((segment.sequence, entries))

    params: dict[str, Any] = {
        "translate_max_concurrency": 3,
        "translate_retry_delay_ms": 10,
        "translate_retry_timeout_sec": 1.0,
    }
    params.update(kwargs)
    pipeline = TranslationPipeline(
        session_id="sess-retry",
        target_locales=LOCALES,
        segmenter=Segmenter(),
        rag=FakeRagClient(),
        translator=translator,
        tts=FakeTts(),
        publisher=FakeAudioPublisher(),
        on_subtitle=on_subtitle,
        on_transcript=on_transcript,
        **params,
    )
    return pipeline, captions, transcripts, emitted_at


def by_seq(captions, locale):
    return [(seq, text, fb) for loc, text, seq, fb in captions if loc == locale]


@pytest.mark.asyncio
async def test_retry_recovers_and_next_sentence_was_translated_in_parallel() -> None:
    translator = ScriptedTranslator({"하나.": [TimeoutError("slow")]}, delay=0.05)
    pipeline, captions, transcripts, _ = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나. 둘."))
    await pipeline.flush_and_stop()

    # 첫 문장은 재요청으로 번역 성공 — 폴백 없음
    assert translator.calls.count("하나.") == 2
    assert by_seq(captions, "vi-VN") == [
        (1, "vi-VN:하나.", False),
        (2, "vi-VN:둘.", False),
    ]
    assert [seq for seq, _ in transcripts] == [1, 2]
    # 둘째 문장 번역은 첫 문장 재요청이 끝나기 전에 이미 끝나 있었다 (병렬)
    end_two = next(t for kind, s, t in translator.events if kind == "end" and s == "둘.")
    last_end_one = max(t for kind, s, t in translator.events if kind == "end" and s == "하나.")
    assert end_two < last_end_one


@pytest.mark.asyncio
async def test_retry_failure_falls_back_then_ready_sentence_follows_immediately() -> None:
    translator = ScriptedTranslator(
        {"하나.": [TimeoutError("slow"), FakeApiError(429)]}, delay=0.05
    )
    pipeline, captions, transcripts, emitted_at = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나. 둘. 셋."))
    await pipeline.flush_and_stop()

    assert translator.calls.count("하나.") == 2
    assert by_seq(captions, "zh-CN") == [
        (1, "하나.", True),  # 재요청까지 실패 → 원문
        (2, "zh-CN:둘.", False),
        (3, "zh-CN:셋.", False),
    ]
    assert transcripts[0][1]["zh-CN"] == {"text": "하나.", "isFallback": True}
    # 뒤 문장들은 미리 번역돼 있어 원문 폴백 직후 바로 나간다
    assert emitted_at[2] - emitted_at[1] < 0.03
    assert emitted_at[3] - emitted_at[2] < 0.03


@pytest.mark.asyncio
async def test_empty_translation_is_retried() -> None:
    translator = ScriptedTranslator({"하나.": ["empty"]})
    pipeline, captions, _, _ = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나."))
    await pipeline.flush_and_stop()

    assert translator.calls == ["하나.", "하나."]
    assert by_seq(captions, "vi-VN") == [(1, "vi-VN:하나.", False)]


@pytest.mark.asyncio
async def test_retry_only_fills_missing_locale() -> None:
    # 첫 시도에서 vi-VN 만 나오고 zh-CN 은 빈칸 → 재요청 결과로 zh-CN 만 채운다
    translator = ScriptedTranslator(
        {"하나.": [{"vi-VN": "vi:first", "zh-CN": ""}, {"vi-VN": "vi:second", "zh-CN": "zh:second"}]}
    )
    pipeline, captions, _, _ = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나."))
    await pipeline.flush_and_stop()

    assert by_seq(captions, "vi-VN") == [(1, "vi:first", False)]
    assert by_seq(captions, "zh-CN") == [(1, "zh:second", False)]


@pytest.mark.asyncio
async def test_streamed_locale_is_kept_and_retry_fills_the_rest() -> None:
    translator = StreamingFlakyTranslator()
    pipeline, captions, _, _ = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나."))
    await pipeline.flush_and_stop()

    assert translator.calls == 2
    # 이미 학생에게 나간 로케일은 바뀌지 않는다
    assert by_seq(captions, "vi-VN") == [(1, "vi:first", False)]
    assert by_seq(captions, "zh-CN") == [(1, "zh:second", False)]


@pytest.mark.asyncio
async def test_non_retryable_error_falls_back_without_retry() -> None:
    translator = ScriptedTranslator({"하나.": [FakeApiError(401)]})
    pipeline, captions, _, _ = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나."))
    await pipeline.flush_and_stop()

    assert translator.calls == ["하나."]
    assert by_seq(captions, "vi-VN") == [(1, "하나.", True)]


@pytest.mark.asyncio
async def test_retries_disabled_restores_immediate_fallback() -> None:
    translator = ScriptedTranslator({"하나.": [TimeoutError("slow")]})
    pipeline, captions, _, _ = make_pipeline(translator, translate_max_retries=0)

    await pipeline.enqueue_stt_final(stt_final("하나."))
    await pipeline.flush_and_stop()

    assert translator.calls == ["하나."]
    assert by_seq(captions, "vi-VN") == [(1, "하나.", True)]


@pytest.mark.asyncio
async def test_hanging_retry_is_cut_by_retry_timeout() -> None:
    translator = ScriptedTranslator({"하나.": [TimeoutError("slow"), "hang"]})
    pipeline, captions, _, _ = make_pipeline(translator, translate_retry_timeout_sec=0.2)

    started = time.monotonic()
    await pipeline.enqueue_stt_final(stt_final("하나. 둘."))
    await pipeline.flush_and_stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, elapsed
    assert by_seq(captions, "vi-VN") == [
        (1, "하나.", True),
        (2, "vi-VN:둘.", False),
    ]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (None, "empty"),
        (asyncio.TimeoutError(), "timeout"),
        (type("APITimeoutError", (Exception,), {})(), "timeout"),
        (FakeApiError(429), "rate_limit"),
        (FakeApiError(503), "http_503"),
        (ConnectionError("x"), "connection"),
        (ValueError("x"), "ValueError"),
    ],
)
def test_failure_reason_classification(error, reason) -> None:
    assert TranslationPipeline._classify_translate_failure(error) == reason
