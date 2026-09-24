"""순서 보존 병렬 번역 검증.

한 STT final 에 문장이 여러 개 들어오면 예전에는 뒷문장이 앞문장 번역을
기다렸다가 시작했다. 이제 번역은 세마포어 상한 안에서 겹쳐 돌고, 자막 발행과
transcript 저장만 sequence 순서로 나간다.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest

from univoice_worker.config import WorkerConfig
from univoice_worker.models import SpeechSegment
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter
from univoice_worker.translator import Translator

from fakes import FakeAudioPublisher, FakeRagClient, FakeTts, stt_final


class ConcurrencyTranslator:
    """문장별 지연을 주고 동시 실행 수를 기록한다."""

    def __init__(self, delays: dict[str, float], *, default_delay: float = 0.05) -> None:
        self.delays = delays
        self.default_delay = default_delay
        self.active = 0
        self.max_active = 0
        self.started: list[str] = []
        self.finished: list[str] = []

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        self.started.append(sentence)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delays.get(sentence, self.default_delay))
        finally:
            self.active -= 1
        self.finished.append(sentence)
        return {"vi-VN": f"vi:{sentence}", "zh-CN": f"zh:{sentence}"}


def make_pipeline(
    translator: Any,
    *,
    concurrency: int = 3,
    rag: Any | None = None,
    flush_timeout_sec: float = 5.0,
    locales: list[str] | None = None,
) -> tuple[TranslationPipeline, list[tuple[str, str, int]], list[int]]:
    captions: list[tuple[str, str, int]] = []
    transcripts: list[int] = []

    async def on_subtitle(locale, text, segment, is_final, *, is_fallback=False) -> None:
        captions.append((locale, text, segment.sequence))

    async def on_transcript(segment: SpeechSegment, entries: dict) -> None:
        transcripts.append(segment.sequence)

    pipeline = TranslationPipeline(
        session_id="sess-par",
        target_locales=locales or ["vi-VN", "zh-CN"],
        segmenter=Segmenter(),
        rag=rag or FakeRagClient(),
        translator=translator,
        tts=FakeTts(),
        publisher=FakeAudioPublisher(),
        on_subtitle=on_subtitle,
        on_transcript=on_transcript,
        translate_max_concurrency=concurrency,
        flush_timeout_sec=flush_timeout_sec,
    )
    return pipeline, captions, transcripts


@pytest.mark.asyncio
async def test_multi_sentence_final_emits_in_sequence_order_even_if_later_finishes_first() -> None:
    # 첫 문장이 가장 느리다 — 완료 순서는 3, 2, 1 이 된다.
    translator = ConcurrencyTranslator({"하나.": 0.20, "둘.": 0.08, "셋.": 0.01})
    pipeline, captions, transcripts = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나. 둘. 셋."))
    await pipeline.flush_and_stop()

    assert translator.finished == ["셋.", "둘.", "하나."]
    sequences = [seq for _, _, seq in captions]
    assert sequences == sorted(sequences)
    assert [seq for loc, _, seq in captions if loc == "vi-VN"] == [1, 2, 3]
    assert [seq for loc, _, seq in captions if loc == "zh-CN"] == [1, 2, 3]
    assert transcripts == [1, 2, 3]


@pytest.mark.asyncio
async def test_translations_of_one_final_actually_overlap() -> None:
    translator = ConcurrencyTranslator({}, default_delay=0.15)
    pipeline, captions, _ = make_pipeline(translator)

    started = time.monotonic()
    await pipeline.enqueue_stt_final(stt_final("하나. 둘. 셋."))
    await pipeline.flush_and_stop()
    elapsed = time.monotonic() - started

    assert translator.max_active == 3
    # 직렬이면 0.45초 이상 걸린다.
    assert elapsed < 0.35, elapsed
    assert len(captions) == 6


@pytest.mark.asyncio
async def test_concurrency_never_exceeds_semaphore_limit() -> None:
    translator = ConcurrencyTranslator({}, default_delay=0.03)
    pipeline, captions, transcripts = make_pipeline(translator, concurrency=2)

    await pipeline.enqueue_stt_final(stt_final("가. 나. 다. 라. 마. 바."))
    await pipeline.flush_and_stop()

    assert translator.max_active == 2
    assert transcripts == [1, 2, 3, 4, 5, 6]


@pytest.mark.asyncio
async def test_concurrency_one_restores_serial_behaviour() -> None:
    translator = ConcurrencyTranslator({"하나.": 0.05, "둘.": 0.01})
    pipeline, _, transcripts = make_pipeline(translator, concurrency=1)

    await pipeline.enqueue_stt_final(stt_final("하나. 둘."))
    await pipeline.flush_and_stop()

    assert translator.max_active == 1
    assert translator.finished == ["하나.", "둘."]
    assert transcripts == [1, 2]


@pytest.mark.asyncio
async def test_failed_translation_in_parallel_batch_falls_back_in_place() -> None:
    class PartlyFailing(ConcurrencyTranslator):
        async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
            if sentence == "둘.":
                await asyncio.sleep(0.01)
                raise RuntimeError("boom")
            return await super().translate(sentence, rag_context)

    pipeline, captions, transcripts = make_pipeline(
        PartlyFailing({"하나.": 0.05}), locales=["vi-VN"]
    )
    await pipeline.enqueue_stt_final(stt_final("하나. 둘. 셋."))
    await pipeline.flush_and_stop()

    assert [(text, seq) for _, text, seq in captions] == [
        ("vi:하나.", 1),
        ("둘.", 2),  # 한국어 원문 폴백이 제자리에 나간다
        ("vi:셋.", 3),
    ]
    assert transcripts == [1, 2, 3]


@pytest.mark.asyncio
async def test_flush_and_stop_drains_inflight_translations() -> None:
    translator = ConcurrencyTranslator({}, default_delay=0.1)
    pipeline, captions, transcripts = make_pipeline(translator)

    await pipeline.enqueue_stt_final(stt_final("하나. 둘."))
    # 번역이 진행 중인 상태에서 곧바로 종료해도 결과가 버려지지 않는다.
    await pipeline.flush_and_stop()

    assert transcripts == [1, 2]
    assert pipeline._emit_q.empty()
    assert not pipeline._inflight


@pytest.mark.asyncio
async def test_flush_and_stop_gives_up_on_hung_translation_within_timeout() -> None:
    class HangingTranslator(ConcurrencyTranslator):
        async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
            await asyncio.Event().wait()
            return {}

    pipeline, _, transcripts = make_pipeline(HangingTranslator({}), flush_timeout_sec=0.3)
    await pipeline.enqueue_stt_final(stt_final("하나. 둘."))

    started = time.monotonic()
    await asyncio.wait_for(pipeline.flush_and_stop(), timeout=3)
    assert time.monotonic() - started < 1.5
    assert transcripts == []
    await asyncio.sleep(0)
    assert not pipeline._inflight


# ── Translator history 순서 ──────────────────────────────────────────────


def _config() -> WorkerConfig:
    return WorkerConfig(
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


class ScriptedCompletions:
    """문장별로 응답 지연을 달리하는 가짜 chat.completions."""

    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays
        self.user_contents: list[str] = []

    async def create(self, **kwargs: Any) -> Any:
        user = kwargs["messages"][-1]["content"]
        self.user_contents.append(user)
        sentence = user.rsplit("\n", 1)[-1]
        await asyncio.sleep(self.delays.get(sentence, 0.0))
        content = json.dumps({"vi-VN": f"vi:{sentence}"}, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def make_translator(completions: ScriptedCompletions) -> Translator:
    translator = Translator(_config(), ["vi-VN"], [])
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return translator


@pytest.mark.asyncio
async def test_history_is_reserved_at_call_start_and_kept_in_sequence_order() -> None:
    completions = ScriptedCompletions({"첫째": 0.1, "둘째": 0.0})
    translator = make_translator(completions)

    first = asyncio.create_task(translator.translate("첫째", None, sequence=1))
    await asyncio.sleep(0)
    # 호출 시작 시점에 (원문, "") 으로 자리를 잡는다.
    assert translator.history == [("첫째", "")]

    await translator.translate("둘째", None, sequence=2)
    # 둘째가 먼저 끝났지만 history 는 sequence 순서다.
    assert translator.history == [("첫째", ""), ("둘째", "vi:둘째")]
    await first
    assert translator.history == [("첫째", "vi:첫째"), ("둘째", "vi:둘째")]


@pytest.mark.asyncio
async def test_history_order_follows_sequence_even_if_later_call_starts_first() -> None:
    completions = ScriptedCompletions({})
    translator = make_translator(completions)

    await translator.translate("둘째", None, sequence=2)
    await translator.translate("첫째", None, sequence=1)
    await translator.translate("셋째", None, sequence=3)

    assert [source for source, _ in translator.history] == ["첫째", "둘째", "셋째"]
    # 셋째의 프롬프트에는 앞선 두 문장이 순서대로 들어간다.
    assert "1) 첫째\n2) 둘째" in completions.user_contents[-1]
    # 첫째의 프롬프트에는 뒤 문장(둘째)이 문맥으로 들어가지 않는다.
    assert completions.user_contents[1] == "첫째"


@pytest.mark.asyncio
async def test_history_entry_is_released_when_translation_fails() -> None:
    class Failing:
        async def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("api down")

    translator = Translator(_config(), ["vi-VN"], [])
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=Failing()))

    with pytest.raises(RuntimeError):
        await translator.translate("실패", None, sequence=1)
    assert translator.history == []


@pytest.mark.asyncio
async def test_pipeline_passes_sequence_so_history_matches_caption_order() -> None:
    class SlowFirstRag:
        """첫 문장 RAG 가 느려 둘째 문장의 번역 호출이 먼저 시작되는 상황."""

        async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
            if sentence == "하나.":
                await asyncio.sleep(0.05)
            return None

    completions = ScriptedCompletions({})
    translator = make_translator(completions)
    pipeline, captions, _ = make_pipeline(translator, rag=SlowFirstRag(), locales=["vi-VN"])

    await pipeline.enqueue_stt_final(stt_final("하나. 둘."))
    await pipeline.flush_and_stop()

    # 번역 호출은 둘째가 먼저 시작됐다.
    assert completions.user_contents[0].endswith("둘.")
    assert [source for source, _ in translator.history] == ["하나.", "둘."]
    assert [seq for _, _, seq in captions] == [1, 2]
