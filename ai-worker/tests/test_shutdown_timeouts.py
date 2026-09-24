"""세션 종료 체인이 어떤 상황에서도 제한 시간 안에 끝나는지 검증.

종료 hang 은 "수업을 다시 시작하면 워커가 활성화되지 않는" 실장애의 원인이었다:
직렬 pubsub 루프가 종료 처리에 묶이면 다음 sessions.started 를 영영 처리 못 한다.
"""

from __future__ import annotations

import asyncio

import pytest

from univoice_worker.models import TtsJob
from univoice_worker.tts_queue import LocaleTtsQueue


class SlowPublisher:
    """실시간 재생처럼 오래 걸리는 push — 종료 드레인 hang 재현용."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.pushed: list[str] = []

    async def push_pcm(self, locale: str, pcm: bytes) -> None:
        await asyncio.sleep(self.delay)
        self.pushed.append(locale)


class InstantTts:
    async def synthesize_job(self, job: TtsJob) -> bytes:
        return job.text.encode()


def job(sequence: int, locale: str = "vi-VN") -> TtsJob:
    return TtsJob(
        session_id="s1",
        segment_id=f"s1-run-seg-{sequence:06d}",
        sequence=sequence,
        locale=locale,
        text=f"text-{sequence}",
    )


@pytest.mark.asyncio
async def test_flush_discards_backlog_within_timeout() -> None:
    """백로그를 실시간으로 전부 재생하는 대신 제한 시간 후 폐기한다."""
    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=InstantTts(),
        publisher=SlowPublisher(delay=10),  # 잡 하나에 10초 — 드레인 불가 상황
        flush_timeout_sec=0.3,
    )
    await queue.start()
    for seq in range(1, 6):
        assert await queue.enqueue(job(seq))

    await asyncio.wait_for(queue.flush_and_stop(), timeout=3)


@pytest.mark.asyncio
async def test_enqueue_drops_when_queue_is_full() -> None:
    """큐가 가득 차면 세그먼트 컨슈머를 블록하는 대신 드롭하고 실패를 알린다."""
    statuses = []

    async def on_audio_status(status) -> None:
        statuses.append(status)

    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=InstantTts(),
        publisher=SlowPublisher(delay=10),
        on_audio_status=on_audio_status,
        queue_max_size=1,
        enqueue_timeout_sec=0.1,
        flush_timeout_sec=0.3,
    )
    await queue.start()

    assert await queue.enqueue(job(1))  # 컨슈머가 집어감
    await asyncio.sleep(0.05)
    assert await queue.enqueue(job(2))  # 큐 1칸 점유
    # 세 번째는 put 이 블록됨 — 예전에는 여기서 영구 대기했다.
    result = await asyncio.wait_for(queue.enqueue(job(3)), timeout=2)
    assert result is False
    assert any(s.error_code == "TTS_QUEUE_FULL" for s in statuses)

    await asyncio.wait_for(queue.flush_and_stop(), timeout=3)


@pytest.mark.asyncio
async def test_start_session_failure_is_recorded_as_failed_status() -> None:
    """세션 기동 예외가 조용히 삼켜지지 않고 failed 상태로 기록된다."""
    from univoice_worker import main as main_module

    class FailingRedis:
        async def get(self, key: str):
            return None

    class RecordingStatusStore:
        def __init__(self) -> None:
            self.statuses: list[tuple[str, str, str | None]] = []

        async def set_status(self, session_id, status, *, error=None, diagnostics=None):
            self.statuses.append((session_id, status, error))

    registry = main_module.WorkerRegistry(FailingRedis(), _worker_config())
    registry._status_store = RecordingStatusStore()

    async def boom(session_id, validated):
        raise RuntimeError("livekit unreachable")

    registry._start_session_inner = boom  # type: ignore[method-assign]

    await registry.start_session(
        {
            "sessionId": "sess-9",
            "courseId": "course-1",
            "liveKitRoomName": "room",
            "targetLocales": ["vi-VN"],
        }
    )

    assert ("sess-9", "failed", "livekit unreachable") in registry._status_store.statuses
    assert "sess-9" not in registry._workers


def _worker_config():
    from univoice_worker.config import WorkerConfig

    return WorkerConfig(
        redis_url="redis://localhost:6379",
        livekit_url="ws://livekit",
        livekit_api_key="key",
        livekit_api_secret="secret",
        azure_speech_key="speech",
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
