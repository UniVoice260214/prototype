from __future__ import annotations

from typing import Any

import pytest

from univoice_worker.models import SpeechSegment, SttFinalResult, TtsJob
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter


def final(text: str) -> SttFinalResult:
    return SttFinalResult(text=text, confidence=0.9, offset_ms=None, duration_ms=None)


class FakeRag:
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        return None


class FakeTranslator:
    def __init__(self, translations: dict[str, str]) -> None:
        self._translations = translations

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        return dict(self._translations)


class FakeTts:
    async def synthesize_job(self, tts_job: TtsJob) -> bytes:
        return tts_job.text.encode()


class FakePublisher:
    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        return 10

    async def aclose(self) -> None:
        return None


async def _noop_subtitle(
    locale: str,
    text: str,
    segment: SpeechSegment,
    is_final: bool,
    *,
    is_fallback: bool = False,
) -> None:
    return None


def make_pipeline(
    on_transcript: Any,
    *,
    translations: dict[str, str],
    locales: list[str],
) -> TranslationPipeline:
    return TranslationPipeline(
        session_id="session-123",
        target_locales=locales,
        segmenter=Segmenter(),
        rag=FakeRag(),
        translator=FakeTranslator(translations),
        tts=FakeTts(),
        publisher=FakePublisher(),
        on_subtitle=_noop_subtitle,
        on_transcript=on_transcript,
    )


@pytest.mark.asyncio
async def test_transcript_sink_receives_translations_and_fallbacks() -> None:
    records: list[tuple[SpeechSegment, dict[str, dict[str, Any]]]] = []

    async def on_transcript(
        segment: SpeechSegment, entries: dict[str, dict[str, Any]]
    ) -> None:
        records.append((segment, entries))

    pipeline = make_pipeline(
        on_transcript,
        translations={"vi-VN": "xin chao"},
        locales=["vi-VN", "mn-MN"],
    )

    await pipeline.enqueue_stt_final(final("안녕하세요."))
    await pipeline.flush_and_stop()

    assert len(records) == 1
    segment, entries = records[0]
    assert segment.text == "안녕하세요."
    assert entries["vi-VN"] == {"text": "xin chao", "isFallback": False}
    # 번역이 없는 로케일은 한국어 원문 폴백으로 기록되어야 한다.
    assert entries["mn-MN"] == {"text": "안녕하세요.", "isFallback": True}


@pytest.mark.asyncio
async def test_transcript_sink_failure_does_not_block_pipeline() -> None:
    captions: list[str] = []

    async def on_subtitle(
        locale: str,
        text: str,
        segment: SpeechSegment,
        is_final: bool,
        *,
        is_fallback: bool = False,
    ) -> None:
        captions.append(text)

    async def broken_transcript(
        segment: SpeechSegment, entries: dict[str, dict[str, Any]]
    ) -> None:
        raise RuntimeError("redis down")

    pipeline = TranslationPipeline(
        session_id="session-123",
        target_locales=["vi-VN"],
        segmenter=Segmenter(),
        rag=FakeRag(),
        translator=FakeTranslator({"vi-VN": "xin chao"}),
        tts=FakeTts(),
        publisher=FakePublisher(),
        on_subtitle=on_subtitle,
        on_transcript=broken_transcript,
    )

    await pipeline.enqueue_stt_final(final("첫 문장입니다."))
    await pipeline.enqueue_stt_final(final("두 번째 문장입니다."))
    await pipeline.flush_and_stop()

    assert captions == ["xin chao", "xin chao"]


@pytest.mark.asyncio
async def test_no_transcript_sink_keeps_pipeline_working() -> None:
    pipeline = make_pipeline(None, translations={"vi-VN": "ok"}, locales=["vi-VN"])

    await pipeline.enqueue_stt_final(final("문장입니다."))
    await pipeline.flush_and_stop()
