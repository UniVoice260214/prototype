from __future__ import annotations

import asyncio
import dataclasses

import pytest

from univoice_worker.config import WorkerConfig
from univoice_worker.session_worker import SessionWorker
from univoice_worker.stt import SttError
from univoice_worker import session_worker as session_worker_module


def config(*, max_reconnects: int = 3) -> WorkerConfig:
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
        stt_max_reconnects=max_reconnects,
        stt_reconnect_base_delay_ms=0,
    )


class FakeRtc:
    class TrackKind:
        KIND_AUDIO = "audio"


class FakeTrack:
    kind = "audio"


class FakePublication:
    def __init__(self, sid: str) -> None:
        self.sid = sid


class FakeParticipant:
    def __init__(self, identity: str = "professor-1") -> None:
        self.identity = identity


class FakeRoom:
    def __init__(self) -> None:
        self.local_participant = object()
        self.handlers: dict[str, object] = {}
        self.disconnected = False

    def on(self, event: str, callback: object) -> None:
        self.handlers[event] = callback

    async def disconnect(self) -> None:
        self.disconnected = True


class NeverEndingStream:
    def __init__(self, track: object) -> None:
        self.closed = False

    def __aiter__(self) -> "NeverEndingStream":
        return self

    async def __anext__(self) -> object:
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class FakeStt:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.writes: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def write(self, pcm: bytes) -> None:
        self.writes.append(pcm)


class StatusStore:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str | None]] = []

    async def set_status(self, session_id: str, status: str, *, error: str | None = None) -> None:
        self.statuses.append((status, error))


@pytest.fixture(autouse=True)
def fake_rtc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_worker_module, "rtc", FakeRtc)


def make_worker(
    *,
    stts: list[FakeStt],
    status_store: StatusStore | None = None,
    max_reconnects: int = 3,
) -> SessionWorker:
    def stt_factory(*_callbacks: object) -> FakeStt:
        stt = FakeStt()
        stts.append(stt)
        return stt

    return SessionWorker(
        config=max_reconnects_config(max_reconnects),
        session_id="session-123",
        room_name="room",
        target_locales=["vi-VN"],
        glossary=[],
        room=FakeRoom(),
        stt_factory=stt_factory,
        audio_stream_factory=NeverEndingStream,
        status_store=status_store,
    )


def max_reconnects_config(max_reconnects: int) -> WorkerConfig:
    return config(max_reconnects=max_reconnects)


@pytest.mark.asyncio
async def test_professor_track_can_attach_after_previous_track_ends() -> None:
    stts: list[FakeStt] = []
    worker = make_worker(stts=stts)
    participant = FakeParticipant()

    assert await worker._attach_professor_track(FakeTrack(), participant, track_key="track-1")
    await worker._detach_professor_track(reason="track_unsubscribed", track_key="track-1")
    assert await worker._attach_professor_track(FakeTrack(), participant, track_key="track-2")

    assert len(stts) == 2
    assert stts[0].stopped
    assert stts[1].started
    await worker.stop()


@pytest.mark.asyncio
async def test_same_track_duplicate_attach_is_ignored() -> None:
    stts: list[FakeStt] = []
    worker = make_worker(stts=stts)
    participant = FakeParticipant()
    track = FakeTrack()

    assert await worker._attach_professor_track(track, participant, track_key="track-1")
    assert not await worker._attach_professor_track(track, participant, track_key="track-1")

    assert len(stts) == 1
    await worker.stop()


@pytest.mark.asyncio
async def test_transient_stt_error_reconnects_up_to_configured_limit() -> None:
    stts: list[FakeStt] = []
    status_store = StatusStore()
    worker = make_worker(stts=stts, status_store=status_store, max_reconnects=2)
    await worker._attach_professor_track(FakeTrack(), FakeParticipant(), track_key="track-1")

    transient = SttError("STT_TRANSIENT_ERROR", True, "temporary network", "transient")
    await worker._on_stt_error(transient)
    await asyncio.sleep(0.01)
    await worker._on_stt_error(transient)
    await asyncio.sleep(0.01)
    await worker._on_stt_error(transient)
    await asyncio.sleep(0.01)

    assert len(stts) == 3
    assert status_store.statuses[-1][0] == "failed"
    await worker.stop()


