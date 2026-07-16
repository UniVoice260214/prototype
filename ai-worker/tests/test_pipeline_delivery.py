from __future__ import annotations

import asyncio

import pytest

from univoice_worker.models import AudioStatus, SpeechSegment, SttFinalResult, TtsJob
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


class FakePublisher:
    def __init__(self) -> None:
        self.closed = False
        self.published: list[tuple[str, bytes]] = []

    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        self.published.append((locale, pcm))
        return 10

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_caption_final_is_sent_before_tts_completion() -> None:
    caption_sent = asyncio.Event()
    release_tts = asyncio.Event()
    captions: list[tuple[str, str, SpeechSegment]] = []
    statuses: list[AudioStatus] = []

    class BlockingTts:
        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            await release_tts.wait()
            return b"\0" * 320

    async def on_subtitle(locale: str, text: str, segment: SpeechSegment, is_final: bool) -> None:
        captions.append((locale, text, segment))
        caption_sent.set()

    async def on_audio_status(status: AudioStatus) -> None:
        statuses.append(status)

    pipeline = TranslationPipeline(
        session_id="session-123",
        target_locales=["vi-VN"],
        segmenter=Segmenter(),
        rag=FakeRag(),
        translator=FakeTranslator({"vi-VN": "xin chao"}),
        tts=BlockingTts(),
        publisher=FakePublisher(),
        on_subtitle=on_subtitle,
        on_audio_status=on_audio_status,
    )

    await pipeline.enqueue_stt_final(final("안녕하세요."))
    await asyncio.wait_for(caption_sent.wait(), timeout=1)

    assert captions
    assert not any(status.type == "audio.completed" for status in statuses)

    release_tts.set()
    await pipeline.flush_and_stop()

    completed = next(status for status in statuses if status.type == "audio.completed")
    assert captions[0][2].segment_id == completed.segment_id
    assert captions[0][2].sequence == completed.sequence


@pytest.mark.asyncio
async def test_missing_locale_translation_fails_only_that_locale() -> None:
    captions: list[tuple[str, str, SpeechSegment]] = []
    statuses: list[AudioStatus] = []
    publisher = FakePublisher()

    class GoodTts:
        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            return tts_job.text.encode()

    async def on_subtitle(locale: str, text: str, segment: SpeechSegment, is_final: bool) -> None:
        captions.append((locale, text, segment))

    async def on_audio_status(status: AudioStatus) -> None:
        statuses.append(status)

    pipeline = TranslationPipeline(
        session_id="session-123",
        target_locales=["vi-VN", "zh-CN"],
        segmenter=Segmenter(),
        rag=FakeRag(),
        translator=FakeTranslator({"vi-VN": "xin chao"}),
        tts=GoodTts(),
        publisher=publisher,
        on_subtitle=on_subtitle,
        on_audio_status=on_audio_status,
    )

    await pipeline.enqueue_stt_final(final("안녕하세요."))
    await pipeline.flush_and_stop()

    assert [(locale, text) for locale, text, _ in captions] == [("vi-VN", "xin chao")]
    assert ("audio.failed", "zh-CN", "TRANSLATION_MISSING") in [
        (status.type, status.locale, status.error_code) for status in statuses
    ]
    assert ("audio.completed", "vi-VN", None) in [
        (status.type, status.locale, status.error_code) for status in statuses
    ]
    assert publisher.published == [("vi-VN", b"xin chao")]


@pytest.mark.asyncio
async def test_caption_and_audio_status_share_segment_identity() -> None:
    captions: list[tuple[str, str, SpeechSegment]] = []
    statuses: list[AudioStatus] = []

    class GoodTts:
        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            return b"ok"

    async def on_subtitle(locale: str, text: str, segment: SpeechSegment, is_final: bool) -> None:
        captions.append((locale, text, segment))

    async def on_audio_status(status: AudioStatus) -> None:
        statuses.append(status)

    pipeline = TranslationPipeline(
        session_id="session-123",
        target_locales=["vi-VN"],
        segmenter=Segmenter(),
        rag=FakeRag(),
        translator=FakeTranslator({"vi-VN": "xin chao"}),
        tts=GoodTts(),
        publisher=FakePublisher(),
        on_subtitle=on_subtitle,
        on_audio_status=on_audio_status,
    )

    await pipeline.enqueue_stt_final(final("안녕하세요."))
    await pipeline.flush_and_stop()

    segment = captions[0][2]
    assert {
        (status.segment_id, status.sequence)
        for status in statuses
        if status.type in {"audio.started", "audio.completed"}
    } == {(segment.segment_id, segment.sequence)}
