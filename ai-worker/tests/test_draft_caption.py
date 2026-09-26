"""STT partial 임시 번역 자막(CAPTION_DRAFT_ENABLED) 검증."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from univoice_worker.config import WorkerConfig
from univoice_worker.draft_caption import DraftCaptioner, draft_payload
from univoice_worker.translator import Translator


class FakeDraftTranslate:
    """번역 호출을 기록한다. gate 가 있으면 풀릴 때까지 응답을 붙잡는다."""

    def __init__(self, locales: tuple[str, ...] = ("vi-VN", "en-US")) -> None:
        self.locales = locales
        self.calls: list[str] = []
        self.gate: asyncio.Event | None = None
        self.fail: set[str] = set()
        self.stream_first: str | None = None

    async def __call__(self, text: str, on_locale: Callable[[str, str], None]) -> dict[str, str]:
        self.calls.append(text)
        if self.gate is not None:
            await self.gate.wait()
        if text in self.fail:
            raise RuntimeError("translate failed")
        result = {locale: f"{locale}:{text}" for locale in self.locales}
        if self.stream_first is not None:
            on_locale(self.stream_first, result[self.stream_first])
        return result


class RecordingPublish:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str, int]] = []

    async def __call__(self, locale: str, text: str, source: str, seq: int) -> None:
        self.items.append((locale, text, source, seq))


def make(interval_ms: int = 0, min_chars: int = 3):
    translate = FakeDraftTranslate()
    publish = RecordingPublish()
    captioner = DraftCaptioner(
        translate=translate, publish=publish, interval_ms=interval_ms, min_chars=min_chars
    )
    return captioner, translate, publish


async def settle(seconds: float = 0.02) -> None:
    await asyncio.sleep(seconds)


@pytest.mark.asyncio
async def test_partial_is_translated_and_published_for_every_locale() -> None:
    captioner, translate, publish = make()

    captioner.on_partial("오늘은 신경망을")
    await settle()

    assert translate.calls == ["오늘은 신경망을"]
    assert sorted(publish.items) == [
        ("en-US", "en-US:오늘은 신경망을", "오늘은 신경망을", 1),
        ("vi-VN", "vi-VN:오늘은 신경망을", "오늘은 신경망을", 1),
    ]
    await captioner.aclose()


@pytest.mark.asyncio
async def test_short_partials_and_listening_indicator_are_ignored() -> None:
    captioner, translate, publish = make(min_chars=3)

    captioner.on_partial("네")
    captioner.on_partial("…")
    captioner.on_partial("   ")
    await settle()

    assert translate.calls == []
    assert publish.items == []
    await captioner.aclose()


@pytest.mark.asyncio
async def test_only_one_request_in_flight_and_latest_partial_wins() -> None:
    captioner, translate, publish = make()
    translate.gate = asyncio.Event()

    captioner.on_partial("오늘은")
    await settle()
    captioner.on_partial("오늘은 신경망")
    captioner.on_partial("오늘은 신경망을 배웁니다")
    await settle()
    assert translate.calls == ["오늘은"]  # 진행 중에는 새 요청을 보내지 않는다

    translate.gate.set()
    await settle()

    # 중간 partial 은 건너뛰고 최신 것만 이어서 번역한다.
    assert translate.calls == ["오늘은", "오늘은 신경망을 배웁니다"]
    assert [seq for *_, seq in publish.items] == [1, 1, 2, 2]
    await captioner.aclose()


@pytest.mark.asyncio
async def test_requests_are_spaced_by_interval() -> None:
    captioner, translate, _ = make(interval_ms=200)

    captioner.on_partial("첫 번째 조각")
    await settle()
    captioner.on_partial("첫 번째 조각 다음")
    await settle(0.05)
    assert translate.calls == ["첫 번째 조각"]

    await settle(0.25)
    assert translate.calls == ["첫 번째 조각", "첫 번째 조각 다음"]
    await captioner.aclose()


@pytest.mark.asyncio
async def test_same_partial_is_not_translated_twice() -> None:
    captioner, translate, _ = make()

    captioner.on_partial("같은 문장입니다")
    await settle()
    captioner.on_partial("같은 문장입니다")
    await settle()

    assert translate.calls == ["같은 문장입니다"]
    await captioner.aclose()


@pytest.mark.asyncio
async def test_final_cancels_in_flight_request_and_drops_its_result() -> None:
    captioner, translate, publish = make()
    translate.gate = asyncio.Event()

    captioner.on_partial("끝나기 전 조각")
    await settle()
    captioner.on_final()
    translate.gate.set()
    await settle()

    assert publish.items == []

    # 다음 발화는 새로 번역한다.
    captioner.on_partial("다음 발화 조각")
    await settle()
    assert translate.calls[-1] == "다음 발화 조각"
    assert publish.items and publish.items[0][2] == "다음 발화 조각"
    await captioner.aclose()


@pytest.mark.asyncio
async def test_streamed_locale_is_published_once() -> None:
    captioner, translate, publish = make()
    translate.stream_first = "en-US"

    captioner.on_partial("스트리밍 조각")
    await settle()

    locales = [locale for locale, *_ in publish.items]
    assert locales[0] == "en-US"
    assert sorted(locales) == ["en-US", "vi-VN"]
    await captioner.aclose()


@pytest.mark.asyncio
async def test_translation_failure_is_swallowed_and_next_partial_works() -> None:
    captioner, translate, publish = make()
    translate.fail = {"실패하는 조각"}

    captioner.on_partial("실패하는 조각")
    await settle()
    captioner.on_partial("성공하는 조각")
    await settle()

    assert translate.calls == ["실패하는 조각", "성공하는 조각"]
    assert {source for _, _, source, _ in publish.items} == {"성공하는 조각"}
    await captioner.aclose()


@pytest.mark.asyncio
async def test_aclose_cancels_in_flight_request_and_ignores_later_partials() -> None:
    captioner, translate, publish = make()
    translate.gate = asyncio.Event()

    captioner.on_partial("닫히기 전 조각")
    await settle()
    await asyncio.wait_for(captioner.aclose(), timeout=1)
    captioner.on_partial("닫힌 뒤 조각")
    translate.gate.set()
    await settle()

    assert translate.calls == ["닫히기 전 조각"]
    assert publish.items == []


def test_draft_payload_shape() -> None:
    payload = draft_payload("sess", "vi-VN", "xin chao", "안녕하세요", 7)

    assert payload["type"] == "caption.partial"
    assert payload["locale"] == "vi-VN"
    assert payload["text"] == "xin chao"
    assert payload["sourceKo"] == "안녕하세요"
    assert payload["draftSeq"] == 7
    assert "sequence" not in payload  # 확정 자막의 sequence 흐름과 섞지 않는다


# ── Translator.translate_draft ───────────────────────────────────────────


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


class EchoCompletions:
    def __init__(self) -> None:
        self.user_contents: list[str] = []

    async def create(self, **kwargs: Any) -> Any:
        user = kwargs["messages"][-1]["content"]
        self.user_contents.append(user)
        sentence = user.rsplit("\n", 1)[-1]
        content = json.dumps({"vi-VN": f"vi:{sentence}"}, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.asyncio
async def test_translate_draft_reads_history_but_never_writes_it() -> None:
    completions = EchoCompletions()
    translator = Translator(_config(), ["vi-VN"], [])
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    await translator.translate("확정된 앞 문장", None)
    result = await translator.translate_draft("말하는 중인 조각")

    assert result == {"vi-VN": "vi:말하는 중인 조각"}
    # 직전 확정 문맥은 프롬프트에 들어가지만,
    assert "확정된 앞 문장" in completions.user_contents[-1]
    # 임시 번역은 history 에 남지 않는다.
    assert [source for source, _ in translator.history] == ["확정된 앞 문장"]
