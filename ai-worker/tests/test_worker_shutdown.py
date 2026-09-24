from __future__ import annotations

import asyncio

import pytest

from univoice_worker.config import WorkerConfig
from univoice_worker.session_worker import SessionWorker


def config() -> WorkerConfig:
    return WorkerConfig(
        redis_url="redis://localhost:6379",
        livekit_url="ws://livekit",
        livekit_api_key="key",
        livekit_api_secret="secret",
        azure_speech_key="speech-key",
        azure_speech_region="region",
        stt_language="ko-KR",
        translate_provider="openai",
        openai_api_key="openai",
        openai_model="gpt",
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
        azure_openai_api_version="",
    )


class FakeRoom:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.local_participant = object()

    def on(self, event: str, callback: object) -> None:
        return None

    async def disconnect(self) -> None:
        self.calls.append("room.disconnect")


class FakeStt:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def stop(self) -> None:
        self.calls.append("stt.stop")


class FakePipeline:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def flush_and_stop(self) -> None:
        self.calls.append("pipeline.flush_and_stop")


class FakePublisher:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def aclose(self) -> None:
        self.calls.append("publisher.aclose")


class StatusStore:
    def __init__(self) -> None:
        self.statuses: list[str] = []

    async def set_status(self, session_id: str, status: str, *, error: str | None = None) -> None:
        self.statuses.append(status)


async def sleeping_audio(calls: list[str]) -> None:
    try:
        await asyncio.Event().wait()
    finally:
        calls.append("audio.cancelled")


@pytest.mark.asyncio
async def test_session_worker_stop_drains_pipeline_and_marks_stopped() -> None:
    calls: list[str] = []
    status_store = StatusStore()
    worker = SessionWorker(
        config=config(),
        session_id="session-123",
        room_name="room",
        target_locales=["vi-VN"],
        glossary=[],
        room=FakeRoom(calls),
        status_store=status_store,
    )
    worker._stt = FakeStt(calls)
    worker._pipeline = FakePipeline(calls)
    worker._publisher = FakePublisher(calls)
    worker._audio_task = asyncio.create_task(sleeping_audio(calls))
    await asyncio.sleep(0)

    await worker.stop()
    await worker.stop()

    assert calls == [
        "stt.stop",
        "pipeline.flush_and_stop",
        "audio.cancelled",
        "publisher.aclose",
        "room.disconnect",
    ]
    assert status_store.statuses[0] == "stopping"
    assert status_store.statuses[-1] == "stopped"
