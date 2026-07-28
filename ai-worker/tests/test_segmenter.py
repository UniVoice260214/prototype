from __future__ import annotations

from univoice_worker.segmenter import Segmenter

from fakes import FakeClock, stt_final as final


def test_splits_sentences_with_terminal_punctuation() -> None:
    segmenter = Segmenter()

    drafts = segmenter.push(final("One sentence. Second sentence!"))

    assert [draft.text for draft in drafts] == ["One sentence.", "Second sentence!"]


def test_emits_without_punctuation_when_max_length_exceeded() -> None:
    segmenter = Segmenter(max_chars=10, min_chars=2)

    drafts = segmenter.push(final("alpha beta gamma", confidence=0.8))

    assert [draft.text for draft in drafts] == ["alpha beta"]
    assert drafts[0].stt_confidence == 0.8


def test_idle_timeout_emits_remainder() -> None:
    clock = FakeClock()
    segmenter = Segmenter(idle_flush_ms=2000, clock=clock)

    assert segmenter.push(final("unfinished sentence", confidence=0.7)) == []
    clock.advance(1.9)
    assert segmenter.pop_idle() == []
    clock.advance(0.2)

    drafts = segmenter.pop_idle()

    assert [draft.text for draft in drafts] == ["unfinished sentence"]
    assert drafts[0].stt_confidence == 0.7


def test_session_end_flush_emits_remainder_once() -> None:
    segmenter = Segmenter()

    assert segmenter.push(final("flush me")) == []

    assert [draft.text for draft in segmenter.flush()] == ["flush me"]
    assert segmenter.flush() == []


def test_ignores_blank_and_too_short_segments() -> None:
    segmenter = Segmenter(min_chars=3)

    assert segmenter.push(final("   ")) == []
    assert segmenter.push(final("A.")) == []

    assert segmenter.flush() == []


def test_multiple_stt_finals_can_merge_into_one_segment() -> None:
    segmenter = Segmenter()

    assert segmenter.push(final("hello", confidence=0.9)) == []
    drafts = segmenter.push(final("world.", confidence=0.7))

    assert [draft.text for draft in drafts] == ["hello world."]


def test_merged_segment_uses_conservative_confidence() -> None:
    segmenter = Segmenter()

    segmenter.push(final("hello", confidence=0.95))
    segmenter.push(final("careful", confidence=0.75))
    drafts = segmenter.push(final("world.", confidence=0.85))

    assert drafts[0].stt_confidence == 0.75
