"""TTS 스트리밍 합성 + 선합성 검증."""

from __future__ import annotations

import asyncio
import ctypes
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from univoice_worker import tts as tts_module
from univoice_worker.dedupe import InMemoryDedupeStore
from univoice_worker.models import AudioStatus, TtsException, TtsJob
from univoice_worker.tts import STREAM_CHUNK_BYTES, TtsSynthesizer
from univoice_worker.tts_queue import FRAME_BYTES, LocaleTtsQueue


def job(sequence: int, locale: str = "vi-VN", text: str | None = None) -> TtsJob:
    return TtsJob(
        session_id="sess",
        segment_id=f"sess-run-seg-{sequence:06d}",
        sequence=sequence,
        locale=locale,
        text=text or f"text-{sequence}",
    )


class RecordingPublisher:
    """push 를 기록하고, 같은 로케일 push 가 겹치는지 감시한다."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.pushes: list[tuple[str, int, bytes, float]] = []
        self.active: dict[str, int] = {}
        self.max_active = 0
        self.current_seq: dict[str, int] = {}

    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        self.active[locale] = self.active.get(locale, 0) + 1
        self.max_active = max(self.max_active, self.active[locale])
        try:
            await asyncio.sleep(self.delay)
            self.pushes.append((locale, self.current_seq.get(locale, 0), pcm, time.monotonic()))
        finally:
            self.active[locale] -= 1
        return len(pcm) // 32  # 16kHz 16bit → 32B/ms


class FakeStreamingTts:
    """stream_job 을 지원하는 합성기 fake. 문장별 청크/지연/실패를 스크립트한다."""

    streaming_supported = True

    def __init__(
        self,
        chunks: dict[int, list[bytes]] | None = None,
        *,
        delay: float = 0.01,
        first_delay: dict[int, float] | None = None,
        fail: dict[int, tuple[int, TtsException]] | None = None,
        publisher: RecordingPublisher | None = None,
    ) -> None:
        self.chunks = chunks or {}
        self.delay = delay
        self.first_delay = first_delay or {}
        self.fail = fail or {}
        self.publisher = publisher
        self.started: list[tuple[int, float]] = []
        self.finished: list[tuple[int, float]] = []
        self.calls = 0

    async def stream_job(self, tts_job: TtsJob, on_chunk) -> None:
        self.calls += 1
        seq = tts_job.sequence
        self.started.append((seq, time.monotonic()))
        await asyncio.sleep(self.first_delay.get(seq, 0.0))
        chunks = self.chunks.get(seq, [bytes([seq]) * STREAM_CHUNK_BYTES] * 3)
        fail_at, error = self.fail.get(seq, (None, None))
        for index, chunk in enumerate(chunks):
            if index == fail_at:
                raise error
            if index:
                await asyncio.sleep(self.delay)
            on_chunk(chunk)
        self.finished.append((seq, time.monotonic()))


def make_queue(tts: Any, publisher: RecordingPublisher, **kwargs: Any):
    statuses: list[AudioStatus] = []

    async def on_status(status: AudioStatus) -> None:
        statuses.append(status)
        if status.type == "audio.started":
            publisher.current_seq[status.locale] = status.sequence

    queue = LocaleTtsQueue(
        locales=["vi-VN", "zh-CN"],
        tts=tts,
        publisher=publisher,
        on_audio_status=on_status,
        **kwargs,
    )
    return queue, statuses


def kinds(statuses: list[AudioStatus]) -> list[tuple[str, int, str | None]]:
    return [(s.type, s.sequence, s.error_code) for s in statuses]


# ── 큐: 청크 단위 발행 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streaming_job_pushes_multiple_chunks_before_synthesis_finishes() -> None:
    publisher = RecordingPublisher()
    tts = FakeStreamingTts(delay=0.05)
    queue, statuses = make_queue(tts, publisher)

    await queue.start()
    await queue.enqueue(job(1))
    await queue.flush_and_stop()

    pushes = [p for p in publisher.pushes if p[1] == 1]
    assert len(pushes) == 3
    assert b"".join(p[2] for p in pushes) == bytes([1]) * STREAM_CHUNK_BYTES * 3
    # 첫 청크 push 가 합성 완료보다 먼저다 — "합성 완료 대기"가 없다.
    assert pushes[0][3] < tts.finished[0][1]
    assert kinds(statuses) == [("audio.started", 1, None), ("audio.completed", 1, None)]
    completed = statuses[-1]
    assert completed.duration_ms == sum(len(p[2]) // 32 for p in pushes)


@pytest.mark.asyncio
async def test_unaligned_chunks_are_regrouped_to_frame_multiples() -> None:
    publisher = RecordingPublisher()
    raw = [b"\x01" * 500, b"\x02" * 500, b"\x03" * 100]
    tts = FakeStreamingTts({1: raw}, delay=0.0)
    queue, _ = make_queue(tts, publisher)

    await queue.start()
    await queue.enqueue(job(1))
    await queue.flush_and_stop()

    sizes = [len(p[2]) for p in publisher.pushes]
    # 마지막 조각을 빼면 모두 10ms 프레임 배수 — 문장 중간 무음 패딩이 없다.
    assert all(size % FRAME_BYTES == 0 for size in sizes[:-1])
    assert sum(sizes) == 1100
    assert b"".join(p[2] for p in publisher.pushes) == b"".join(raw)


@pytest.mark.asyncio
async def test_locale_order_and_no_overlap_are_preserved_with_prefetch() -> None:
    publisher = RecordingPublisher(delay=0.02)
    # 1번 합성이 가장 느리게 시작된다. 선합성으로 2, 3 이 먼저 준비돼도 발행은 1→2→3.
    tts = FakeStreamingTts(first_delay={1: 0.1}, delay=0.01)
    queue, statuses = make_queue(tts, publisher)

    await queue.start()
    for seq in (1, 2, 3):
        await queue.enqueue(job(seq))
        await queue.enqueue(job(seq, "zh-CN"))
    await queue.flush_and_stop()

    for locale in ("vi-VN", "zh-CN"):
        seqs = [p[1] for p in publisher.pushes if p[0] == locale]
        assert seqs == sorted(seqs) and set(seqs) == {1, 2, 3}
        # 각 push 의 내용이 그 순간 재생 중인 job 의 것이어야 한다.
        assert all(p[2][:1] == bytes([p[1]]) for p in publisher.pushes if p[0] == locale)
    assert publisher.max_active == 1
    completed = [(s.locale, s.sequence) for s in statuses if s.type == "audio.completed"]
    assert [seq for loc, seq in completed if loc == "vi-VN"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_next_job_synthesis_starts_while_previous_job_is_playing() -> None:
    publisher = RecordingPublisher(delay=0.05)  # 청크 하나 재생에 50ms
    tts = FakeStreamingTts(delay=0.0)
    queue, _ = make_queue(tts, publisher)

    await queue.start()
    await queue.enqueue(job(1))
    await queue.enqueue(job(2))
    await queue.flush_and_stop()

    job1_last_push = max(p[3] for p in publisher.pushes if p[1] == 1)
    job2_synth_start = dict(tts.started)[2]
    assert job2_synth_start < job1_last_push


@pytest.mark.asyncio
async def test_prefetch_can_be_disabled() -> None:
    publisher = RecordingPublisher(delay=0.02)
    tts = FakeStreamingTts(delay=0.0)
    queue, _ = make_queue(tts, publisher, prefetch=False)

    await queue.start()
    await queue.enqueue(job(1))
    await queue.enqueue(job(2))
    await queue.flush_and_stop()

    job1_last_push = max(p[3] for p in publisher.pushes if p[1] == 1)
    assert dict(tts.started)[2] >= job1_last_push


@pytest.mark.asyncio
async def test_failure_before_first_chunk_emits_failed_and_releases_dedupe() -> None:
    publisher = RecordingPublisher()
    error = TtsException("TTS_TRANSIENT_ERROR", "temporary", retryable=True)
    tts = FakeStreamingTts(fail={1: (0, error)})
    queue, statuses = make_queue(tts, publisher, dedupe_store=InMemoryDedupeStore(failed_ttl_sec=0))

    await queue.start()
    await queue.enqueue(job(1))
    await queue.enqueue(job(2))
    await queue.flush_and_stop()

    assert ("audio.failed", 1, "TTS_TRANSIENT_ERROR") in kinds(statuses)
    assert ("audio.completed", 2, None) in kinds(statuses)
    assert all(p[1] == 2 for p in publisher.pushes)

    # 실패 키는 풀려서 같은 job 을 다시 처리할 수 있다 (기존 재시도 정책 유지).
    tts.fail.clear()
    await queue.start()
    await queue.enqueue(job(1))
    await queue.flush_and_stop()
    assert kinds(statuses)[-1] == ("audio.completed", 1, None)


@pytest.mark.asyncio
async def test_mid_stream_failure_stops_job_and_next_job_still_plays() -> None:
    publisher = RecordingPublisher()
    error = TtsException("TTS_AZURE_CANCELED", "canceled mid-stream", retryable=True)
    tts = FakeStreamingTts(fail={1: (2, error)})
    queue, statuses = make_queue(tts, publisher)

    await queue.start()
    await queue.enqueue(job(1))
    await queue.enqueue(job(2))
    await queue.flush_and_stop()

    assert len([p for p in publisher.pushes if p[1] == 1]) == 2  # 실패 전까지 나간 청크
    assert ("audio.failed", 1, "TTS_AZURE_CANCELED") in kinds(statuses)
    assert ("audio.completed", 2, None) in kinds(statuses)


@pytest.mark.asyncio
async def test_non_streaming_tts_keeps_single_push_behaviour() -> None:
    class WholeTts:
        async def synthesize_job(self, tts_job: TtsJob) -> bytes:
            return b"\x00" * 1000

    publisher = RecordingPublisher()
    queue, _ = make_queue(WholeTts(), publisher)
    await queue.start()
    await queue.enqueue(job(1))
    await queue.flush_and_stop()

    assert [len(p[2]) for p in publisher.pushes] == [1000]


@pytest.mark.asyncio
async def test_flush_timeout_discards_prefetched_job_without_hanging() -> None:
    publisher = RecordingPublisher(delay=10)  # 재생이 끝나지 않는 상황
    tts = FakeStreamingTts(delay=0.0)
    queue, _ = make_queue(tts, publisher, flush_timeout_sec=0.2)

    await queue.start()
    for seq in (1, 2, 3):
        await queue.enqueue(job(seq))
    await asyncio.wait_for(queue.flush_and_stop(), timeout=3)

    # 큐 회계가 맞아야 다음 세션 재시작 후 flush 가 매달리지 않는다.
    await queue.start()
    publisher.delay = 0.0
    await queue.enqueue(job(4))
    await asyncio.wait_for(queue.flush_and_stop(), timeout=3)
    assert any(p[1] == 4 for p in publisher.pushes)


# ── TtsSynthesizer 스트리밍 (가짜 Speech SDK) ─────────────────────────────


class FakeSdk:
    class ResultReason:
        Canceled = "Canceled"
        SynthesizingAudioStarted = "SynthesizingAudioStarted"
        SynthesizingAudioCompleted = "SynthesizingAudioCompleted"

    class StreamStatus:
        Canceled = "Canceled"
        AllData = "AllData"

    class SpeechSynthesizer:
        def start_speaking_text_async(self, text: str) -> Any:  # pragma: no cover - 존재 표시용
            raise NotImplementedError

    class AudioDataStream:
        """실제 SDK 처럼 불변 bytes 버퍼를 C 수준에서 덮어쓴다."""

        def __init__(self, result: Any) -> None:
            self._data = result.data
            self._pos = 0
            self._cancel_at = result.cancel_at
            self.status = FakeSdk.StreamStatus.AllData
            self.cancellation_details = None

        def read_data(self, audio_buffer: bytes) -> int:
            assert isinstance(audio_buffer, bytes)
            if self._cancel_at is not None and self._pos >= self._cancel_at:
                self.status = FakeSdk.StreamStatus.Canceled
                self.cancellation_details = SimpleNamespace(
                    reason="Error", error_details="connection reset"
                )
                return 0
            chunk = self._data[self._pos : self._pos + len(audio_buffer)]
            ctypes.memmove(audio_buffer, chunk, len(chunk))
            self._pos += len(chunk)
            return len(chunk)


class FakeSynth:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls = 0
        self.stopped = False

    def start_speaking_text_async(self, text: str) -> Any:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return SimpleNamespace(get=lambda: step)

    def stop_speaking_async(self) -> Any:
        self.stopped = True
        return SimpleNamespace(get=lambda: None)


def started(data: bytes, cancel_at: int | None = None) -> Any:
    return SimpleNamespace(
        reason=FakeSdk.ResultReason.SynthesizingAudioStarted, data=data, cancel_at=cancel_at
    )


def make_synth(monkeypatch: pytest.MonkeyPatch, script: list[Any], **kwargs: Any):
    monkeypatch.setattr(tts_module, "speechsdk", FakeSdk)
    synth = TtsSynthesizer("key", "region", {"vi-VN": "voice"}, retry_base_delay_ms=0, **kwargs)
    fake = FakeSynth(script)
    monkeypatch.setattr(synth, "_get", lambda locale: fake)
    return synth, fake


@pytest.mark.asyncio
async def test_synthesizer_streams_chunks_as_distinct_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    data = bytes(range(256)) * 32  # 8192B → 3200 + 3200 + 1792
    synth, _ = make_synth(monkeypatch, [started(data)])
    chunks: list[bytes] = []

    assert synth.streaming_supported
    await synth.stream_job(job(1), chunks.append)

    assert [len(c) for c in chunks] == [3200, 3200, 1792]
    # 버퍼 재사용으로 앞 청크가 덮어써지면 이 비교가 깨진다.
    assert b"".join(chunks) == data


@pytest.mark.asyncio
async def test_synthesizer_retries_failure_before_first_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    synth, fake = make_synth(
        monkeypatch, [RuntimeError("connection reset by peer"), started(b"\x01" * 640)]
    )
    chunks: list[bytes] = []

    await synth.stream_job(job(1), chunks.append)
    assert fake.calls == 2
    assert b"".join(chunks) == b"\x01" * 640


@pytest.mark.asyncio
async def test_synthesizer_permanent_cancel_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    canceled = SimpleNamespace(
        reason=FakeSdk.ResultReason.Canceled,
        cancellation_details=SimpleNamespace(reason="Error", error_details="invalid voice name"),
    )
    synth, fake = make_synth(monkeypatch, [canceled], max_retries=3)

    with pytest.raises(TtsException) as exc_info:
        await synth.stream_job(job(1), lambda chunk: None)
    assert exc_info.value.error_code == "TTS_BAD_VOICE_OR_LOCALE"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_synthesizer_mid_stream_cancel_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    synth, fake = make_synth(monkeypatch, [started(b"\x02" * 8000, cancel_at=3200)], max_retries=3)
    chunks: list[bytes] = []

    with pytest.raises(TtsException) as exc_info:
        await synth.stream_job(job(1), chunks.append)
    # 앞부분이 이미 재생 중이라 다시 합성하지 않는다.
    assert exc_info.value.retryable is True
    assert fake.calls == 1
    assert b"".join(chunks) == b"\x02" * 3200


@pytest.mark.asyncio
async def test_synthesizer_stalled_stream_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    class StallingStream(FakeSdk.AudioDataStream):
        def read_data(self, audio_buffer: bytes) -> int:
            if self._pos:
                release.wait(2)
                return 0
            return super().read_data(audio_buffer)

    monkeypatch.setattr(FakeSdk, "AudioDataStream", StallingStream)
    synth, fake = make_synth(monkeypatch, [started(b"\x03" * 320)], timeout_sec=0.1, max_retries=2)
    try:
        with pytest.raises(TtsException) as exc_info:
            await synth.stream_job(job(1), lambda chunk: None)
        assert exc_info.value.error_code == "TTS_TIMEOUT"
        assert fake.calls == 1  # 첫 청크가 나간 뒤라 재시도하지 않는다
    finally:
        release.set()


@pytest.mark.asyncio
async def test_synthesizer_falls_back_when_sdk_has_no_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_module, "speechsdk", SimpleNamespace())

    class Whole(TtsSynthesizer):
        def synthesize(self, locale: str, text: str) -> bytes:
            return b"whole"

    synth = Whole("key", "region", {})
    chunks: list[bytes] = []

    assert not synth.streaming_supported
    await synth.stream_job(job(1), chunks.append)
    assert chunks == [b"whole"]


@pytest.mark.asyncio
async def test_streaming_can_be_disabled_on_synthesizer(monkeypatch: pytest.MonkeyPatch) -> None:
    synth, _ = make_synth(monkeypatch, [started(b"\x01" * 320)], streaming=False)
    assert not synth.streaming_supported


@pytest.mark.asyncio
async def test_queue_with_real_synthesizer_pushes_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"\x05" * (STREAM_CHUNK_BYTES * 2 + 320)
    synth, _ = make_synth(monkeypatch, [started(data)])
    publisher = RecordingPublisher()
    queue, statuses = make_queue(synth, publisher)

    await queue.start()
    await queue.enqueue(job(1))
    await queue.flush_and_stop()

    assert [len(p[2]) for p in publisher.pushes] == [3200, 3200, 320]
    assert kinds(statuses)[-1] == ("audio.completed", 1, None)


# ── 말하기 속도 (SSML prosody rate) ───────────────────────────────────────


class RateRecordingSynth(FakeSynth):
    """plain text / SSML 중 어느 경로로 합성했는지 기록한다."""

    def __init__(self, script: list[Any]) -> None:
        super().__init__(script)
        self.texts: list[str] = []
        self.ssml: list[str] = []

    def start_speaking_text_async(self, text: str) -> Any:
        self.texts.append(text)
        return super().start_speaking_text_async(text)

    def start_speaking_ssml_async(self, ssml: str) -> Any:
        self.ssml.append(ssml)
        return super().start_speaking_text_async(ssml)

    def speak_text_async(self, text: str) -> Any:
        self.texts.append(text)
        return SimpleNamespace(get=lambda: completed(b"\x01" * 320))

    def speak_ssml_async(self, ssml: str) -> Any:
        self.ssml.append(ssml)
        return SimpleNamespace(get=lambda: completed(b"\x01" * 320))


def completed(data: bytes) -> Any:
    return SimpleNamespace(reason=FakeSdk.ResultReason.SynthesizingAudioCompleted, audio_data=data)


def make_rate_synth(monkeypatch: pytest.MonkeyPatch, speaking_rate: float):
    monkeypatch.setattr(tts_module, "speechsdk", FakeSdk)
    synth = TtsSynthesizer(
        "key", "region", {"vi-VN": "vi-VN-HoaiMyNeural"}, speaking_rate=speaking_rate
    )
    fake = RateRecordingSynth([started(b"\x01" * 320)])
    monkeypatch.setattr(synth, "_get", lambda locale: fake)
    return synth, fake


@pytest.mark.asyncio
async def test_default_speaking_rate_keeps_plain_text_path(monkeypatch: pytest.MonkeyPatch) -> None:
    synth, fake = make_rate_synth(monkeypatch, 1.0)

    await synth.stream_job(job(1, text="xin chao"), lambda chunk: None)

    assert fake.texts == ["xin chao"]
    assert fake.ssml == []


@pytest.mark.asyncio
async def test_speaking_rate_streams_through_ssml_prosody(monkeypatch: pytest.MonkeyPatch) -> None:
    synth, fake = make_rate_synth(monkeypatch, 1.2)

    await synth.stream_job(job(1, text="A & B <c>"), lambda chunk: None)

    assert fake.texts == []
    assert len(fake.ssml) == 1
    ssml = fake.ssml[0]
    assert "<prosody rate='+20%'>" in ssml
    assert 'name="vi-VN-HoaiMyNeural"' in ssml
    assert 'xml:lang="vi-VN"' in ssml
    # 번역문 안의 &, < 가 SSML 을 깨지 않게 이스케이프한다.
    assert "A &amp; B &lt;c&gt;" in ssml


def test_speaking_rate_applies_to_whole_utterance_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    synth, fake = make_rate_synth(monkeypatch, 0.9)

    assert synth.synthesize("vi-VN", "xin chao") == b"\x01" * 320
    assert fake.texts == []
    assert "<prosody rate='-10%'>xin chao</prosody>" in fake.ssml[0]


def test_speaking_rate_is_clamped_to_azure_range(monkeypatch: pytest.MonkeyPatch) -> None:
    fast, _ = make_rate_synth(monkeypatch, 5.0)
    slow, _ = make_rate_synth(monkeypatch, 0.1)

    assert "rate='+100%'" in (fast._ssml("vi-VN", "x") or "")
    assert "rate='-50%'" in (slow._ssml("vi-VN", "x") or "")
