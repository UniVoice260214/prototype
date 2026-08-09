from __future__ import annotations

import numpy as np
import pytest

from router import RagRouter
from runtime import INDEXES_BY_MAJOR, CourseIndexEntry, RagRuntime, parse_course_index_map


class FakeEmbedder:
    def encode(self, _texts: list[str]) -> np.ndarray:
        return np.asarray([[1.0, 0.0]], dtype=np.float32)


class FakeIndex:
    def __init__(self, score: float) -> None:
        self.score = score

    def search(self, _vector: np.ndarray, top_k: int):
        scores = np.full((1, top_k), -1.0, dtype=np.float32)
        positions = np.full((1, top_k), -1, dtype=np.int64)
        scores[0, 0] = self.score
        positions[0, 0] = 0
        return scores, positions


def runtime(score: float = 0.8, *, course_index_map: dict[str, CourseIndexEntry] | None = None) -> RagRuntime:
    indexes = {}
    chunks = {}
    for name in {index for names in INDEXES_BY_MAJOR.values() for index in names}:
        chunk_id = f"chunk-{name}"
        indexes[name] = (FakeIndex(score), [chunk_id])
        chunks[chunk_id] = {
            "chunk_id": chunk_id,
            "source": f"{name}.pdf",
            "doc_type": "demo",
            "text": f"{name} 검색 문맥",
            "metadata": {"section_title": "demo section"},
        }
    return RagRuntime(
        model_key="fake",
        embedder=FakeEmbedder(),
        routers={major: RagRouter(major) for major in INDEXES_BY_MAJOR},
        indexes=indexes,
        chunks=chunks,
        top_k=2,
        course_index_map=course_index_map,
    )


def test_runtime_routes_bme_transliteration_and_returns_context() -> None:
    result = runtime().retrieve("그 피시알 그거 몇 단계라 했죠", major="bme")

    assert result["useRag"] is True
    assert result["major"] == "bme"
    assert "PCR" in result["matchedTerms"]
    assert "검색 문맥" in result["context"]
    assert result["results"][0]["score"] == 0.8


def test_runtime_skips_unrelated_sentence() -> None:
    result = runtime().retrieve("오늘 점심 메뉴가 무엇인가요", major="ai")

    assert result["useRag"] is False
    assert result["reason"] == "NO_TRIGGER"


def test_runtime_applies_major_score_gate() -> None:
    result = runtime(score=0.2).retrieve("합성곱의 특징 추출 원리", major="ai")

    assert result["useRag"] is False
    assert result["reason"] == "SCORE_BELOW_THRESHOLD"


def test_runtime_falls_back_to_primary_index_for_unregistered_course() -> None:
    # courseId가 RAG_COURSE_INDEX_MAP에 없으면 강의 인덱스는 섞이지 않고 전공 인덱스만 본다.
    result = runtime().retrieve(
        "그 피시알 그거 몇 단계라 했죠", major="bme", course_id="unregistered-course"
    )

    assert result["useRag"] is True
    assert result["indexes"] == ["major_biomedical_bioengineering"]


def test_runtime_narrows_to_course_registered_indexes() -> None:
    course_index_map = {
        "course-hss-1": CourseIndexEntry(
            major="hss",
            indexes=("major_humanities_social_sciences", "lecture_heo_korling"),
        )
    }
    result = runtime(course_index_map=course_index_map).retrieve(
        "기능주의와 갈등이론의 차이", major="auto", course_id="course-hss-1"
    )

    assert result["useRag"] is True
    # 과목이 확정되면 라우터 auto 비교 없이 등록된 전공/인덱스로 바로 검색한다.
    assert result["major"] == "hss"
    assert set(result["indexes"]) == {
        "major_humanities_social_sciences",
        "lecture_heo_korling",
    }
    assert "lecture_nam_relsoc" not in result["indexes"]


def test_parse_course_index_map_empty() -> None:
    assert parse_course_index_map("") == {}
    assert parse_course_index_map(None) == {}


def test_parse_course_index_map_valid() -> None:
    raw = (
        '{"course-1": {"major": "bme", '
        '"indexes": ["major_biomedical_bioengineering", "lecture_lee_molbio"]}}'
    )
    result = parse_course_index_map(raw)

    assert result == {
        "course-1": CourseIndexEntry(
            major="bme",
            indexes=("major_biomedical_bioengineering", "lecture_lee_molbio"),
        )
    }


def test_parse_course_index_map_rejects_invalid_major() -> None:
    with pytest.raises(ValueError, match="major"):
        parse_course_index_map('{"course-1": {"major": "unknown", "indexes": ["major_ai"]}}')


def test_parse_course_index_map_rejects_unknown_index_name() -> None:
    with pytest.raises(ValueError, match="unknown index names"):
        parse_course_index_map('{"course-1": {"major": "ai", "indexes": ["not_a_real_index"]}}')


def test_parse_course_index_map_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="파싱 실패"):
        parse_course_index_map("{not json")
