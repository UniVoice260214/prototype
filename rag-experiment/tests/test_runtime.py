from __future__ import annotations

import numpy as np

from router import RagRouter
from runtime import INDEXES_BY_MAJOR, RagRuntime


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


def runtime(score: float = 0.8) -> RagRuntime:
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
