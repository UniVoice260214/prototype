"""lexicon 교정이 파이프라인 한 지점에서 자막·번역 양쪽에 반영되는지 확인한다.

SpeechSegment.text 가 단일 출처이므로 _build_segment 에서 한 번 교정하면
번역 입력 / 학생 화면 sourceKo / 교수 화면 확정 자막이 모두 같은 값을 쓴다.
"""

from __future__ import annotations

import pytest

from univoice_worker.lexicon import MajorLexicon
from univoice_worker.models import SpeechSegment, SttFinalResult
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter

LEXICON = MajorLexicon.from_payload(
    {
        "major": "ai",
        "label": "인공지능",
        "index": "major_ai",
        "score_threshold": 0.5,
        "transliterations": {"케이 민즈": "K-평균 군집화", "라그": "RAG"},
        "lexicon": [
            {"pattern": "k-평균 군집화", "canonical": "K-평균 군집화", "reason": "GLOSSARY_TERM"}
        ],
        "pattern_exclusions": {},
        "filler_patterns": [r"\s+그거\s+"],
    }
)


def final(text: str) -> SttFinalResult:
    return SttFinalResult(text=text, confidence=0.9, offset_ms=None, duration_ms=None)


class RecordingTranslator:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        self.seen.append(sentence)
        return {"en-US": f"en:{sentence}"}


class FakeRag:
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        return None


class FakeTts:
    def synthesize(self, locale: str, text: str) -> bytes:
        return b""


class FakePublisher:
    async def push_pcm(self, locale: str, pcm: bytes) -> None:
        return None


def build(corrector):
    segments: list[SpeechSegment] = []
    captions: list[tuple[str, str, SpeechSegment]] = []
    translator = RecordingTranslator()

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

    pipeline = TranslationPipeline(
        session_id="session-1",
        target_locales=["en-US"],
        segmenter=Segmenter(),
        rag=FakeRag(),
        translator=translator,
        tts=FakeTts(),
        publisher=FakePublisher(),
        corrector=corrector,
        on_subtitle=on_subtitle,
        on_segment=on_segment,
    )
    return pipeline, segments, captions, translator


@pytest.mark.asyncio
async def test_correction_reaches_segment_translation_and_caption() -> None:
    pipeline, segments, captions, translator = build(LEXICON.correct_for_display)

    await pipeline.enqueue_stt_final(final("그 케이 민즈랑 라그 얘기했죠."))
    await pipeline.flush_and_stop()

    corrected = "그 K-평균 군집화랑 RAG 얘기했죠."
    # 1) 교수 화면 확정 자막 (on_segment → session_worker._publish_segment_final)
    assert [s.text for s in segments] == [corrected]
    # 2) 번역 입력
    assert translator.seen == [corrected]
    # 3) 학생 화면 원문 (session_worker 가 segment.text 를 sourceKo 로 싣는다)
    assert captions[0][2].text == corrected
    # 교정 전 원문은 회귀 분석을 위해 보존한다
    assert segments[0].raw_text == "그 케이 민즈랑 라그 얘기했죠."


@pytest.mark.asyncio
async def test_correction_does_not_strip_filler_words() -> None:
    """자막 경로에서 교수가 실제로 말한 담화 표지를 지우면 안 된다."""
    pipeline, segments, _, _ = build(LEXICON.correct_for_display)

    await pipeline.enqueue_stt_final(final("그 케이 민즈 그거 쓰죠."))
    await pipeline.flush_and_stop()

    assert "그거" in segments[0].text


@pytest.mark.asyncio
async def test_no_corrector_keeps_text_and_leaves_raw_text_none() -> None:
    pipeline, segments, _, translator = build(None)

    await pipeline.enqueue_stt_final(final("그 케이 민즈랑 라그 얘기했죠."))
    await pipeline.flush_and_stop()

    assert segments[0].text == "그 케이 민즈랑 라그 얘기했죠."
    assert segments[0].raw_text is None


@pytest.mark.asyncio
async def test_corrector_failure_falls_back_to_original_text() -> None:
    def broken(_text: str) -> tuple[str, int]:
        raise RuntimeError("boom")

    pipeline, segments, _, _ = build(broken)

    await pipeline.enqueue_stt_final(final("정상 문장입니다."))
    await pipeline.flush_and_stop()

    # 교정이 터져도 자막은 나가야 한다.
    assert [s.text for s in segments] == ["정상 문장입니다."]
