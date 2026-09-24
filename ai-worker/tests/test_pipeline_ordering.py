from __future__ import annotations

import asyncio

import pytest

from univoice_worker.models import SpeechSegment, SttFinalResult
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter


def final(text: str, confidence: float | None = None) -> SttFinalResult:
    return SttFinalResult(
        text=text,
        confidence=confidence,
        offset_ms=None,
        duration_ms=None,
    )


class FakeRag:
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        return None


class FakeTranslator:
    def __init__(self, *, fail_texts: set[str] | None = None) -> None:
        self.fail_texts = fail_texts or set()
        self.seen: list[str] = []

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        self.seen.append(sentence)
        if sentence in self.fail_texts:
            raise RuntimeError(f"translation failed for {sentence}")
        return {"en-US": f"en:{sentence}"}


class FakeTts:
    def synthesize(self, locale: str, text: str) -> bytes:
        return f"{locale}:{text}".encode("utf-8")


class FakePublisher:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, bytes]] = []

    async def push_pcm(self, locale: str, pcm: bytes) -> None:
        self.pushed.append((locale, pcm))


def make_pipeline(
    *,
    translator: FakeTranslator | None = None,
    segmenter: Segmenter | None = None,
) -> tuple[
    TranslationPipeline,
    list[SpeechSegment],
    list[tuple[str, str, SpeechSegment]],
    list[bool],
]:
    segments: list[SpeechSegment] = []
    captions: list[tuple[str, str, SpeechSegment]] = []
    fallback_flags: list[bool] = []

    async def on_segment(segment: SpeechSegment) -> None:
        segments.append(segment)

    async def on_subtitle(
        locale: str,
        text: str,
        segment: SpeechSegment,
        is_final: bool,
        *,
        is_fallback: bool = False,
    ) -> None:
        captions.append((locale, text, segment))
        fallback_flags.append(is_fallback)

    pipeline = TranslationPipeline(
        session_id="session-123",
        target_locales=["en-US"],
        segmenter=segmenter or Segmenter(),
        rag=FakeRag(),
        translator=translator or FakeTranslator(),
        tts=FakeTts(),
        publisher=FakePublisher(),
        on_subtitle=on_subtitle,
        on_segment=on_segment,
        queue_max_size=10,
        enqueue_timeout_ms=50,
    )
    return pipeline, segments, captions, fallback_flags


@pytest.mark.asyncio
async def test_fast_stt_finals_keep_sequence_order() -> None:
    pipeline, segments, captions, fallback_flags = make_pipeline()

    await asyncio.gather(
        pipeline.enqueue_stt_final(final("one.", 0.9)),
        pipeline.enqueue_stt_final(final("two.", 0.8)),
        pipeline.enqueue_stt_final(final("three.", 0.7)),
    )
    await pipeline.flush_and_stop()

    assert [segment.sequence for segment in segments] == [1, 2, 3]
    # segment_id 는 {session}-{run_id}-seg-{seq} — run_id 는 워커 런마다 달라
    # 재기동 시 이전 런과의 dedupe/DB 충돌을 막는다.
    run_id = pipeline._run_id
    assert [segment.segment_id for segment in segments] == [
        f"session-123-{run_id}-seg-000001",
        f"session-123-{run_id}-seg-000002",
        f"session-123-{run_id}-seg-000003",
    ]
    assert [caption[2].sequence for caption in captions] == [1, 2, 3]


@pytest.mark.asyncio
async def test_one_segment_failure_does_not_stop_next_segment() -> None:
    translator = FakeTranslator(fail_texts={"bad."})
    pipeline, segments, captions, fallback_flags = make_pipeline(translator=translator)

    await pipeline.enqueue_stt_final(final("good."))
    await pipeline.enqueue_stt_final(final("bad."))
    await pipeline.enqueue_stt_final(final("after."))
    await pipeline.flush_and_stop()

    assert [segment.sequence for segment in segments] == [1, 2, 3]
    # 번역이 실패해도 문장이 사라지면 안 된다. 한국어 원문을 폴백 자막으로 내보낸다.
    # (예전에는 "bad." 가 자막 없이 통째로 소실됐다.)
    assert [text for _, text, _ in captions] == ["en:good.", "bad.", "en:after."]
    assert fallback_flags == [False, True, False]


@pytest.mark.asyncio
async def test_flush_and_stop_drains_residual_segment_and_queue() -> None:
    pipeline, segments, captions, fallback_flags = make_pipeline()

    await pipeline.enqueue_stt_final(final("residual without punctuation", confidence=0.6))
    await pipeline.flush_and_stop()
    await pipeline.flush_and_stop()

    assert [segment.text for segment in segments] == ["residual without punctuation"]
    assert [caption[2].segment_id for caption in captions] == [
        f"session-123-{pipeline._run_id}-seg-000001"
    ]
    assert pipeline._queue.empty()
