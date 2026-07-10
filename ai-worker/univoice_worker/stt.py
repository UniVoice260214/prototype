"""Azure Speech 스트리밍 STT 어댑터.

LiveKit에서 받은 16kHz/16bit/mono PCM을 PushAudioInputStream으로 밀어 넣고,
partial(recognizing) / final(recognized) 콜백을 그대로 위로 올린다.

주의: Azure SDK 콜백은 SDK 내부 스레드에서 호출된다.
호출자는 콜백 안에서 asyncio 객체를 직접 만지지 말고
loop.call_soon_threadsafe 로 이벤트 루프에 넘겨야 한다.
"""

import logging
from typing import Callable, Iterable

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BITS_PER_SAMPLE = 16
CHANNELS = 1


class AzureStreamingStt:
    def __init__(
        self,
        key: str,
        region: str,
        language: str,
        phrases: Iterable[str],
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
    ) -> None:
        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=SAMPLE_RATE,
            bits_per_sample=BITS_PER_SAMPLE,
            channels=CHANNELS,
        )
        self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)

        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_recognition_language = language

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=speechsdk.audio.AudioConfig(stream=self._push_stream),
        )

        # 전공 용어 힌트 — 아키텍처 가이드의 "Phrase List" (glossary를 STT에 주입)
        phrase_list = speechsdk.PhraseListGrammar.from_recognizer(self._recognizer)
        for phrase in phrases:
            if phrase:
                phrase_list.addPhrase(phrase)

        self._recognizer.recognizing.connect(
            lambda evt: evt.result.text and on_partial(evt.result.text)
        )

        def _handle_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            if (
                evt.result.reason == speechsdk.ResultReason.RecognizedSpeech
                and evt.result.text
            ):
                on_final(evt.result.text)

        self._recognizer.recognized.connect(_handle_recognized)
        self._recognizer.canceled.connect(
            lambda evt: logger.warning("STT canceled: %s %s", evt.reason, evt.error_details)
        )

    def start(self) -> None:
        self._recognizer.start_continuous_recognition_async().get()

    def write(self, pcm: bytes) -> None:
        self._push_stream.write(pcm)

    def stop(self) -> None:
        try:
            self._push_stream.close()
            self._recognizer.stop_continuous_recognition_async().get()
        except Exception:  # noqa: BLE001 — 종료 경로는 best-effort
            logger.exception("STT stop failed")
