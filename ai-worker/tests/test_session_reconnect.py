from __future__ import annotations

import asyncio

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
async def test_stopping_worker_does_not_reconnect_stt() -> None:
    stts: list[FakeStt] = []
    worker = make_worker(stts=stts)
    await worker._attach_professor_track(FakeTrack(), FakeParticipant(), track_key="track-1")

    worker._stopping = True
    await worker._on_stt_error(SttError("STT_TRANSIENT_ERROR", True, "temporary", "transient"))
    await asyncio.sleep(0.01)

    assert len(stts) == 1
    await worker.stop()


# ── 데드락 회귀 (실제 장애 재현) ─────────────────────────────────────────
#
# NeverEndingStream 은 첫 __anext__ 에서 곧바로 영구 대기하므로, attach 직후
# 이벤트 루프에 양보 없이 detach 하면 _pump_audio 코루틴이 async for 본문에
# "진입하기 전에" cancel 된다 — finally 의 detach 재진입이 실행되지 않아
# 기존 테스트는 자기교착을 재현하지 못했다.
#
# 아래 스트림은 첫 프레임을 실제로 전달해 펌프가 루프 본문을 돈 상태를 만든 뒤
# detach 를 건다. 수정 전 코드(펌프 finally 가 _attach_lock 을 직접 await)라면
# detach 가 영원히 끝나지 않아 wait_for 가 TimeoutError 로 실패한다.


class FakeAudioFrame:
    class _Data:
        @staticmethod
        def tobytes() -> bytes:
            return b"\x00\x01"

    data = _Data()


class FakeAudioEvent:
    frame = FakeAudioFrame()


class YieldOnceThenBlockStream:
    def __init__(self, track: object) -> None:
        self.closed = False
        self._yielded = False

    def __aiter__(self) -> "YieldOnceThenBlockStream":
        return self

    async def __anext__(self) -> object:
        if not self._yielded:
            self._yielded = True
            return FakeAudioEvent()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


def make_pumping_worker(stts: list[FakeStt]) -> SessionWorker:
    def stt_factory(*_callbacks: object) -> FakeStt:
        stt = FakeStt()
        stts.append(stt)
        return stt

    return SessionWorker(
        config=config(),
        session_id="session-123",
        room_name="room",
        target_locales=["vi-VN"],
        glossary=[],
        room=FakeRoom(),
        stt_factory=stt_factory,
        audio_stream_factory=YieldOnceThenBlockStream,
    )


async def let_pump_enter_loop(worker: SessionWorker) -> None:
    """오디오 펌프가 첫 프레임을 소비하고 async for 내부에서 대기할 때까지 양보."""
    for _ in range(10):
        await asyncio.sleep(0)
    assert worker._audio_task is not None and not worker._audio_task.done()


@pytest.mark.asyncio
async def test_detach_while_pump_is_running_does_not_deadlock() -> None:
    stts: list[FakeStt] = []
    worker = make_pumping_worker(stts)

    assert await worker._attach_professor_track(FakeTrack(), FakeParticipant(), track_key="t-1")
    await let_pump_enter_loop(worker)
    assert stts[0].writes  # 펌프가 실제로 프레임을 STT 로 밀었다

    # 수정 전 코드는 여기서 영구 대기했다 (_cancel_audio_task_locked 가 락을 쥔 채
    # 펌프를 await ↔ 펌프 finally 가 같은 락을 대기).
    # shield 필수: wait_for 가 타임아웃에 detach 를 cancel 하면 구 코드의
    # `except CancelledError: pass` 가 그 취소를 삼켜 데드락이 "풀린 척" 통과한다.
    # 운영에서는 아무도 취소해 주지 않으므로, 외부 취소 없이 스스로 끝나야 한다.
    detach = asyncio.ensure_future(
        worker._detach_professor_track(reason="mic_paused", track_key="t-1")
    )
    await asyncio.wait_for(asyncio.shield(detach), timeout=2)

    # 데드락이 없다면 새 트랙 부착과 세션 종료가 정상 동작해야 한다.
    assert await worker._attach_professor_track(FakeTrack(), FakeParticipant(), track_key="t-2")
    assert len(stts) == 2
    await asyncio.wait_for(worker.stop(), timeout=5)


@pytest.mark.asyncio
async def test_stop_while_pump_is_running_completes_promptly() -> None:
    """세션 종료(sessions.ended 경로)가 펌프 활성 상태에서도 제한 시간 내 끝난다."""
    stts: list[FakeStt] = []
    worker = make_pumping_worker(stts)

    assert await worker._attach_professor_track(FakeTrack(), FakeParticipant(), track_key="t-1")
    await let_pump_enter_loop(worker)

    await asyncio.wait_for(worker.stop(), timeout=5)
    assert stts[0].stopped


@pytest.mark.asyncio
async def test_reattach_after_pump_detach_uses_fresh_stt() -> None:
    """마이크 일시정지→재개 시나리오: detach 후 재attach 가 새 STT 로 이어진다."""
    stts: list[FakeStt] = []
    worker = make_pumping_worker(stts)
    participant = FakeParticipant()

    for round_no in (1, 2, 3):
        assert await worker._attach_professor_track(
            FakeTrack(), participant, track_key=f"t-{round_no}"
        )
        await let_pump_enter_loop(worker)
        detach = asyncio.ensure_future(
            worker._detach_professor_track(reason="mic_paused", track_key=f"t-{round_no}")
        )
        await asyncio.wait_for(asyncio.shield(detach), timeout=2)

    assert len(stts) == 3
    assert all(stt.stopped for stt in stts)
    await asyncio.wait_for(worker.stop(), timeout=5)
