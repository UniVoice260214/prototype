"""LiveKit 로 locale 별 오디오 track 을 publish.

아키텍처 가이드: AI 워커가 언어별 track(tts.zh-CN, tts.vi-VN ...)을 publish 하면
학생 앱이 자기 언어 track 만 subscribe 해 재생한다.

track 은 세션 시작 시 locale 마다 하나씩 미리 만들어 두고(학생이 미리 구독 가능),
합성된 PCM 을 push_pcm() 으로 흘려보낸다.
"""

import logging

from livekit import rtc

from .tts import SAMPLE_RATE

logger = logging.getLogger(__name__)

NUM_CHANNELS = 1
# 10ms 프레임 단위로 흘려보낸다 (16000 * 0.01 = 160 samples/frame)
FRAME_SAMPLES = SAMPLE_RATE // 100
FRAME_BYTES = FRAME_SAMPLES * NUM_CHANNELS * 2  # 16-bit


class LocaleAudioPublisher:
    def __init__(self, room: rtc.Room, locales: list[str]) -> None:
        self._room = room
        self._locales = locales
        self._sources: dict[str, rtc.AudioSource] = {}

    async def start(self) -> None:
        for locale in self._locales:
            source = rtc.AudioSource(SAMPLE_RATE, NUM_CHANNELS)
            track = rtc.LocalAudioTrack.create_audio_track(f"tts.{locale}", source)
            options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await self._room.local_participant.publish_track(track, options)
            self._sources[locale] = source
            logger.info("track 'tts.%s' publish 완료", locale)

    async def push_pcm(self, locale: str, pcm: bytes) -> None:
        source = self._sources.get(locale)
        if source is None or not pcm:
            return
        # 10ms 프레임으로 잘라 순차 전송 (source 가 실시간으로 재생)
        for offset in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
            chunk = pcm[offset : offset + FRAME_BYTES]
            frame = rtc.AudioFrame(
                data=chunk,
                sample_rate=SAMPLE_RATE,
                num_channels=NUM_CHANNELS,
                samples_per_channel=FRAME_SAMPLES,
            )
            await source.capture_frame(frame)

    async def aclose(self) -> None:
        for source in self._sources.values():
            try:
                await source.aclose()
            except Exception:  # noqa: BLE001
                pass
        self._sources.clear()
