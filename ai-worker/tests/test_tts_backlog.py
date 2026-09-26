"""재생이 밀린 음성 건너뛰기(TTS_MAX_QUEUE_WAIT_MS) 검증."""

from __future__ import annotations

import asyncio
import time

import pytest

from univoice_worker.dedupe import InMemoryDedupeStore, tts_dedupe_key
from univoice_worker.latency import LatencyLog
from univoice_worker.models import AudioStatus, TtsJob
from univoice_worker.tts_queue import LocaleTtsQueue


def job(
    sequence: int,
    *,
    waited_sec: float | None = None,
    speech_end_ago_sec: float | None = None,
    locale: str = "vi-VN",
) -> TtsJob:
    """waited_sec 초 전에 큐에 들어온 job. None 이면 적재 시각 정보가 없다."""
    now = time.monotonic()
    return TtsJob(
        session_id="sess",
        segment_id=f"sess-seg-{sequence:06d}",
        sequence=sequence,
        locale=locale,
        text=f"text-{sequence}",
        speech_end_at=None if speech_end_ago_sec is None else now - speech_end_ago_sec,
        enqueued_at=None if waited_sec is None else now - waited_sec,
    )


class SlowPublisher:
    """push 마다 실시간 재생처럼 잠깐 붙잡는다 — 그 사이 뒤 job 이 큐에 쌓인다."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.published: list[bytes] = []

    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        await asyncio.sleep(self.delay)
        self.published.append(pcm)
        return 10


class RecordingTts:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def synthesize_job(self, tts_job: TtsJob) -> bytes:
        self.calls.append(tts_job.sequence)
        return f"{tts_job.sequence}".encode()


def make_queue(tts, publisher, **kwargs):
    statuses: list[AudioStatus] = []
    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=tts,
        publisher=publisher,
        on_audio_status=statuses.append,
        **kwargs,
    )
    return queue, statuses


def failed(statuses: list[AudioStatus]) -> list[tuple[int, str | None]]:
    return [(s.sequence, s.error_code) for s in statuses if s.type == "audio.failed"]


async def run(queue: LocaleTtsQueue, jobs: list[TtsJob]) -> None:
    await queue.start()
    for tts_job in jobs:
        await queue.enqueue(tts_job)
    await queue.flush_and_stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefetch", [True, False])
async def test_stale_job_with_newer_waiting_is_skipped(prefetch: bool) -> None:
    tts = RecordingTts()
    publisher = SlowPublisher()
    queue, statuses = make_queue(tts, publisher, max_queue_wait_ms=3000, prefetch=prefetch)

    await run(queue, [job(1, waited_sec=0), job(2, waited_sec=10), job(3, waited_sec=10)])

    # 2 는 뒤에 3 이 기다리고 있어 건너뛴다. 3 은 늦었지만 뒤가 비어 있어 재생한다.
    assert publisher.published == [b"1", b"3"]
    assert failed(statuses) == [(2, "TTS_SKIPPED_STALE")]
    if not prefetch:
        # 선합성이 없으면 합성 전에 걸러 Azure 호출 자체를 하지 않는다.
        assert tts.calls == [1, 3]


@pytest.mark.asyncio
async def test_several_stale_jobs_are_skipped_until_the_newest() -> None:
    publisher = SlowPublisher()
    queue, statuses = make_queue(RecordingTts(), publisher, max_queue_wait_ms=3000)

    await run(queue, [job(1, waited_sec=0)] + [job(seq, waited_sec=10) for seq in (2, 3, 4)])

    assert publisher.published == [b"1", b"4"]
    assert failed(statuses) == [(2, "TTS_SKIPPED_STALE"), (3, "TTS_SKIPPED_STALE")]


@pytest.mark.asyncio
async def test_last_stale_job_is_still_played() -> None:
    publisher = SlowPublisher()
    queue, statuses = make_queue(RecordingTts(), publisher, max_queue_wait_ms=3000)

    await run(queue, [job(1, waited_sec=10)])

    assert publisher.published == [b"1"]
    assert failed(statuses) == []


@pytest.mark.asyncio
async def test_fresh_jobs_are_never_skipped() -> None:
    publisher = SlowPublisher()
    queue, statuses = make_queue(RecordingTts(), publisher, max_queue_wait_ms=3000)

    await run(queue, [job(seq, waited_sec=0) for seq in (1, 2, 3)])

    assert publisher.published == [b"1", b"2", b"3"]
    assert failed(statuses) == []


@pytest.mark.asyncio
async def test_old_speech_end_alone_does_not_skip() -> None:
    """마이크가 끊겨 speech_end_at 이 과거로 밀려도, 큐 대기가 짧으면 재생한다."""
    publisher = SlowPublisher()
    queue, statuses = make_queue(RecordingTts(), publisher, max_queue_wait_ms=3000)

    await run(
        queue,
        [job(seq, waited_sec=0, speech_end_ago_sec=60) for seq in (1, 2, 3)],
    )

    assert publisher.published == [b"1", b"2", b"3"]
    assert failed(statuses) == []


@pytest.mark.asyncio
async def test_jobs_without_enqueue_time_are_never_skipped() -> None:
    publisher = SlowPublisher()
    queue, statuses = make_queue(RecordingTts(), publisher, max_queue_wait_ms=1)

    await run(queue, [job(seq) for seq in (1, 2, 3)])

    assert publisher.published == [b"1", b"2", b"3"]
    assert failed(statuses) == []


@pytest.mark.asyncio
async def test_zero_max_queue_wait_disables_skipping() -> None:
    publisher = SlowPublisher()
    queue, statuses = make_queue(RecordingTts(), publisher, max_queue_wait_ms=0)

    await run(queue, [job(seq, waited_sec=10) for seq in (1, 2, 3)])

    assert publisher.published == [b"1", b"2", b"3"]
    assert failed(statuses) == []


@pytest.mark.asyncio
async def test_skipped_prefetched_job_releases_dedupe_lock() -> None:
    dedupe = InMemoryDedupeStore()
    queue, _ = make_queue(
        RecordingTts(),
        SlowPublisher(),
        max_queue_wait_ms=3000,
        prefetch=True,
        dedupe_store=dedupe,
    )

    await run(queue, [job(1, waited_sec=0), job(2, waited_sec=10), job(3, waited_sec=10)])

    assert await dedupe.is_done(tts_dedupe_key("sess", "sess-seg-000001", "vi-VN"))
    assert not await dedupe.is_done(tts_dedupe_key("sess", "sess-seg-000002", "vi-VN"))
    assert await dedupe.is_done(tts_dedupe_key("sess", "sess-seg-000003", "vi-VN"))


@pytest.mark.asyncio
async def test_skipped_job_is_recorded_in_latency_log(tmp_path) -> None:
    log_path = tmp_path / "latency.jsonl"
    queue, _ = make_queue(
        RecordingTts(),
        SlowPublisher(),
        max_queue_wait_ms=3000,
        prefetch=False,
        latency_log=LatencyLog(str(log_path)),
    )

    await run(queue, [job(1, waited_sec=0), job(2, waited_sec=10), job(3, waited_sec=10)])

    lines = log_path.read_text(encoding="utf-8").splitlines()
    skipped = [line for line in lines if '"skipped": true' in line]
    assert len(skipped) == 1
    assert '"sequence": 2' in skipped[0]
    assert '"ttsQueueMs"' in skipped[0]


# ── 설정 ─────────────────────────────────────────────────────────────────


def test_config_defaults_enable_skipping_and_keep_normal_speed() -> None:
    from univoice_worker.config import DEFAULT_TTS_MAX_QUEUE_WAIT_MS, DEFAULT_TTS_SPEAKING_RATE

    assert DEFAULT_TTS_MAX_QUEUE_WAIT_MS == 3000
    assert DEFAULT_TTS_SPEAKING_RATE == 1.0


@pytest.mark.parametrize("raw", ["0.4", "2.5", "fast"])
def test_speaking_rate_outside_range_is_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    from univoice_worker import config

    monkeypatch.setenv("TTS_SPEAKING_RATE", raw)
    with pytest.raises(SystemExit):
        config._load_speaking_rate()


def test_speaking_rate_is_loaded_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from univoice_worker import config

    monkeypatch.setenv("TTS_SPEAKING_RATE", "1.25")
    assert config._load_speaking_rate() == 1.25
    monkeypatch.delenv("TTS_SPEAKING_RATE")
    assert config._load_speaking_rate() == 1.0
