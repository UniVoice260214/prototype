"""세션 1개를 전담하는 워커 (아키텍처 가이드 §Python AI 워커).

수업 시작 시:
  1. Redis prewarm glossary → STT Phrase List(용어) + Translator/TTS(번역·발음) 로 사용
  2. LiveKit Room 에 participant(ai-worker-{sessionId})로 입장
  3. locale 별 오디오 track(tts.{locale}) 미리 publish
  4. 교수(professor-*) 오디오 track subscribe → Azure STT 스트리밍

실시간 루프 (pipeline.py 가 조립):
  STT final → Segmenter → (RAG) → 번역 → [자막 DataChannel + locale별 TTS track]

자막 DataChannel:
  - topic "stt"     : 원문 한국어 (partial=lossy, final=reliable)
  - topic "caption" : 번역 자막 (locale 별, reliable)
"""

import asyncio
import json
import logging
import time

from livekit import api, rtc

from .audio_publisher import LocaleAudioPublisher
from .config import WorkerConfig
from .glossary import GlossaryEntry
from .pipeline import TranslationPipeline
from .rag import NoOpRagClient, RagClient
from .segmenter import Segmenter
from .stt import AzureStreamingStt
from .translator import Translator
from .tts import TtsSynthesizer

logger = logging.getLogger(__name__)

PROFESSOR_IDENTITY_PREFIX = "professor-"
STT_TOPIC = "stt"          # 원문 한국어 자막
CAPTION_TOPIC = "caption"  # 번역 자막


class SessionWorker:
    def __init__(
        self,
        config: WorkerConfig,
        session_id: str,
        room_name: str,
        target_locales: list[str],
        glossary: list[GlossaryEntry],
        rag: RagClient | None = None,
    ) -> None:
        self._config = config
        self._session_id = session_id
        self._room_name = room_name
        self._target_locales = target_locales
        self._glossary = glossary
        self._rag = rag or NoOpRagClient()  # ← RAG 교체 지점 (기본: 미적용)
        self._loop = asyncio.get_event_loop()
        self._room = rtc.Room()
        self._stt: AzureStreamingStt | None = None
        self._audio_task: asyncio.Task | None = None
        self._publisher: LocaleAudioPublisher | None = None
        self._pipeline: TranslationPipeline | None = None
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        token = (
            api.AccessToken(self._config.livekit_api_key, self._config.livekit_api_secret)
            .with_identity(f"ai-worker-{self._session_id}")
            .with_name("AI Worker")
            .with_metadata(json.dumps({"role": "ai-worker", "sessionId": self._session_id}))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self._room_name,
                    can_publish=True,       # 번역 오디오 track publish
                    can_subscribe=True,     # 교수 오디오 subscribe
                    can_publish_data=True,  # 자막 DataChannel
                )
            )
            .to_jwt()
        )

        self._room.on("track_subscribed", self._on_track_subscribed)
        self._room.on("disconnected", lambda *_: self._stopped.set())

        await self._room.connect(self._config.livekit_url, token)
        logger.info("[%s] room '%s' 입장 완료", self._session_id, self._room_name)

        # locale 별 TTS track 미리 publish (학생이 미리 구독 가능)
        self._publisher = LocaleAudioPublisher(self._room, self._target_locales)
        await self._publisher.start()

        # 파이프라인 조립
        translator = Translator(self._config, self._target_locales, self._glossary)
        tts = TtsSynthesizer(
            self._config.azure_speech_key,
            self._config.azure_speech_region,
            self._config.voice_map,
        )
        self._pipeline = TranslationPipeline(
            session_id=self._session_id,
            target_locales=self._target_locales,
            segmenter=Segmenter(),
            rag=self._rag,
            translator=translator,
            tts=tts,
            publisher=self._publisher,
            on_subtitle=self._publish_translation,
        )
        logger.info("[%s] 파이프라인 준비 완료 (locales=%s), 교수 오디오 대기", self._session_id, self._target_locales)

        await self._stopped.wait()
        await self._cleanup()

    async def stop(self) -> None:
        self._stopped.set()

    def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if not participant.identity.startswith(PROFESSOR_IDENTITY_PREFIX):
            return
        if self._audio_task is not None:
            logger.warning("[%s] 교수 오디오 track 이 이미 연결됨, 무시", self._session_id)
            return

        logger.info("[%s] 교수 오디오 track 수신 시작 (%s)", self._session_id, participant.identity)
        self._stt = AzureStreamingStt(
            key=self._config.azure_speech_key,
            region=self._config.azure_speech_region,
            language=self._config.stt_language,
            phrases=[g.term for g in self._glossary],
            on_partial=lambda text: self._schedule(self._on_partial(text)),
            on_final=lambda text: self._schedule(self._on_final(text)),
        )
        self._stt.start()
        self._audio_task = asyncio.create_task(self._pump_audio(track))

    async def _pump_audio(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
        try:
            async for event in stream:
                if self._stt is not None:
                    self._stt.write(event.frame.data.tobytes())
        except Exception:  # noqa: BLE001
            logger.exception("[%s] 오디오 스트림 중단", self._session_id)
        finally:
            await stream.aclose()

    def _schedule(self, coro) -> None:
        # Azure SDK 스레드 → asyncio 루프로 안전하게 전달
        self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(coro))

    async def _on_partial(self, text: str) -> None:
        await self._publish_stt("stt.partial", text, reliable=False)

    async def _on_final(self, text: str) -> None:
        await self._publish_stt("stt.final", text, reliable=True)
        if self._pipeline is not None:
            await self._pipeline.handle_final(text)

    async def _publish_stt(self, kind: str, text: str, reliable: bool) -> None:
        payload = json.dumps(
            {
                "type": kind,
                "sessionId": self._session_id,
                "lang": self._config.stt_language,
                "text": text,
                "ts": time.time(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await self._room.local_participant.publish_data(
                payload, reliable=reliable, topic=STT_TOPIC
            )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] 원문 자막 publish 실패", self._session_id)

    async def _publish_translation(self, locale: str, text: str, source_ko: str, is_final: bool) -> None:
        payload = json.dumps(
            {
                "type": "caption.final" if is_final else "caption.partial",
                "sessionId": self._session_id,
                "locale": locale,
                "text": text,
                "sourceKo": source_ko,
                "ts": time.time(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await self._room.local_participant.publish_data(
                payload, reliable=is_final, topic=CAPTION_TOPIC
            )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] 번역 자막 publish 실패 (%s)", self._session_id, locale)

    async def _cleanup(self) -> None:
        if self._audio_task is not None:
            self._audio_task.cancel()
        if self._stt is not None:
            self._stt.stop()
        if self._pipeline is not None:
            await self._pipeline.flush()
        if self._publisher is not None:
            await self._publisher.aclose()
        try:
            await self._room.disconnect()
        except Exception:  # noqa: BLE001
            pass
        logger.info("[%s] 세션 워커 종료", self._session_id)
