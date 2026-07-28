from __future__ import annotations

import asyncio
import threading
import time

import pytest

from univoice_worker.dedupe import InMemoryDedupeStore
from univoice_worker.models import AudioStatus, TtsException, TtsJob
from univoice_worker.tts import TtsSynthesizer
from univoice_worker.tts_queue import LocaleTtsQueue


def job(sequence: int, locale: str = "vi-VN", text: str | None = None) -> TtsJob:
    return TtsJob(
        session_id="session-123",
        segment_id=f"session-123-seg-{sequence:06d}",
        sequence=sequence,
        locale=locale,
        text=text or f"text-{sequence}",
    )


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        self.published.append((locale, pcm))
        return 10


class RecordingTts:
    def __init__(self) -> None:
        self.calls: list[TtsJob] = []

    async def synthesize_job(self, tts_job: TtsJob) -> bytes:
        self.calls.append(tts_job)
        return f"{tts_job.locale}:{tts_job.sequence}".encode()


@pytest.mark.asyncio
async def test_same_locale_jobs_are_processed_in_sequence_order() -> None:
    statuses: list[AudioStatus] = []
    tts = RecordingTts()
    publisher = FakePublisher()
    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=tts,
        publisher=publisher,
        on_audio_status=statuses.append,
    )

    await queue.start()
    await queue.enqueue(job(1))
    await queue.enqueue(job(2))
    await queue.enqueue(job(3))
    await queue.flush_and_stop()

    assert [call.sequence for call in tts.calls] == [1, 2, 3]
    assert [pcm for _, pcm in publisher.published] == [b"vi-VN:1", b"vi-VN:2", b"vi-VN:3"]


@pytest.mark.asyncio
async def test_different_locales_can_process_in_parallel() -> None:
    both_started = asyncio.Event()
    release = asyncio.Event()
    started: set[str] = set()

    class BlockingTts:
        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            started.add(tts_job.locale)
            if started == {"vi-VN", "zh-CN"}:
                both_started.set()
            await release.wait()
            return tts_job.locale.encode()

    queue = LocaleTtsQueue(
        locales=["vi-VN", "zh-CN"],
        tts=BlockingTts(),
        publisher=FakePublisher(),
    )

    await queue.start()
    await queue.enqueue(job(1, "vi-VN"))
    await queue.enqueue(job(1, "zh-CN"))
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release.set()
    await queue.flush_and_stop()

    assert started == {"vi-VN", "zh-CN"}


@pytest.mark.asyncio
async def test_one_locale_failure_does_not_stop_another_locale() -> None:
    statuses: list[AudioStatus] = []
    publisher = FakePublisher()

    class FailingOneLocaleTts:
        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            if tts_job.locale == "zh-CN":
                raise TtsException("TTS_TRANSIENT_ERROR", "temporary", retryable=True)
            return b"ok"

    queue = LocaleTtsQueue(
        locales=["vi-VN", "zh-CN"],
        tts=FailingOneLocaleTts(),
        publisher=publisher,
        on_audio_status=statuses.append,
    )

    await queue.start()
    await queue.enqueue(job(1, "zh-CN"))
    await queue.enqueue(job(1, "vi-VN"))
    await queue.flush_and_stop()

    assert ("vi-VN", b"ok") in publisher.published
    assert ("audio.failed", "zh-CN", "TTS_TRANSIENT_ERROR") in [
        (status.type, status.locale, status.error_code) for status in statuses
    ]
    assert ("audio.completed", "vi-VN", None) in [
        (status.type, status.locale, status.error_code) for status in statuses
    ]


@pytest.mark.asyncio
async def test_tts_timeout_is_converted_to_audio_failed() -> None:
    statuses: list[AudioStatus] = []

    class TimeoutTts:
        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            raise TtsException("TTS_TIMEOUT", "timed out", retryable=True)

    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=TimeoutTts(),
        publisher=FakePublisher(),
        on_audio_status=statuses.append,
    )

    await queue.start()
    await queue.enqueue(job(1))
    await queue.flush_and_stop()

    assert ("audio.failed", "TTS_TIMEOUT") in [(status.type, status.error_code) for status in statuses]


