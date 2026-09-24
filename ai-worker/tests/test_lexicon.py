from __future__ import annotations

import json
from pathlib import Path

import pytest

from univoice_worker.lexicon import (
    LexiconRegistry,
    MajorLexicon,
    build_phrase_list,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "rag_assets"


def payload(**overrides) -> dict:
    base = {
        "major": "ai",
        "label": "인공지능",
        "index": "major_ai",
        "score_threshold": 0.5,
        "transliterations": {
            "케이 민즈": "K-평균 군집화",
            "백프로파게이션": "역전파",
            "라그": "RAG",
            "지디피": "GDP",
        },
        "lexicon": [
            {"pattern": "역전파", "canonical": "역전파", "reason": "GLOSSARY_TERM"},
            {"pattern": "음소", "canonical": "음소", "reason": "LECTURE_CONCEPT"},
            {"pattern": "ai", "canonical": "AI", "reason": "GLOSSARY_TERM"},
        ],
        "pattern_exclusions": {"음소": r"음소거"},
        "filler_patterns": [r"^(어|음|자|그|저)\s+", r"\s+그거\s+"],
    }
    base.update(overrides)
    return base


def lexicon(**overrides) -> MajorLexicon:
    return MajorLexicon.from_payload(payload(**overrides))


# ── 교정 ──────────────────────────────────────────────────────────────


def test_transliteration_is_applied_to_display_text() -> None:
    lex = lexicon()
    text, fixed = lex.correct_for_display("그 케이 민즈랑 백프로파게이션 쓰죠")
    assert text == "그 K-평균 군집화랑 역전파 쓰죠"
    assert fixed == 2


def test_display_correction_keeps_fillers_but_query_normalization_removes_them() -> None:
    """자막용 교정은 교수가 실제로 말한 단어를 지우면 안 된다."""
    lex = lexicon()
    sentence = "어 케이 민즈 그거 쓰죠"

    display, _ = lex.correct_for_display(sentence)
    assert display.startswith("어 ")
    assert "그거" in display

    query = lex.normalize_for_query(sentence)
    assert not query.startswith("어 ")
    assert "그거" not in query
    # 두 경로 모두 음차 치환은 동일하게 적용된다.
    assert "K-평균 군집화" in display and "K-평균 군집화" in query


def test_spaced_abbreviation_is_corrected() -> None:
    """STT 는 약어를 글자마다 띄어 쓰는 일이 많다."""
    lex = lexicon()
    text, fixed = lex.correct_for_display("그 지 디 피 성장률")
    assert text == "그 GDP 성장률"
    assert fixed == 1


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        # 백프로파게이션(받침 ㄴ) → 역전파(받침 없음): 으로 → 로
        ("백프로파게이션으로 계산합니다", "역전파로 계산합니다"),
        ("백프로파게이션은 체인룰이다", "역전파는 체인룰이다"),
        ("백프로파게이션이 핵심이다", "역전파가 핵심이다"),
        ("백프로파게이션을 봅시다", "역전파를 봅시다"),
    ],
)
def test_particles_follow_the_replaced_term(sentence: str, expected: str) -> None:
    """치환이 앞말의 받침을 바꾸므로 조사도 함께 맞춰야 비문이 안 나온다."""
    lex = lexicon()
    text, _ = lex.correct_for_display(sentence)
    assert text == expected


def test_particles_are_left_alone_for_latin_terms() -> None:
    """라틴 약어는 발음 기준이라 규칙이 불확실하다. 틀리게 고치느니 둔다."""
    lex = lexicon()
    text, _ = lex.correct_for_display("라그은 검색을 씁니다")
    assert text == "RAG은 검색을 씁니다"


def test_particles_of_untouched_text_are_not_rewritten() -> None:
    """치환이 없었던 문장은 조사에 손대지 않는다."""
    lex = lexicon()
    text, fixed = lex.correct_for_display("사과은 맛있다")
    assert text == "사과은 맛있다"
    assert fixed == 0


def test_no_match_returns_original_untouched() -> None:
    lex = lexicon()
    text, fixed = lex.correct_for_display("오늘은 날씨가 좋습니다")
    assert text == "오늘은 날씨가 좋습니다"
    assert fixed == 0


def test_blank_input_is_safe() -> None:
    lex = lexicon()
    assert lex.correct_for_display("") == ("", 0)
    assert lex.correct_for_display("   ")[1] == 0


# ── 매칭 ──────────────────────────────────────────────────────────────


def test_exclusion_prevents_substring_false_positive() -> None:
    """'음소' 가 '음소거' 안에 박혀 오탐하면 안 된다."""
    lex = lexicon()
    assert lex.match("음소거 눌러주세요") == []
    assert "음소" in lex.match("음소 단위로 분석합니다")


