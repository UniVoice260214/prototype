"""STT partial 로 만드는 임시 번역 자막 (caption.partial).

확정 자막은 STT final → 세그먼트 → 번역을 거쳐서야 나간다. 교수가 길게 말하는
동안 학생 화면이 비어 있지 않도록, 말하는 도중의 partial 을 주기적으로 번역해
"임시 자막"으로 먼저 보여 준다. 확정 자막이 오면 학생 화면이 임시 자막을 지운다.

- 음성(TTS)은 만들지 않는다. 이미 말한 음성은 되돌릴 수 없으므로 음성은 확정
  문장으로만 만든다.
- 번역 요청은 동시에 하나만 돈다(single-flight). 진행 중에 들어온 partial 은
  최신 것만 기억해 두었다가 끝나면 이어서 번역한다. 요청 시작 간격은
  interval_ms 이상으로 벌린다 — partial 은 수백 ms 마다 오므로 전부 번역하면
  비용이 폭증한다.
- STT final 이 오면 그 발화의 진행 중 요청을 취소하고 이후 결과는 버린다.
  마지막으로 보낸 임시 자막은 확정 자막이 올 때까지 학생 화면에 남는다.
- draftSeq 는 세션 안에서 단조 증가한다. 비신뢰 채널이라 도착 순서가 바뀔 수
  있어, 학생 화면은 더 작은 draftSeq 를 버린다.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# (text, on_locale) → 전체 결과. on_locale 은 로케일 하나가 완성될 때마다 호출된다.
DraftTranslate = Callable[[str, Callable[[str, str], None]], Awaitable[dict[str, str]]]
# (locale, 번역문, 한국어 partial, draftSeq)
DraftPublish = Callable[[str, str, str, int], Awaitable[None]]

# stt_openai 가 발화 시작 시 보내는 "듣는 중" 표시. 번역할 내용이 아니다.
_IGNORED_TEXTS = {"…"}


class DraftCaptioner:
    def __init__(
        self,
        *,
        translate: DraftTranslate,
        publish: DraftPublish,
        interval_ms: int = 1000,
        min_chars: int = 6,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._translate = translate
        self._publish = publish
        self._interval = max(0, interval_ms) / 1000
        self._min_chars = max(1, min_chars)
        self._clock = clock or time.monotonic
        self._seq = itertools.count(1)
        # 발화 번호. STT final 마다 올라가며, 이전 발화의 결과를 버리는 기준이다.
        self._generation = 0
        self._latest = ""
        self._last_requested = ""
        self._last_started_at: float | None = None
        self._task: asyncio.Task[None] | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._publishes: set[asyncio.Task[None]] = set()
        self._closed = False

    def on_partial(self, text: str) -> None:
        """이벤트 루프에서 호출한다."""
        if self._closed:
            return
        text = (text or "").strip()
        if len(text) < self._min_chars or text in _IGNORED_TEXTS:
            return
        self._latest = text
        self._maybe_start()

    def on_final(self) -> None:
        """현재 발화를 끝낸다. 진행 중인 임시 번역은 취소하고 결과를 버린다."""
        self._generation += 1
        self._latest = ""
        self._last_requested = ""
        self._last_started_at = None
        self._cancel_timer()
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def aclose(self) -> None:
        self._closed = True
        task = self._task
        self.on_final()
        pending = [t for t in (task, *self._publishes) if t is not None and not t.done()]
        for pending_task in pending:
            pending_task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _maybe_start(self) -> None:
        if self._closed or not self._latest or self._latest == self._last_requested:
            return
        if self._task is not None and not self._task.done():
            return  # 끝나면 _run 이 다시 부른다.
        now = self._clock()
        if self._last_started_at is not None:
            wait = self._interval - (now - self._last_started_at)
            if wait > 0:
                if self._timer is None:
                    self._timer = asyncio.get_running_loop().call_later(wait, self._on_timer)
                return
        self._last_started_at = now
        self._last_requested = self._latest
        self._task = asyncio.create_task(
            self._run(self._latest, self._generation), name="draft-caption"
        )

    def _on_timer(self) -> None:
        self._timer = None
        self._maybe_start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    async def _run(self, text: str, generation: int) -> None:
        seq = next(self._seq)
        published: set[str] = set()

        def emit(locale: str, translated: str) -> None:
            if generation != self._generation or self._closed or not translated:
                return
            published.add(locale)
            task = asyncio.ensure_future(self._safe_publish(locale, translated, text, seq))
            self._publishes.add(task)
            task.add_done_callback(self._publishes.discard)

        try:
            result = await self._translate(text, emit)
            # 스트리밍이 꺼져 on_locale 이 안 불린 로케일은 전체 결과로 채운다.
            for locale, translated in (result or {}).items():
                if locale not in published:
                    emit(locale, translated)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 임시 자막은 실패해도 확정 자막이 나간다.
            logger.warning("임시 자막 번역 실패 (무시)", exc_info=True)
        finally:
            if generation == self._generation:
                self._task = None
                self._maybe_start()

    async def _safe_publish(self, locale: str, translated: str, source: str, seq: int) -> None:
        try:
            await self._publish(locale, translated, source, seq)
        except Exception:  # noqa: BLE001
            logger.warning("임시 자막 발행 실패 (%s)", locale, exc_info=True)


def draft_payload(session_id: str, locale: str, text: str, source: str, seq: int) -> dict[str, Any]:
    return {
        "type": "caption.partial",
        "sessionId": session_id,
        "locale": locale,
        "text": text,
        "sourceKo": source,
        "draftSeq": seq,
        "ts": time.time(),
    }