@pytest.mark.asyncio
async def test_retryable_error_retries_configured_attempts() -> None:
    class RetryableSynth(TtsSynthesizer):
        def __init__(self) -> None:
            super().__init__("", "", {}, max_retries=2, retry_base_delay_ms=0)
            self.calls = 0

        def synthesize(self, locale: str, text: str) -> bytes:
            self.calls += 1
            if self.calls < 3:
                raise TtsException("TTS_TRANSIENT_ERROR", "temporary", retryable=True)
            return b"ok"

    synth = RetryableSynth()

    assert await synth.synthesize_async("vi-VN", "hello", job=job(1)) == b"ok"
    assert synth.calls == 3


@pytest.mark.asyncio
async def test_permanent_error_does_not_retry() -> None:
    class PermanentSynth(TtsSynthesizer):
        def __init__(self) -> None:
            super().__init__("", "", {}, max_retries=3, retry_base_delay_ms=0)
            self.calls = 0

        def synthesize(self, locale: str, text: str) -> bytes:
            self.calls += 1
            raise TtsException("TTS_BAD_VOICE_OR_LOCALE", "bad locale", retryable=False)

    synth = PermanentSynth()

    with pytest.raises(TtsException, match="bad locale"):
        await synth.synthesize_async("xx-XX", "hello", job=job(1, "xx-XX"))
    assert synth.calls == 1


@pytest.mark.asyncio
async def test_synthesizer_timeout_raises_typed_timeout() -> None:
    class SlowSynth(TtsSynthesizer):
        def __init__(self) -> None:
            super().__init__("", "", {}, timeout_sec=0.001, max_retries=0)

        def synthesize(self, locale: str, text: str) -> bytes:
            time.sleep(0.05)
            return b"late"

    with pytest.raises(TtsException) as exc_info:
        await SlowSynth().synthesize_async("vi-VN", "hello", job=job(1))
    assert exc_info.value.error_code == "TTS_TIMEOUT"


@pytest.mark.asyncio
async def test_synthesizer_respects_max_concurrency() -> None:
    class LimitedSynth(TtsSynthesizer):
        def __init__(self) -> None:
            super().__init__("", "", {}, max_concurrency=1)
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def synthesize(self, locale: str, text: str) -> bytes:
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.01)
            with self.lock:
                self.active -= 1
            return b"ok"

    synth = LimitedSynth()

    await asyncio.gather(
        *(synth.synthesize_async("vi-VN", "hello", job=job(sequence)) for sequence in range(1, 4))
    )

    assert synth.max_active == 1


@pytest.mark.asyncio
async def test_duplicate_segment_locale_calls_tts_once() -> None:
    tts = RecordingTts()
    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=tts,
        publisher=FakePublisher(),
        dedupe_store=InMemoryDedupeStore(),
    )
    duplicate = job(1)

    await queue.start()
    await queue.enqueue(duplicate)
    await queue.enqueue(duplicate)
    await queue.flush_and_stop()

    assert len(tts.calls) == 1


@pytest.mark.asyncio
async def test_failed_job_can_retry_when_policy_releases_failed_key() -> None:
    statuses: list[AudioStatus] = []

    class FailsThenSucceeds:
        def __init__(self) -> None:
            self.calls = 0

        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            self.calls += 1
            if self.calls == 1:
                raise TtsException("TTS_TRANSIENT_ERROR", "temporary", retryable=True)
            return b"ok"

    tts = FailsThenSucceeds()
    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=tts,
        publisher=FakePublisher(),
        on_audio_status=statuses.append,
        dedupe_store=InMemoryDedupeStore(failed_ttl_sec=0),
    )
    retry_job = job(1)

    await queue.start()
    await queue.enqueue(retry_job)
    await queue.enqueue(retry_job)
    await queue.flush_and_stop()

    assert tts.calls == 2
    assert [status.type for status in statuses if status.type != "audio.started"] == [
        "audio.failed",
        "audio.completed",
    ]


@pytest.mark.asyncio
async def test_flush_and_stop_drains_all_locale_queues() -> None:
    publisher = FakePublisher()
    queue = LocaleTtsQueue(
        locales=["vi-VN", "zh-CN", "mn-MN"],
        tts=RecordingTts(),
        publisher=publisher,
    )

    await queue.start()
    for sequence in range(1, 4):
        for locale in ["vi-VN", "zh-CN", "mn-MN"]:
            await queue.enqueue(job(sequence, locale))
    await queue.flush_and_stop()

    assert len(publisher.published) == 9
