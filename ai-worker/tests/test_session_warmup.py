"""세션 시작 시 번역/TTS 클라이언트 예열 검증."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from univoice_worker import session_worker as session_worker_module
from univoice_worker import tts as tts_module
from univoice_worker.config import WorkerConfig
from univoice_worker.session_worker import SessionWorker
from univoice_worker.translator import Translator
from univoice_worker.tts import TtsSynthesizer


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


class FakeRoom:
    def __init__(self) -> None:
        self.local_participant = SimpleNamespace()
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, callback: Any) -> None:
        self.handlers[event] = callback

    async def connect(self, url: str, token: str) -> None:
        return None

    async def disconnect(self) -> None:
        return None


class FakePublisher:
    def __init__(self, room: Any, locales: list[str]) -> None:
        self.locales = locales

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class FakePipeline:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def start(self) -> None:
        return None

    async def flush_and_stop(self) -> None:
        return None


class StatusStore:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.ready = asyncio.Event()

    async def set_status(self, session_id, status, *, error=None, diagnostics=None) -> None:
        self.statuses.append(status)
        if status == "ready":
            self.ready.set()


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []


def install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    recorder: Recorder,
    *,
    translator_warmup=None,
    tts_warmup=None,
) -> None:
    class FakeTranslator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def warmup(self) -> None:
            recorder.calls.append(("translator", None))
            if translator_warmup is not None:
                await translator_warmup()

    class FakeTts:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def warmup(self, locales: list[str]) -> None:
            recorder.calls.append(("tts", list(locales)))
            if tts_warmup is not None:
                await tts_warmup()

    monkeypatch.setattr(session_worker_module, "Translator", FakeTranslator)
    monkeypatch.setattr(session_worker_module, "TtsSynthesizer", FakeTts)
    monkeypatch.setattr(SessionWorker, "_build_token", lambda self: "token")


def make_worker(status_store: StatusStore, **cfg: Any) -> SessionWorker:
    return SessionWorker(
        config=config(**cfg),
        session_id="sess-warm",
        room_name="room",
        target_locales=["vi-VN", "zh-CN"],
        glossary=[],
        room=FakeRoom(),
        status_store=status_store,
        publisher_factory=FakePublisher,
        pipeline_factory=FakePipeline,
    )


async def run_until_ready(worker: SessionWorker, store: StatusStore) -> asyncio.Task[None]:
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(store.ready.wait(), timeout=2)
    return task


async def shutdown(worker: SessionWorker, task: asyncio.Task[None]) -> None:
    await worker.stop()
    await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_session_start_warms_up_translator_and_tts_before_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    both_running = asyncio.Event()
    running: set[str] = set()

    def gate(name: str):
        async def _wait() -> None:
            running.add(name)
            if running == {"translator", "tts"}:
                both_running.set()
            # 두 예열이 동시에 진행 중이어야만 풀린다 → 병렬 실행 증명.
            await asyncio.wait_for(both_running.wait(), timeout=1)

        return _wait

    install_fakes(
        monkeypatch, recorder, translator_warmup=gate("translator"), tts_warmup=gate("tts")
    )
    store = StatusStore()
    worker = make_worker(store)

    task = await run_until_ready(worker, store)

    assert sorted(name for name, _ in recorder.calls) == ["translator", "tts"]
    assert ("tts", ["vi-VN", "zh-CN"]) in recorder.calls
    assert store.statuses[:2] == ["starting", "ready"]
    await shutdown(worker, task)
    assert store.statuses[-1] == "stopped"


@pytest.mark.asyncio
async def test_warmup_failure_does_not_block_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder()

    async def boom() -> None:
        raise RuntimeError("openai unreachable")

    async def tts_boom() -> None:
        raise ConnectionError("azure speech unreachable")

    install_fakes(monkeypatch, recorder, translator_warmup=boom, tts_warmup=tts_boom)
    store = StatusStore()
    worker = make_worker(store)

    task = await run_until_ready(worker, store)

    assert "failed" not in store.statuses
    assert store.statuses[-1] == "ready"
    await shutdown(worker, task)
    assert store.statuses[-1] == "stopped"


@pytest.mark.asyncio
async def test_hanging_warmup_is_cut_off_by_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder()

    async def hang() -> None:
        await asyncio.Event().wait()

    install_fakes(monkeypatch, recorder, translator_warmup=hang)
    store = StatusStore()
    worker = make_worker(store, warmup_timeout_sec=0.1)

    task = await run_until_ready(worker, store)
    assert store.statuses[-1] == "ready"
    await shutdown(worker, task)


@pytest.mark.asyncio
async def test_warmup_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder()
    install_fakes(monkeypatch, recorder)
    store = StatusStore()
    worker = make_worker(store, warmup_enabled=False)

    task = await run_until_ready(worker, store)
    assert recorder.calls == []
    await shutdown(worker, task)


# ── 개별 warmup 구현 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_translator_warmup_uses_same_schema_and_prompt_without_touching_history() -> None:
    captured: list[dict[str, Any]] = []

    class Completions:
        async def create(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            content = json.dumps({"vi-VN": "xin chào"})
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    translator = Translator(config(translate_streaming=False), ["vi-VN"], [])
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    await translator.warmup()
    await translator.translate("실제 문장", None)

    warm, real = captured
    assert warm["response_format"] == real["response_format"]
    assert warm["messages"][0] == real["messages"][0]  # 같은 system prompt
    assert warm["model"] == real["model"]
    assert translator.history == [("실제 문장", "xin chào")]


class FakeConnection:
    opened: list[str] = []

    def __init__(self, synth: Any) -> None:
        self.synth = synth

    @classmethod
    def from_speech_synthesizer(cls, synth: Any) -> "FakeConnection":
        return cls(synth)

    def open(self, for_continuous_recognition: bool) -> None:
        if self.synth.locale == "xx-XX":
            raise RuntimeError("connect failed")
        FakeConnection.opened.append(self.synth.locale)


@pytest.mark.asyncio
async def test_tts_warmup_opens_connection_per_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeConnection.opened = []
    monkeypatch.setattr(tts_module, "speechsdk", SimpleNamespace(Connection=FakeConnection))

    synth = TtsSynthesizer("key", "region", {})
    monkeypatch.setattr(synth, "_get", lambda locale: SimpleNamespace(locale=locale))

    await synth.warmup(["vi-VN", "zh-CN", "xx-XX"])  # 일부 실패는 삼킨다
    assert sorted(FakeConnection.opened) == ["vi-VN", "zh-CN"]
    assert set(synth._connections) == {"vi-VN", "zh-CN"}

    with pytest.raises(RuntimeError):
        await synth.warmup(["xx-XX"])  # 전부 실패면 호출자에게 알린다