@pytest.mark.asyncio
async def test_permanent_stt_error_does_not_reconnect() -> None:
    stts: list[FakeStt] = []
    status_store = StatusStore()
    worker = make_worker(stts=stts, status_store=status_store)
    await worker._attach_professor_track(FakeTrack(), FakeParticipant(), track_key="track-1")

    await worker._on_stt_error(SttError("STT_PERMANENT_ERROR", False, "bad key", "permanent"))
    await asyncio.sleep(0.01)

    assert len(stts) == 1
    assert status_store.statuses[-1][0] == "failed"
    await worker.stop()


@pytest.mark.asyncio
async def test_unsolicited_room_disconnect_marks_worker_failed() -> None:
    """LiveKit이 재연결 시도를 모두 소진하고 보내는 비자발적 disconnect는
    (우리가 stop()을 호출하지 않은 상태에서 발생하면) failed로 기록되어야
    Core API/재시작 supervisor가 감지할 수 있다."""
    stts: list[FakeStt] = []
    status_store = StatusStore()
    worker = make_worker(stts=stts, status_store=status_store)

    worker._on_room_disconnected()
    await asyncio.sleep(0.01)

    assert worker._failed is True
    assert status_store.statuses[-1][0] == "failed"


@pytest.mark.asyncio
async def test_graceful_stop_does_not_mark_worker_failed() -> None:
    """세션 종료(stop()) 흐름에서 room이 disconnect되는 것은 정상 종료이며
    failed로 오분류되면 안 된다."""
    stts: list[FakeStt] = []
    status_store = StatusStore()
    worker = make_worker(stts=stts, status_store=status_store)

    await worker.stop()
    worker._on_room_disconnected()  # 우리 쪽 disconnect()로 인한 후속 이벤트
    await asyncio.sleep(0.01)

    assert worker._failed is False
    assert status_store.statuses[-1][0] == "stopped"


@pytest.mark.asyncio
async def test_heartbeat_loop_periodically_rewrites_last_known_status() -> None:
    """상태가 바뀌지 않아도 heartbeat가 주기적으로 Redis 키를 재기록해
    TTL을 연장해야, 응답 없는(hang된) 워커도 TTL 만료로 감지 가능하다."""
    stts: list[FakeStt] = []
    status_store = StatusStore()
    cfg = dataclasses.replace(max_reconnects_config(3), worker_heartbeat_interval_sec=0.02)
    worker = SessionWorker(
        config=cfg,
        session_id="session-123",
        room_name="room",
        target_locales=["vi-VN"],
        glossary=[],
        room=FakeRoom(),
        stt_factory=lambda *_cb: (stts.append(FakeStt()) or stts[-1]),
        audio_stream_factory=NeverEndingStream,
        status_store=status_store,
    )
    worker._last_status = "ready"  # simulates pipeline having already reached "ready"

    heartbeat_task = asyncio.create_task(worker._heartbeat_loop())
    try:
        # Windows' default event loop clock has ~15ms granularity, so give the
        # 20ms-interval loop plenty of headroom to tick more than once.
        await asyncio.sleep(0.2)
    finally:
        heartbeat_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await heartbeat_task

    assert len(status_store.statuses) >= 2
    assert all(status == ("ready", None) for status in status_store.statuses)


@pytest.mark.asyncio
async def test_heartbeat_loop_stops_once_worker_is_cleaned_up() -> None:
    stts: list[FakeStt] = []
    status_store = StatusStore()
    cfg = dataclasses.replace(max_reconnects_config(3), worker_heartbeat_interval_sec=0.01)
    worker = SessionWorker(
        config=cfg,
        session_id="session-123",
        room_name="room",
        target_locales=["vi-VN"],
        glossary=[],
        room=FakeRoom(),
        stt_factory=lambda *_cb: (stts.append(FakeStt()) or stts[-1]),
        audio_stream_factory=NeverEndingStream,
        status_store=status_store,
    )
    worker._last_status = "ready"
    worker._cleaned_up = True  # simulate cleanup having already run

    heartbeat_task = asyncio.create_task(worker._heartbeat_loop())
    await asyncio.sleep(0.03)

    assert heartbeat_task.done()
    assert status_store.statuses == []


@pytest.mark.asyncio
async def test_stopping_worker_does_not_reconnect_stt() -> None:
    stts: list[FakeStt] = []
    worker = make_worker(stts=stts)
    await worker._attach_professor_track(FakeTrack(), FakeParticipant(), track_key="track-1")

    worker._stopping = True
    await worker._on_stt_error(SttError("STT_TRANSIENT_ERROR", True, "temporary", "transient"))
    await asyncio.sleep(0.01)

    assert len(stts) == 1
    await worker.stop()
