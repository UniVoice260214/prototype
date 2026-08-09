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


def test_korean_ending_split_is_off_by_default() -> None:
    segmenter = Segmenter()

    drafts = segmenter.push(final("오늘은 미토콘드리아에 대해 배우겠습니다 다음 주제로 넘어가면"))

    assert drafts == []


def test_korean_ending_splits_unpunctuated_sentence() -> None:
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("오늘은 미토콘드리아에 대해 배우겠습니다 다음 주제로 넘어가면"))

    assert [draft.text for draft in drafts] == ["오늘은 미토콘드리아에 대해 배우겠습니다"]
    assert [d.text for d in segmenter.flush()] == ["다음 주제로 넘어가면"]


def test_korean_ending_at_buffer_end_waits_for_more_input() -> None:
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("여기까지가 세포막의 정의입니다"))

    assert drafts == []


def test_korean_ending_connective_nidaman_is_not_split() -> None:
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("이 방법이 좋습니다만 단점도 있습니다 그리고"))

    assert [draft.text for draft in drafts] == ["이 방법이 좋습니다만 단점도 있습니다"]


def test_korean_ending_short_candidate_is_not_split() -> None:
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("네 알겠습니다 그럼"))

    assert drafts == []


# ── 실제 강의 전사(국어학개론 4주차) 기반 회귀 테스트 ──────────────────
# 사람이 직접 받아 적은 실강의 문장으로 종결어미 휴리스틱을 검증한다.


def test_korean_ending_formal_interrogative_bnikka_splits() -> None:
    # "생각합니까" — ㅂ받침(합) + 니까 는 격식체 의문형이므로 문장 경계다.
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("여러분은 음성학은 무엇이라고 생각합니까 한번 볼까요"))

    assert [draft.text for draft in drafts] == ["여러분은 음성학은 무엇이라고 생각합니까"]


def test_korean_ending_connective_nikka_is_not_split() -> None:
    # "크니까" — ㅂ받침이 없는 -니까 는 연결어미라 끊으면 안 된다.
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("그 사람이 키가 크니까 농구 팀에 들어가면 작은 게 되겠죠 그렇죠"))

    assert [draft.text for draft in drafts] == ["그 사람이 키가 크니까 농구 팀에 들어가면 작은 게 되겠죠"]
    assert [d.text for d in segmenter.flush()] == ["그렇죠"]


def test_korean_ending_lecture_jyo_ending_splits() -> None:
    # 실강의에서 가장 흔한 "-이죠/-거죠" 종결 발화.
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("관계 속에서 그 소리를 바라보는 것이 음운론인 거죠 그리고 공부를 해 나가다 보면"))

    assert [draft.text for draft in drafts] == ["관계 속에서 그 소리를 바라보는 것이 음운론인 거죠"]


def test_korean_ending_connective_jiman_eun_is_not_split() -> None:
    # "-지만은", "-는데" 같은 연결어미 구간은 통째로 유지되어야 한다.
    segmenter = Segmenter(split_korean_endings=True)

    drafts = segmenter.push(final("신체적으로 보면 똑같은 4학년이지만은 한 집에서는 맏이일 수가 있고"))

    assert drafts == []
