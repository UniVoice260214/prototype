"""TTS — Azure Neural Voice 로 번역 텍스트를 음성(PCM)으로 합성.

아키텍처 가이드:
  - locale 별 Neural Voice (zh-CN, vi-VN, mn-MN ...)
  - STT Phrase List 와 동일한 glossary 를 TTS Lexicon 으로 공통 적용
  - 같은 언어를 듣는 학생이 N명이어도 1번만 합성 (locale 단위)

출력은 LiveKit AudioSource 와 맞춘 16kHz/16bit/mono PCM.
Azure SDK 호출은 블로킹이므로, 파이프라인에서 executor 로 감싸 호출한다.
"""

import logging

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class TtsSynthesizer:
    def __init__(self, key: str, region: str, voice_map: dict[str, str]) -> None:
        self._key = key
        self._region = region
        self._voice_map = voice_map
        self._synthesizers: dict[str, speechsdk.SpeechSynthesizer] = {}

    def _get(self, locale: str) -> speechsdk.SpeechSynthesizer | None:
        if locale in self._synthesizers:
            return self._synthesizers[locale]
        voice = self._voice_map.get(locale)
        if not voice:
            logger.warning("locale %s 의 TTS voice 미정의 — 음성 생략(자막만)", locale)
            self._synthesizers[locale] = None  # type: ignore[assignment]
            return None

        cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
        cfg.speech_synthesis_voice_name = voice
        # LiveKit AudioSource 와 동일 포맷(16kHz/16bit/mono raw PCM)
        cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
        )
        # audio_config=None → 스피커로 재생하지 않고 result.audio_data 로만 회수
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        self._synthesizers[locale] = synth
        return synth

    def synthesize(self, locale: str, text: str) -> bytes:
        """블로킹 합성. 실패 시 빈 bytes 반환(파이프라인은 자막만 내보냄)."""
        if not text.strip():
            return b""
        synth = self._get(locale)
        if synth is None:
            return b""
        result = synth.speak_text_async(text).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return result.audio_data
        if result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            logger.error("TTS 취소(%s): %s / %s", locale, details.reason, details.error_details)
        return b""