def test_ascii_pattern_requires_word_boundary() -> None:
    """'ai' 가 'said' 에 걸리면 안 된다."""
    lex = lexicon()
    assert lex.match("he said something") == []
    assert "AI" in lex.match("AI 모델을 학습합니다")


# ── PhraseList ────────────────────────────────────────────────────────


def test_phrase_list_dedupes_and_prioritises_course_glossary() -> None:
    lex = lexicon()
    phrases, stats = build_phrase_list(
        # '역전파' 는 lexicon 에도 있으므로 중복 제거 대상이다.
        glossary_terms=["미토콘드리아", "역전파"],
        lexicon=lex,
    )
    assert phrases[0] == "미토콘드리아"   # 교수가 직접 입력한 용어가 최우선
    assert phrases.count("역전파") == 1   # 대소문자 무시 중복 제거
    assert stats["glossary"] == 2
    assert stats["merged"] == len(phrases)


def test_phrase_list_respects_item_limit() -> None:
    lex = lexicon()
    phrases, stats = build_phrase_list(glossary_terms=["가나다"], lexicon=lex, max_items=2)
    assert len(phrases) == 2
    assert stats["dropped"] > 0


def test_phrase_list_respects_char_limit() -> None:
    lex = lexicon()
    phrases, _ = build_phrase_list(glossary_terms=[], lexicon=lex, max_chars=10)
    assert sum(len(p) for p in phrases) <= 10


def test_phrase_list_filters_out_too_short_entries() -> None:
    lex = lexicon()
    phrases, _ = build_phrase_list(glossary_terms=["가", ""], lexicon=lex)
    assert "가" not in phrases


def test_phrase_list_without_lexicon_still_returns_glossary() -> None:
    phrases, stats = build_phrase_list(glossary_terms=["미토콘드리아"], lexicon=None)
    assert phrases == ["미토콘드리아"]
    assert stats["lexicon"] == 0


# ── 로더 ──────────────────────────────────────────────────────────────


def test_missing_optional_keys_fall_back_to_builtin_rules() -> None:
    """구형 export(예외/필러 키 없음)도 로드되어야 한다."""
    raw = payload()
    del raw["pattern_exclusions"]
    del raw["filler_patterns"]
    lex = MajorLexicon.from_payload(raw)
    assert lex.match("음소거 눌러주세요") == []          # 내장 예외 규칙이 적용됨
    assert lex.normalize_for_query("어 라그 쓰죠").startswith("RAG")


def test_registry_skips_broken_asset(tmp_path: Path) -> None:
    (tmp_path / "lexicon_ok.json").write_text(
        json.dumps(payload()), encoding="utf-8"
    )
    (tmp_path / "lexicon_broken.json").write_text("{not json", encoding="utf-8")
    registry = LexiconRegistry.load_dir(tmp_path)
    assert registry.majors == ["ai"]
    assert registry.get("ai") is not None
    assert registry.get("bme") is None


def test_registry_on_missing_dir_is_empty(tmp_path: Path) -> None:
    registry = LexiconRegistry.load_dir(tmp_path / "does-not-exist")
    assert len(registry) == 0
    assert registry.get("ai") is None


# ── 실제 자산 (없으면 skip) ────────────────────────────────────────────


@pytest.mark.skipif(
    not (ASSETS_DIR / "lexicon_ai.json").exists(),
    reason="rag_assets/lexicon_ai.json 미배치",
)
def test_shipped_ai_asset_corrects_known_misrecognitions() -> None:
    lex = MajorLexicon.load(ASSETS_DIR / "lexicon_ai.json")
    text, fixed = lex.correct_for_display("그 케이 민즈랑 백프로파게이션 그거 라그에도 쓰죠")
    assert "K-평균 군집화" in text
    assert "역전파" in text
    assert "RAG" in text
    assert "그거" in text          # 필러는 자막에서 지우지 않는다
    assert fixed == 3


@pytest.mark.skipif(
    not (ASSETS_DIR / "lexicon_ai.json").exists(),
    reason="rag_assets/lexicon_ai.json 미배치",
)
def test_shipped_ai_asset_phrase_list_is_within_azure_limit() -> None:
    lex = MajorLexicon.load(ASSETS_DIR / "lexicon_ai.json")
    phrases, stats = build_phrase_list(glossary_terms=[], lexicon=lex)
    assert 0 < len(phrases) <= 500        # Azure PhraseList 항목 수 상한
    assert len(phrases) == len({p.lower() for p in phrases})
    assert stats["chars"] <= 8000
