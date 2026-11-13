"""번역 스트리밍 + 로케일별 조기 확정 검증."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from univoice_worker.config import WorkerConfig
from univoice_worker.models import SpeechSegment, TtsJob
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter
from univoice_worker.translator import LocaleStreamParser, Translator

from fakes import FakeAudioPublisher, FakeRagClient, stt_final

LOCALES = ["vi-VN", "zh-CN"]


# ── 파서 ─────────────────────────────────────────────────────────────────


def feed_all(parser: LocaleStreamParser, pieces: list[str]) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for index, piece in enumerate(pieces):
        for key, value in parser.feed(piece):
            out.append((index, key, value))
    return out


def test_parser_emits_each_locale_as_soon_as_its_value_closes() -> None:
    parser = LocaleStreamParser(LOCALES)
    pieces = ['{"zh', '-CN": "线', '粒体"', ', "vi-VN"', ': "Ty ', 'thể"', "}"]
    assert feed_all(parser, pieces) == [(2, "zh-CN", "线粒体"), (5, "vi-VN", "Ty thể")]


def test_parser_handles_escapes_and_unicode_split_across_chunks() -> None:
    parser = LocaleStreamParser(LOCALES)
    raw = json.dumps({"vi-VN": 'nói "xin chào"\\ \n', "zh-CN": "é"}, ensure_ascii=True)
    # 한 글자씩 흘려 이스케이프가 청크 경계에서 잘리는 경우를 전부 만든다.
    out = feed_all(parser, list(raw))
    assert [(k, v) for _, k, v in out] == [("vi-VN", 'nói "xin chào"\\ \n'), ("zh-CN", "é")]


def test_parser_ignores_unknown_keys_and_stops_on_non_string_values() -> None:
    parser = LocaleStreamParser(LOCALES)
    assert parser.feed('{"other": "x", "vi-VN": "a", "zh-CN": 3}') == [("vi-VN", "a")]
    assert parser.feed(', "zh-CN": "late"}') == []


# ── Translator 스트리밍 ──────────────────────────────────────────────────


def config(**overrides: Any) -> WorkerConfig:
    base = WorkerConfig(
        redis_url="redis://localhost:6379",
        livekit_url="ws://livekit",
        livekit_api_key="key",
        livekit_api_secret="secret",
        azure_speech_key="speech",
        azure_speech_region="region",
        stt_language="ko-KR",
        translate_provider="openai",
        openai_api_key="test-key",
        openai_model="gpt-test",
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
        azure_openai_api_version="",
    )
    return replace(base, **overrides)


def chunk(content: str | None) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


def full_response(data: dict[str, str]) -> Any:
    content = json.dumps(data, ensure_ascii=False)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeStream:
    def __init__(
        self,
        pieces: list[str],
        *,
        delays: list[float] | None = None,
        fail_at: int | None = None,
        hang_at: int | None = None,
    ) -> None:
        self.pieces = pieces
        self.delays = delays or [0.0] * len(pieces)
        self.fail_at = fail_at
        self.hang_at = hang_at
        self.yielded = 0
        self.closed = False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        # Azure 가 보내는 choices 없는 청크(콘텐츠 필터 결과)도 섞는다.
        yield SimpleNamespace(choices=[])
        for index, piece in enumerate(self.pieces):
            if index == self.hang_at:
                await asyncio.Event().wait()
            if index == self.fail_at:
                raise RuntimeError("stream broken")
            await asyncio.sleep(self.delays[index])
            self.yielded = index + 1
            yield chunk(piece)

    async def close(self) -> None:
        self.closed = True


class FakeCompletions:
    def __init__(self, stream_factory, full: dict[str, str] | None = None) -> None:
        self.stream_factory = stream_factory
        self.full = full or {"vi-VN": "vi-full", "zh-CN": "zh-full"}
        self.calls: list[bool] = []
        self.streams: list[FakeStream] = []

    async def create(self, **kwargs: Any) -> Any:
        stream = bool(kwargs.get("stream"))
        self.calls.append(stream)
        if stream:
            s = self.stream_factory(kwargs)
            self.streams.append(s)
            return s
        return full_response(self.full)


def make_translator(completions: Any, **cfg: Any) -> Translator:
    translator = Translator(config(**cfg), LOCALES, [])
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return translator


ZH_FIRST = ['{"zh-CN": "你好"', ', "vi-VN": "xin ', 'chào"}']


@pytest.mark.asyncio
async def test_translate_stream_calls_on_locale_before_stream_finishes() -> None:
    completions = FakeCompletions(lambda kw: FakeStream(ZH_FIRST))
    translator = make_translator(completions)
    seen: list[tuple[str, str, int]] = []
    first_tokens: list[int] = []

    def on_locale(locale: str, text: str) -> None:
        seen.append((locale, text, completions.streams[0].yielded))

    result = await translator.translate(
        "안녕", None, on_locale=on_locale, on_first_token=lambda: first_tokens.append(1)
    )

    assert result == {"vi-VN": "xin chào", "zh-CN": "你好"}
    # zh-CN 은 첫 청크만 받은 시점에 이미 넘어갔다 (전체 JSON 대기 없음).
    assert seen == [("zh-CN", "你好", 1), ("vi-VN", "xin chào", 3)]
    assert first_tokens == [1]
    assert completions.calls == [True]
    assert completions.streams[0].closed
    assert translator.history == [("안녕", "xin chào")]


@pytest.mark.asyncio
async def test_translate_falls_back_to_non_streaming_when_stream_unsupported() -> None:
    def unsupported(kwargs: dict[str, Any]) -> Any:
        raise TypeError("create() got an unexpected keyword argument 'stream'")

    completions = FakeCompletions(unsupported)
    translator = make_translator(completions)
    seen: list[str] = []

    assert await translator.translate("안녕", None, on_locale=lambda l, t: seen.append(l)) == {
        "vi-VN": "vi-full",
        "zh-CN": "zh-full",
    }
    # 두 번째 호출부터는 스트리밍을 시도하지 않는다.
    await translator.translate("다시", None)
    assert completions.calls == [True, False, False]
    assert seen == []


@pytest.mark.asyncio
async def test_streaming_disabled_by_config_uses_single_call() -> None:
    completions = FakeCompletions(lambda kw: FakeStream(ZH_FIRST))
    translator = make_translator(completions, translate_streaming=False)

    assert await translator.translate("안녕", None) == {"vi-VN": "vi-full", "zh-CN": "zh-full"}
    assert completions.calls == [False]


@pytest.mark.asyncio
async def test_mid_stream_failure_refetches_but_keeps_already_emitted_locale() -> None:
    completions = FakeCompletions(lambda kw: FakeStream(ZH_FIRST, fail_at=1))
    translator = make_translator(completions)
    seen: list[str] = []

    result = await translator.translate("안녕", None, on_locale=lambda l, t: seen.append(l))

    assert seen == ["zh-CN"]
    # 이미 학생에게 나간 zh-CN 값은 유지, 나머지는 비스트리밍 재요청 결과.
    assert result == {"vi-VN": "vi-full", "zh-CN": "你好"}
    assert completions.calls == [True, False]
    assert completions.streams[0].closed


@pytest.mark.asyncio
async def test_stream_timeout_raises_after_partial_emit() -> None:
    completions = FakeCompletions(lambda kw: FakeStream(ZH_FIRST, hang_at=1))
    translator = make_translator(completions, translate_timeout_sec=0.2)
    seen: list[str] = []

    with pytest.raises(asyncio.TimeoutError):
        await translator.translate("안녕", None, on_locale=lambda l, t: seen.append(l))
    assert seen == ["zh-CN"]
    assert completions.streams[0].closed
    assert translator.history == []


# ── 파이프라인 조기 발행 ─────────────────────────────────────────────────


class RecordingTtsQueue:
    def __init__(self) -> None:
        self.jobs: list[TtsJob] = []

    async def start(self) -> None:
        return None

    async def enqueue(self, job: TtsJob) -> bool:
        self.jobs.append(job)
        return True

    async def flush_and_stop(self) -> None:
        return None


def make_pipeline(translator: Any, tts_queue: RecordingTtsQueue | None = None):
    captions: list[tuple[str, str, int, float]] = []
    transcripts: list[tuple[int, dict]] = []

    async def on_subtitle(locale, text, segment, is_final, *, is_fallback=False) -> None:
        captions.append((locale, text, segment.sequence, time.monotonic()))

    async def on_transcript(segment: SpeechSegment, entries: dict) -> None:
        transcripts.append((segment.sequence, entries))

    pipeline = TranslationPipeline(
        session_id="sess-stream",
        target_locales=LOCALES,
        segmenter=Segmenter(),
        rag=FakeRagClient(),
        translator=translator,
        tts=None,
        publisher=FakeAudioPublisher(),
        on_subtitle=on_subtitle,
        on_transcript=on_transcript,
        tts_queue=tts_queue or RecordingTtsQueue(),
    )
    return pipeline, captions, transcripts


class GatedStreamingTranslator:
    """on_locale 을 원하는 순서/시점에 부르는 스트리밍 번역기 fake."""

    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}
        self.plans: dict[str, list[tuple[str, str]]] = {}

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    def gate(self, sentence: str) -> asyncio.Event:
        return self.gates.setdefault(sentence, asyncio.Event())

    async def translate(self, sentence, rag_context, *, on_locale=None, on_first_token=None):
        if on_first_token:
            on_first_token()
        plan = self.plans[sentence]
        first_locale, first_text = plan[0]
        on_locale(first_locale, first_text)
        await self.gate(sentence).wait()
        for locale, text in plan[1:]:
            on_locale(locale, text)
        return dict(plan)


async def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_locale_completed_first_is_emitted_before_the_others() -> None:
    translator = GatedStreamingTranslator()
    translator.plans["하나."] = [("zh-CN", "zh:하나"), ("vi-VN", "vi:하나")]
    tts_queue = RecordingTtsQueue()
    pipeline, captions, transcripts = make_pipeline(translator, tts_queue)

    await pipeline.enqueue_stt_final(stt_final("하나."))
    # vi-VN 은 아직 완성 전인데 zh-CN 자막과 TTS 는 이미 나갔다.
    await wait_until(lambda: len(captions) == 1)
    assert captions[0][:3] == ("zh-CN", "zh:하나", 1)
    assert [(j.locale, j.text) for j in tts_queue.jobs] == [("zh-CN", "zh:하나")]
    assert transcripts == []  # 저장은 세그먼트가 모두 끝난 뒤 한 번

    translator.gate("하나.").set()
    await pipeline.flush_and_stop()

    assert [(c[0], c[2]) for c in captions] == [("zh-CN", 1), ("vi-VN", 1)]
    assert [j.locale for j in tts_queue.jobs] == ["zh-CN", "vi-VN"]
    assert transcripts == [
        (
            1,
            {
                "vi-VN": {"text": "vi:하나", "isFallback": False},
                "zh-CN": {"text": "zh:하나", "isFallback": False},
            },
        )
    ]


@pytest.mark.asyncio
async def test_early_locale_does_not_break_cross_segment_order() -> None:
    translator = GatedStreamingTranslator()
    translator.plans["하나."] = [("zh-CN", "zh:하나"), ("vi-VN", "vi:하나")]
    translator.plans["둘."] = [("vi-VN", "vi:둘"), ("zh-CN", "zh:둘")]
    translator.gate("둘.").set()  # 둘째 문장은 즉시 전부 완성
    pipeline, captions, transcripts = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나. 둘."))
    await wait_until(lambda: len(captions) == 1)
    await asyncio.sleep(0.05)
    # 둘째는 번역이 끝났어도 첫째가 다 나가기 전에는 나가지 않는다.
    assert [(c[0], c[2]) for c in captions] == [("zh-CN", 1)]

    translator.gate("하나.").set()
    await pipeline.flush_and_stop()

    assert [c[2] for c in captions] == [1, 1, 2, 2]
    for locale in LOCALES:
        assert [c[2] for c in captions if c[0] == locale] == [1, 2]
    assert [seq for seq, _ in transcripts] == [1, 2]


@pytest.mark.asyncio
async def test_pipeline_with_real_streaming_translator_emits_out_of_order_locales() -> None:
    # zh-CN 이 먼저 완성되고, vi-VN 은 0.15초 뒤에 완성된다.
    completions = FakeCompletions(
        lambda kw: FakeStream(ZH_FIRST, delays=[0.0, 0.15, 0.0])
    )
    translator = make_translator(completions)
    pipeline, captions, transcripts = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("안녕하세요."))
    await pipeline.flush_and_stop()

    assert [(c[0], c[1]) for c in captions] == [("zh-CN", "你好"), ("vi-VN", "xin chào")]
    zh_at, vi_at = captions[0][3], captions[1][3]
    assert vi_at - zh_at >= 0.1
    assert transcripts[0][1]["zh-CN"] == {"text": "你好", "isFallback": False}


@pytest.mark.asyncio
async def test_stream_timeout_keeps_early_locale_and_falls_back_for_rest() -> None:
    completions = FakeCompletions(lambda kw: FakeStream(ZH_FIRST, hang_at=1))
    translator = make_translator(completions, translate_timeout_sec=0.2)
    fallback_flags: list[tuple[str, bool]] = []
    pipeline, captions, transcripts = make_pipeline(translator)

    original = pipeline._on_subtitle

    async def on_subtitle(locale, text, segment, is_final, *, is_fallback=False) -> None:
        fallback_flags.append((locale, is_fallback))
        await original(locale, text, segment, is_final, is_fallback=is_fallback)

    pipeline._on_subtitle = on_subtitle

    await pipeline.enqueue_stt_final(stt_final("안녕하세요."))
    await pipeline.flush_and_stop()

    assert fallback_flags == [("zh-CN", False), ("vi-VN", True)]
    assert [c[1] for c in captions] == ["你好", "안녕하세요."]
    assert transcripts[0][1]["vi-VN"]["isFallback"] is True
