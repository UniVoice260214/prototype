"""파이프라인 오케스트레이션 — 아키텍처 가이드의 실시간 처리 루프.

  STT final ─▶ Segmenter ─▶ (RAG Trigger) ─▶ OpenAI 번역 ─▶ ┬▶ Azure TTS ─▶ locale track publish
                                                            └▶ 자막 DataChannel broadcast

각 단계는 별도 모듈이며 이 클래스가 조립만 한다. RAG 는 RagClient 인터페이스로만
의존하므로, NoOpRagClient(기본) → 실제 구현으로 바꿔 끼우면 끝.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable

from .audio_publisher import LocaleAudioPublisher
from .rag import RagClient
from .segmenter import Segmenter
from .translator import Translator
from .tts import TtsSynthesizer

logger = logging.getLogger(__name__)

# on_subtitle(locale, text, source_ko, is_final) -> Awaitable
SubtitleSink = Callable[[str, str, str, bool], Awaitable[None]]


class TranslationPipeline:
    def __init__(
        self,
        session_id: str,
        target_locales: list[str],
        segmenter: Segmenter,
        rag: RagClient,
        translator: Translator,
        tts: TtsSynthesizer,
        publisher: LocaleAudioPublisher,
        on_subtitle: SubtitleSink,
    ) -> None:
        self._session_id = session_id
        self._locales = target_locales
        self._segmenter = segmenter
        self._rag = rag
        self._translator = translator
        self._tts = tts
        self._publisher = publisher
        self._on_subtitle = on_subtitle
        self._loop = asyncio.get_event_loop()

    async def handle_final(self, ko_text: str) -> None:
        """STT final 콜백에서 호출. 완성 문장마다 번역 파이프라인을 태운다."""
        for sentence in self._segmenter.push(ko_text):
            try:
                await self._process_sentence(sentence)
            except Exception:  # noqa: BLE001 — 한 문장 실패가 세션을 죽이지 않도록
                logger.exception("[%s] 문장 처리 실패: %s", self._session_id, sentence)

    async def _process_sentence(self, sentence: str) -> None:
        # 1) RAG Trigger 판단 + 문맥 검색 (NoOp 이면 항상 None)
        hits = self._translator.detect_glossary_hits(sentence)
        context = await self._rag.retrieve(sentence, hits)

        # 2) 다국어 동시 번역
        translations = await self._translator.translate(sentence, context)

        # 3) locale 별 자막 + 음성 동시 처리
        await asyncio.gather(
            *(self._emit_locale(loc, translations.get(loc, ""), sentence) for loc in self._locales)
        )

    async def _emit_locale(self, locale: str, text: str, source_ko: str) -> None:
        if not text:
            return
        # 자막 먼저 (음성보다 빨리 도달)
        await self._on_subtitle(locale, text, source_ko, True)
        # TTS 는 블로킹 → executor 에서 합성 후 track 으로 push
        pcm = await self._loop.run_in_executor(None, self._tts.synthesize, locale, text)
        if pcm:
            await self._publisher.push_pcm(locale, pcm)

    async def flush(self) -> None:
        """세션 종료 시 버퍼에 남은 문장 처리."""
        for sentence in self._segmenter.flush():
            try:
                await self._process_sentence(sentence)
            except Exception:  # noqa: BLE001
                logger.exception("[%s] flush 처리 실패: %s", self._session_id, sentence)
