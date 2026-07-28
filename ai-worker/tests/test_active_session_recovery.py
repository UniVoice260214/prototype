from __future__ import annotations

import asyncio
import json

import pytest

from univoice_worker.config import WorkerConfig
from univoice_worker import main as worker_main


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


class FakeRedis:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.sets: list[tuple[str, str, int | None]] = []

    async def scan_iter(self, *, match: str, count: int):
        assert match == worker_main.SESSION_STATUS_PATTERN
        assert count == 100
        for key in self.values:
            if key.endswith(":status"):
                yield key

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.values[key] = value
        self.sets.append((key, value, ex))


@pytest.mark.asyncio
async def test_worker_startup_recovers_active_sessions_with_scan() -> None:
    started: list[dict] = []
    redis = FakeRedis(
        {
            "session:active-1:status": "active",
            "session:active-1:config": json.dumps(
                {
                    "sessionId": "active-1",
                    "courseId": "course-1",
                    "liveKitRoomName": "room-1",
                    "targetLocales": ["vi-VN"],
                }
            ),
            "session:ended-1:status": "ended",
            "session:bad-json:status": "active",
            "session:bad-json:config": "{bad",
            "session:worker-ish:worker:status": json.dumps({"status": "ready"}),
        }
    )

    async def start_session(event: dict) -> None:
        started.append(event)

    await worker_main.recover_active_sessions(redis, config(), start_session)

    assert [event["sessionId"] for event in started] == ["active-1"]


@pytest.mark.asyncio
async def test_registry_does_not_start_duplicate_running_session(monkeypatch: pytest.MonkeyPatch) -> None:
    run_started = asyncio.Event()
    created: list[str] = []

    class FakeSessionWorker:
        def __init__(self, *, session_id: str, **_kwargs: object) -> None:
            self.session_id = session_id
            created.append(session_id)

        async def run(self) -> None:
            run_started.set()
            await asyncio.Event().wait()

        async def stop(self) -> None:
            return None

    async def fake_load_glossary(*_args: object) -> list:
        return []

    monkeypatch.setattr(worker_main, "SessionWorker", FakeSessionWorker)
    monkeypatch.setattr(worker_main, "load_glossary", fake_load_glossary)

    registry = worker_main.WorkerRegistry(FakeRedis({}), config())
    event = {
        "sessionId": "session-123",
        "courseId": "course-1",
        "liveKitRoomName": "room-1",
        "targetLocales": ["vi-VN"],
    }

    await registry.start_session(event)
    await run_started.wait()
    await registry.start_session(event)

    assert created == ["session-123"]
    for worker, task in list(registry._workers.values()):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_registry_removes_crashed_worker_and_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    class CrashingSessionWorker:
        def __init__(self, *, session_id: str, **_kwargs: object) -> None:
            self.session_id = session_id

        async def run(self) -> None:
            raise RuntimeError("boom")

        async def stop(self) -> None:
            return None

    async def fake_load_glossary(*_args: object) -> list:
        return []

    monkeypatch.setattr(worker_main, "SessionWorker", CrashingSessionWorker)
    monkeypatch.setattr(worker_main, "load_glossary", fake_load_glossary)

    redis = FakeRedis({})
    registry = worker_main.WorkerRegistry(redis, config())

    await registry.start_session(
        {
            "sessionId": "crashes",
            "courseId": "course-1",
            "liveKitRoomName": "room-1",
            "targetLocales": ["vi-VN"],
        }
    )

    for _ in range(10):
        if not registry._workers and redis.sets:
            break
        await asyncio.sleep(0)

    assert registry._workers == {}
    status_key, status_json, ttl = redis.sets[-1]
    assert status_key == "session:crashes:worker:status"
    assert ttl == config().worker_status_ttl_sec
    status = json.loads(status_json)
    assert status["status"] == "failed"
    assert status["error"] == "boom"


@pytest.mark.asyncio
async def test_registry_end_session_waits_for_task_and_removes_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = asyncio.Event()
    created: list[object] = []

    class StoppableSessionWorker:
        def __init__(self, *, session_id: str, **_kwargs: object) -> None:
            self.session_id = session_id
            created.append(self)

        async def run(self) -> None:
            await stopped.wait()

        async def stop(self) -> None:
            stopped.set()

    async def fake_load_glossary(*_args: object) -> list:
        return []

    monkeypatch.setattr(worker_main, "SessionWorker", StoppableSessionWorker)
    monkeypatch.setattr(worker_main, "load_glossary", fake_load_glossary)

    registry = worker_main.WorkerRegistry(FakeRedis({}), config())
    await registry.start_session(
        {
            "sessionId": "session-123",
            "courseId": "course-1",
            "liveKitRoomName": "room-1",
            "targetLocales": ["vi-VN"],
        }
    )

    await registry.end_session({"sessionId": "session-123"})

    assert len(created) == 1
    assert registry._workers == {}


def test_validate_started_payload_skips_unsupported_locales() -> None:
    event = worker_main.validate_started_payload(
        {
            "sessionId": "session-123",
            "courseId": "course-1",
            "liveKitRoomName": "room-1",
            "targetLocales": ["zh-CN", "th-TH"],
        },
        config(),
    )

    assert event is not None
    assert event["targetLocales"] == ["zh-CN"]


def test_validate_started_payload_rejects_when_all_locales_are_unsupported() -> None:
    event = worker_main.validate_started_payload(
        {
            "sessionId": "session-123",
            "courseId": "course-1",
            "liveKitRoomName": "room-1",
            "targetLocales": ["th-TH"],
        },
        config(),
    )

    assert event is None


@pytest.mark.asyncio
async def test_bad_pubsub_payload_does_not_stop_loop() -> None:
    calls: list[dict] = []

    class FakeRegistry:
        async def start_session(self, event: dict) -> None:
            calls.append(event)

        async def end_session(self, event: dict) -> None:
            calls.append(event)

    registry = FakeRegistry()

    await worker_main.handle_pubsub_message(
        {"type": "message", "channel": worker_main.CHANNEL_SESSIONS_STARTED, "data": "{bad"},
        registry,
    )
    await worker_main.handle_pubsub_message(
        {
            "type": "message",
            "channel": worker_main.CHANNEL_SESSIONS_STARTED,
            "data": json.dumps({"sessionId": "session-123"}),
        },
        registry,
    )

    assert calls == [{"sessionId": "session-123"}]
