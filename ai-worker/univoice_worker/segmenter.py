"""Segment STT finals into translation-ready speech units."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from .models import SttFinalResult

_SENTENCE_END = re.compile(r'[.!?\u3002\uff01\uff1f\u2026]+["\'\u201d\u2019)\]\u3011\u300d\u300f]*\s*')

# \uad6c\ub450\uc810 \uc5c6\uc774 \uc774\uc5b4\uc9c0\ub294 \ud55c\uad6d\uc5b4 \ubc1c\ud654\uc6a9 \ubcf4\uc870 \uacbd\uacc4. STT TrueText \uac00 \ubb38\uc7a5\ubd80\ud638\ub97c \ubabb \ubd99\uc778
# \uad6c\uac04\uc5d0\uc11c \uc885\uacb0\uc5b4\ubbf8 \ub4a4 \uacf5\ubc31\uc744 \ubb38\uc7a5 \uacbd\uacc4\ub85c \ubcf8\ub2e4. \uc5f0\uacb0\uc5b4\ubbf8 \uc624\ud0d0\uc744 \uc904\uc774\uae30 \uc704\ud574
# \ud655\uc2e4\ud55c \uc885\uacb0\ud615\ub9cc \ub9e4\uce6d\ud55c\ub2e4: "-\ub2c8\ub2e4"(\uc2b5\ub2c8\ub2e4/\ud569\ub2c8\ub2e4/\uc785\ub2c8\ub2e4...), "-\u3142\ub2c8\uae4c"(\uc2ed\ub2c8\uae4c/\ubb61\ub2c8\uae4c...),
# "-\uc5d0\uc694/\uc608\uc694/\uc138\uc694/\ub124\uc694/\ub370\uc694/\uae4c\uc694/\ub098\uc694/\uc9c0\uc694", "-\uac70\ub4e0\uc694/\uad70\uc694/\uc8e0".
# "\uc2b5\ub2c8\ub2e4\ub9cc" \ucc98\ub7fc \ubd99\uc5b4 \uc774\uc5b4\uc9c0\ub294 \ud615\ud0dc\ub294 \ub4a4\uac00 \uacf5\ubc31\uc774 \uc544\ub2c8\ubbc0\ub85c \ub9e4\uce6d\ub418\uc9c0 \uc54a\ub294\ub2e4.
#
# "-\ub2c8\uae4c" \ub294 \uaca9\uc2dd\uccb4 \uc758\ubb38("\uc548\ub155\ud558\uc2ed\ub2c8\uae4c")\uacfc \uc5f0\uacb0\uc5b4\ubbf8("\ud06c\ub2c8\uae4c", "\uadf8\ub7ec\ub2c8\uae4c")\uac00 \uacb9\uce58\ub294\ub370,
# \uc758\ubb38\ud615\uc740 \uc55e \uc74c\uc808\uc5d0 \ubc18\ub4dc\uc2dc \u3142\ubc1b\uce68\uc774 \uc628\ub2e4(\uc2ed/\ubb61/\ub429/\ud569...). \u3142\ubc1b\uce68 \uc74c\uc808\ub9cc \uace8\ub77c
# \ubb38\uc790 \ud074\ub798\uc2a4\ub85c \ud569\uc131\ud574 \uc5f0\uacb0\uc5b4\ubbf8 \uc624\ud0d0\uc744 \ub9c9\ub294\ub2e4 (\uc2e4\uc81c \uac15\uc758 \uc804\uc0ac\uc5d0\uc11c \uac80\uc99d\ud55c \uaddc\uce59).
_B_BATCHIM_SYLLABLES = "".join(
    chr(0xAC00 + i) for i in range(11172) if i % 28 == 17
)
_KO_SENTENCE_END = re.compile(
    r"(?:[\uac00-\ud7a3]\ub2c8\ub2e4"
    rf"|[{_B_BATCHIM_SYLLABLES}]\ub2c8\uae4c"
    r"|[\uac00-\ud7a3](?:\uc5d0|\uc608|\uc138|\ub124|\ub370|\uae4c|\ub098|\uc9c0)\uc694"
    r"|[\uac00-\ud7a3]\uac70\ub4e0\uc694|[\uac00-\ud7a3]\uad70\uc694|[\uac00-\ud7a3]\uc8e0)(?=\s)"
)

# \uc885\uacb0\uc5b4\ubbf8 \ubd84\ub9ac\ub294 \uc774\ubcf4\ub2e4 \uc9e7\uc740 \uc870\uac01\uc5d0\ub294 \uc801\uc6a9\ud558\uc9c0 \uc54a\ub294\ub2e4. \ub108\ubb34 \uc9e7\uc740 \ub2e8\uc704\ub85c \ub04a\uc73c\uba74
# \ubc88\uc5ed \ubb38\ub9e5\uc774 \uc0ac\ub77c\uc838 \uc624\ud788\ub824 \ud488\uc9c8\uc774 \ub5a8\uc5b4\uc9c4\ub2e4.
KOREAN_ENDING_MIN_CHARS = 12


def _split_korean_endings(text: str, min_chars: int) -> tuple[list[str], str]:
    """Split unpunctuated Korean text at sentence-final endings followed by space."""
    sentences: list[str] = []
    last_end = 0
    for match in _KO_SENTENCE_END.finditer(text):
        candidate = text[last_end : match.end()].strip()
        if len(candidate) >= min_chars:
            sentences.append(candidate)
            last_end = match.end()
    return sentences, text[last_end:].strip()


@dataclass(frozen=True)
class SegmentDraft:
    text: str
    stt_confidence: float | None
    started_at: float | None
    ended_at: float
    # 지연 계측용. 이 draft 를 만들어낸 마지막 STT final 기준 (time.monotonic).
    # 여러 final 이 한 세그먼트로 합쳐지면 "마지막" final 의 값이다 — 세그먼트가
    # 확정 가능해진 시점이 그때이기 때문이다.
    stt_received_at: float | None = None
    speech_end_at: float | None = None


def split_completed_sentences(
    text: str,
    *,
    korean_endings: bool = False,
    korean_ending_min_chars: int = KOREAN_ENDING_MIN_CHARS,
) -> tuple[list[str], str]:
    """Return completed sentences and the unfinished remainder."""
    sentences: list[str] = []
    last_end = 0
    for match in _SENTENCE_END.finditer(text):
        sentence = text[last_end : match.end()].strip()
        if sentence:
            sentences.append(sentence)
        last_end = match.end()
    remainder = text[last_end:].strip()
    if korean_endings and remainder:
        more, remainder = _split_korean_endings(remainder, korean_ending_min_chars)
        sentences.extend(more)
    return sentences, remainder


def split_at_max_chars(text: str, max_chars: int) -> tuple[str, str]:
    """Split near max_chars, preferring a whitespace boundary."""
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped, ""
    boundary = stripped.rfind(" ", 0, max_chars + 1)
    if boundary <= 0:
        boundary = max_chars
    return stripped[:boundary].strip(), stripped[boundary:].strip()


class Segmenter:
    """Buffers raw STT finals and emits translation units.

    If multiple STT finals are merged into one segment, confidence is the minimum
    available confidence among the merged finals. This conservative rule avoids
    overstating quality when any source utterance was uncertain.
    """

    def __init__(
        self,
        *,
        max_chars: int = 120,
        idle_flush_ms: int = 2000,
        min_chars: int = 2,
        split_korean_endings: bool = False,
        korean_ending_min_chars: int = KOREAN_ENDING_MIN_CHARS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_chars = max(max_chars, min_chars)
        self._idle_flush_seconds = idle_flush_ms / 1000
        self._min_chars = min_chars
        self._split_korean_endings = split_korean_endings
        self._korean_ending_min_chars = korean_ending_min_chars
        self._clock = clock or time.monotonic
        self._buffer = ""
        self._confidences: list[float] = []
        self._started_at: float | None = None
        self._last_input_at: float | None = None
        self._last_received_at: float | None = None
        self._last_speech_end_at: float | None = None

    def push(self, final_result: SttFinalResult | str) -> list[SegmentDraft]:
        """Push an STT final and return any emitted segment drafts."""
        result = self._coerce_result(final_result)
        final_text = result.text.strip()
        if not final_text:
            return []

        now = self._clock()
        if not self._buffer:
            self._started_at = now
            self._buffer = final_text
        else:
            self._buffer = f"{self._buffer} {final_text}".strip()

        if result.confidence is not None:
            self._confidences.append(result.confidence)
        self._last_input_at = now
        # 계측 앵커는 항상 최신 final 로 갱신한다 (없으면 이전 값을 유지).
        if result.received_at is not None:
            self._last_received_at = result.received_at
        if result.speech_end_at is not None:
            self._last_speech_end_at = result.speech_end_at

        drafts = self._drain_completed(now, result.confidence)
        drafts.extend(self._drain_by_max_chars(now))
        return drafts

    def pop_idle(self) -> list[SegmentDraft]:
        """Emit the current buffer if no input arrived within idle_flush_ms."""
        if not self._buffer or self._last_input_at is None:
            return []
        now = self._clock()
        if now - self._last_input_at < self._idle_flush_seconds:
            return []
        return self.flush()

    def flush(self) -> list[SegmentDraft]:
        """Flush remaining buffered text. Safe to call repeatedly."""
        now = self._clock()
        remaining = self._buffer.strip()
        draft = self._make_draft(remaining, now) if self._is_emit_ready(remaining) else None
        self._clear()
        return [draft] if draft is not None else []

    def _drain_completed(
        self,
        ended_at: float,
        newest_confidence: float | None,
    ) -> list[SegmentDraft]:
        sentences, remainder = split_completed_sentences(
            self._buffer,
            korean_endings=self._split_korean_endings,
            korean_ending_min_chars=self._korean_ending_min_chars,
        )
        if not sentences:
            return []

        drafts = [
            self._make_draft(sentence, ended_at)
            for sentence in sentences
            if self._is_emit_ready(sentence)
        ]
        self._buffer = remainder
        if remainder:
            self._started_at = ended_at
            self._confidences = [newest_confidence] if newest_confidence is not None else []
            self._last_input_at = ended_at
        else:
            self._clear()
        return drafts

    def _drain_by_max_chars(self, ended_at: float) -> list[SegmentDraft]:
        drafts: list[SegmentDraft] = []
        while len(self._buffer) > self._max_chars:
            segment_text, remainder = split_at_max_chars(self._buffer, self._max_chars)
            if not segment_text or segment_text == self._buffer:
                break
            if self._is_emit_ready(segment_text):
                drafts.append(self._make_draft(segment_text, ended_at))
            self._buffer = remainder
            if not self._buffer:
                self._clear()
                break
            self._started_at = ended_at
            self._last_input_at = ended_at
        return drafts

    def _make_draft(self, text: str, ended_at: float) -> SegmentDraft:
        confidence = min(self._confidences) if self._confidences else None
        return SegmentDraft(
            text=text.strip(),
            stt_confidence=confidence,
            started_at=self._started_at,
            ended_at=ended_at,
            stt_received_at=self._last_received_at,
            speech_end_at=self._last_speech_end_at,
        )

    def _is_emit_ready(self, text: str) -> bool:
        return len(text.strip()) >= self._min_chars

    def _clear(self) -> None:
        self._buffer = ""
        self._confidences = []
        self._started_at = None
        self._last_input_at = None
        self._last_received_at = None
        self._last_speech_end_at = None

    @staticmethod
    def _coerce_result(final_result: SttFinalResult | str) -> SttFinalResult:
        if isinstance(final_result, SttFinalResult):
            return final_result
        return SttFinalResult(
            text=str(final_result),
            confidence=None,
            offset_ms=None,
            duration_ms=None,
        )
