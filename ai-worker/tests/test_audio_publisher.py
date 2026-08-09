from __future__ import annotations

import asyncio

import pytest

from univoice_worker import audio_publisher
from univoice_worker.audio_publisher import (
    FRAME_BYTES,
    FRAME_DURATION_MS,
    LocaleAudioPublisher,
)


class FakeAudioFrame:
    def __init__(
        self,
        *,
        data: bytes,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> None:
        self.data = data
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.samples_per_channel = samples_per_channel


class FakeRtc:
    AudioFrame = FakeAudioFrame


class FakeSource:
    def __init__(self) -> None:
        self.frames: list[FakeAudioFrame] = []

    async def capture_frame(self, frame: FakeAudioFrame) -> None:
        await asyncio.sleep(0)
        self.frames.append(frame)

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_rtc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_publisher, "rtc", FakeRtc)


@pytest.mark.asyncio
async def test_full_pcm_frames_are_published_without_padding() -> None:
    publisher = LocaleAudioPublisher(room=object(), locales=["vi-VN"])
    source = FakeSource()
    publisher._sources["vi-VN"] = source

    duration_ms = await publisher.push_pcm("vi-VN", b"a" * (FRAME_BYTES * 2))

    assert duration_ms == 2 * FRAME_DURATION_MS
    assert [len(frame.data) for frame in source.frames] == [FRAME_BYTES, FRAME_BYTES]
    assert all(frame.data == b"a" * FRAME_BYTES for frame in source.frames)


@pytest.mark.asyncio
async def test_partial_pcm_frame_is_silence_padded() -> None:
    publisher = LocaleAudioPublisher(room=object(), locales=["vi-VN"])
    source = FakeSource()
    publisher._sources["vi-VN"] = source

    duration_ms = await publisher.push_pcm("vi-VN", b"a" * (FRAME_BYTES + 5))

    assert duration_ms == 2 * FRAME_DURATION_MS
    assert len(source.frames) == 2
    assert len(source.frames[-1].data) == FRAME_BYTES
    assert source.frames[-1].data[:5] == b"a" * 5
    assert source.frames[-1].data[5:] == bytes(FRAME_BYTES - 5)


@pytest.mark.asyncio
async def test_empty_pcm_raises_clear_error() -> None:
    publisher = LocaleAudioPublisher(room=object(), locales=["vi-VN"])
    publisher._sources["vi-VN"] = FakeSource()

    with pytest.raises(Exception) as exc_info:
        await publisher.push_pcm("vi-VN", b"")

    assert getattr(exc_info.value, "error_code") == "AUDIO_EMPTY_PCM"


@pytest.mark.asyncio
async def test_same_locale_push_pcm_calls_do_not_interleave() -> None:
    publisher = LocaleAudioPublisher(room=object(), locales=["vi-VN"])
    source = FakeSource()
    publisher._sources["vi-VN"] = source

    await asyncio.gather(
        publisher.push_pcm("vi-VN", b"a" * (FRAME_BYTES * 2)),
        publisher.push_pcm("vi-VN", b"b" * (FRAME_BYTES * 2)),
    )

    frame_heads = [frame.data[:1] for frame in source.frames]
    assert frame_heads in ([b"a", b"a", b"b", b"b"], [b"b", b"b", b"a", b"a"])


class FakeConnectedRoom:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected

    def isconnected(self) -> bool:
        return self.connected


@pytest.mark.asyncio
async def test_push_pcm_raises_when_room_is_disconnected() -> None:
    room = FakeConnectedRoom(connected=False)
    publisher = LocaleAudioPublisher(room=room, locales=["vi-VN"])
    publisher._sources["vi-VN"] = FakeSource()

    with pytest.raises(Exception) as exc_info:
        await publisher.push_pcm("vi-VN", b"a" * FRAME_BYTES)

    assert getattr(exc_info.value, "error_code") == "AUDIO_ROOM_DISCONNECTED"


@pytest.mark.asyncio
async def test_push_pcm_succeeds_when_room_is_connected() -> None:
    room = FakeConnectedRoom(connected=True)
    publisher = LocaleAudioPublisher(room=room, locales=["vi-VN"])
    source = FakeSource()
    publisher._sources["vi-VN"] = source

    await publisher.push_pcm("vi-VN", b"a" * FRAME_BYTES)

    assert len(source.frames) == 1


@pytest.mark.asyncio
async def test_push_pcm_skips_connection_guard_when_room_has_no_isconnected() -> None:
    """Room test doubles (and unit tests using room=object()) shouldn't be
    forced to implement isconnected(); the guard is best-effort."""
    publisher = LocaleAudioPublisher(room=object(), locales=["vi-VN"])
    source = FakeSource()
    publisher._sources["vi-VN"] = source

    await publisher.push_pcm("vi-VN", b"a" * FRAME_BYTES)

    assert len(source.frames) == 1


@pytest.mark.asyncio
async def test_unknown_locale_and_closed_publisher_raise_clear_errors() -> None:
    publisher = LocaleAudioPublisher(room=object(), locales=["vi-VN"])
    publisher._sources["vi-VN"] = FakeSource()

    with pytest.raises(Exception) as missing_locale:
        await publisher.push_pcm("zh-CN", b"a" * FRAME_BYTES)
    assert getattr(missing_locale.value, "error_code") == "AUDIO_LOCALE_UNAVAILABLE"

    await publisher.aclose()
    with pytest.raises(Exception) as closed:
        await publisher.push_pcm("vi-VN", b"a" * FRAME_BYTES)
    assert getattr(closed.value, "error_code") == "AUDIO_PUBLISHER_CLOSED"
