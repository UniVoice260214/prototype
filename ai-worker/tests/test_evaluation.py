from __future__ import annotations

from univoice_worker.evaluation import (
    SampleScore,
    aggregate_cer,
    cer,
    edit_distance,
    normalize_text,
    normalize_words,
    wer,
)


def test_normalize_strips_punctuation_and_whitespace() -> None:
    assert normalize_text("안녕하세요, 미토콘드리아입니다!") == "안녕하세요미토콘드리아입니다"
    assert normalize_text("Hello, World.") == "helloworld"


def test_normalize_words_splits_on_punctuation() -> None:
    assert normalize_words("안녕하세요, 여러분. 시작합니다") == ["안녕하세요", "여러분", "시작합니다"]


def test_edit_distance_basic() -> None:
    assert edit_distance("abc", "abc") == 0
    assert edit_distance("abc", "axc") == 1
    assert edit_distance("abc", "") == 3
    assert edit_distance([], ["a"]) == 1


def test_cer_perfect_and_total_mismatch() -> None:
    assert cer("미토콘드리아", "미토콘드리아") == 0.0
    assert cer("미토콘드리아", "") == 1.0


def test_cer_ignores_spacing_differences() -> None:
    # 한국어 STT 는 띄어쓰기가 흔들린다 — 문자 기준으로만 비교해야 공정하다.
    assert cer("미토콘드리아는 세포의 발전소입니다", "미토콘드리아는세포의발전소입니다") == 0.0


def test_wer_counts_word_substitution() -> None:
    assert wer("세포막 구조를 봅시다", "세포벽 구조를 봅시다") == 1 / 3


def test_empty_reference() -> None:
    assert cer("", "") == 0.0
    assert cer("", "잡음") == 1.0
    assert wer("", "") == 0.0


def test_aggregate_cer_weights_by_length() -> None:
    scores = [
        SampleScore(name="long", cer=0.1, wer=0.2, ref_chars=90),
        SampleScore(name="short", cer=1.0, wer=1.0, ref_chars=10),
    ]
    assert abs(aggregate_cer(scores) - 0.19) < 1e-9
    assert aggregate_cer([]) == 0.0


# ── 간투사 처리 (실강의 전사 기반) ──────────────────────────────────────
# 사람이 받아 적은 전사에는 "씁", "어", "아", "하" 같은 간투사가 들어가지만
# STT 출력에는 없다. drop_fillers 없이 재면 정직한 엔진일수록 CER 이 나빠진다.

from univoice_worker.evaluation import strip_fillers


def test_strip_fillers_removes_standalone_interjections() -> None:
    assert (
        strip_fillers("오늘은 국어학개론 4주차 씁 오늘 우리가 공부할 내용은")
        == "오늘은 국어학개론 4주차 오늘 우리가 공부할 내용은"
    )
    assert strip_fillers("어 씁 여러분은 말소리는 뭐고") == "여러분은 말소리는 뭐고"


def test_strip_fillers_keeps_words_containing_filler_syllables() -> None:
    # '어제', '아기', '하나' 처럼 간투사 음절로 시작하는 단어는 보존해야 한다.
    assert strip_fillers("어제 아기가 하나 있다") == "어제 아기가 하나 있다"


def test_cer_with_drop_fillers_is_fair_to_stt_output() -> None:
    reference = "하 또 다른 집에서는 막내일 수가 있는 것인 거죠"
    hypothesis = "또 다른 집에서는 막내일 수가 있는 것인 거죠"
    assert cer(reference, hypothesis) > 0.0
    assert cer(reference, hypothesis, drop_fillers=True) == 0.0
    assert wer(reference, hypothesis, drop_fillers=True) == 0.0
