"""LiveKit locale audio track publisher."""

from __future__ import annotations

import asyncio
import logging

try:  # pragma: no cover - LiveKit is runtime-provided, tests use fakes
    from livekit import rtc
except ImportError:  # pragma: no cover
    rtc = None  # type: ignore[assignment]

from .tts import SAMPLE_RATE

logger = logging.getLogger(__name__)

NUM_CHANNELS = 1
FRAME_DURATION_MS = 10
FRAME_SAMPLES = SAMPLE_RATE // (1000 // FRAME_DURATION_MS)
FRAME_BYTES = FRAME_SAMPLES * NUM_CHANNELS * 2  # 16-bit mono


class AudioPublishError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class LocaleAudioPublisher:
    def __init__(self, room: object, locales: list[str]) -> None:
        self._room = room
        self._locales = list(locales)
        self._sources: dict[str, object] = {}
        self._locks = {locale: asyncio.Lock() for locale in self._locales}
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise AudioPublishError("AUDIO_PUBLISHER_CLOSED", "Audio publisher is closed")
        if self._started:
            return
        if rtc is None:
            raise AudioPublishError("AUDIO_LIVEKIT_MISSING", "LiveKit SDK is not installed")

        for locale in self._locales:
            source = rtc.AudioSource(SAMPLE_RATE, NUM_CHANNELS)
            track = rtc.LocalAudioTrack.create_audio_track(f"tts.{locale}", source)
            options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await self._room.local_participant.publish_track(track, options)
            self._sources[locale] = source
            logger.info("track 'tts.%s' publish 완료", locale)
        self._started = True

    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        if self._closed:
            raise AudioPublishError("AUDIO_PUBLISHER_CLOSED", "Audio publisher is closed")
        self._ensure_room_connected()
        source = self._sources.get(locale)
        if source is None:
            raise AudioPublishError(
                "AUDIO_LOCALE_UNAVAILABLE",
                f"No audio source is published for locale {locale}",
            )
        if not pcm:
            raise AudioPublishError("AUDIO_EMPTY_PCM", "Cannot publish empty PCM")

        lock = self._locks.setdefault(locale, asyncio.Lock())
        async with lock:
            padded_pcm = self._pad_final_frame(pcm)
            frame_count = 0
            for offset in range(0, len(padded_pcm), FRAME_BYTES):
                chunk = padded_pcm[offset : offset + FRAME_BYTES]
                frame = rtc.AudioFrame(
                    data=chunk,
                    sample_rate=SAMPLE_RATE,
                    num_channels=NUM_CHANNELS,
                    samples_per_channel=FRAME_SAMPLES,
                )
                await source.capture_frame(frame)
                frame_count += 1
            return frame_count * FRAME_DURATION_MS

    def _ensure_room_connected(self) -> None:
        """`AudioSource.capture_frame` only writes into a local ring buffer —
        it returns successfully even after the LiveKit room has disconnected
        (e.g. the room was deleted from under us). Without this guard, TTS
        audio synthesized after disconnect would be reported as
        `audio.completed` even though no student could ever hear it.
        """
        is_connected = getattr(self._room, "isconnected", None)
        if is_connected is None:
            return  # room double doesn't expose connection state; nothing to check
        if not is_connected():
            raise AudioPublishError(
                "AUDIO_ROOM_DISCONNECTED", "LiveKit room is not connected"
            )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for source in self._sources.values():
            try:
                await source.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("audio source close failed", exc_info=True)
        self._sources.clear()
        self._started = False

    @staticmethod
    def _pad_final_frame(pcm: bytes) -> bytes:
        remainder = len(pcm) % FRAME_BYTES
        if remainder == 0:
            return pcm
        return pcm + bytes(FRAME_BYTES - remainder)
