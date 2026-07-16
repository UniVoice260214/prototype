"""Segment STT finals into translation-ready speech units."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from .models import SttFinalResult

_SENTENCE_END = re.compile(r'[.!?\u3002\uff01\uff1f\u2026]+["\'\u201d\u2019)\]\u3011\u300d\u300f]*\s*')


@dataclass(frozen=True)
class SegmentDraft:
    text: str
    stt_confidence: float | None
    started_at: float | None
    ended_at: float


def split_completed_sentences(text: str) -> tuple[list[str], str]:
    """Return completed sentences and the unfinished remainder."""
    sentences: list[str] = []
    last_end = 0
    for match in _SENTENCE_END.finditer(text):
        sentence = text[last_end : match.end()].strip()
        if sentence:
            sentences.append(sentence)
        last_end = match.end()
    return sentences, text[last_end:].strip()


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
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_chars = max(max_chars, min_chars)
        self._idle_flush_seconds = idle_flush_ms / 1000
        self._min_chars = min_chars
        self._clock = clock or time.monotonic
        self._buffer = ""
        self._confidences: list[float] = []
        self._started_at: float | None = None
        self._last_input_at: float | None = None

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
        sentences, remainder = split_completed_sentences(self._buffer)
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
        )

    def _is_emit_ready(self, text: str) -> bool:
        return len(text.strip()) >= self._min_chars

    def _clear(self) -> None:
        self._buffer = ""
        self._confidences = []
        self._started_at = None
        self._last_input_at = None

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
