"""데모용 전공 Router + KURE/FAISS 검색 런타임."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from config import INDEX_SUBSETS, MAJOR_PRIMARY_INDEX
from embed import get_embedder, load_chunks
from router import RagRouter, RouteDecision, load_routers
from search import load_index

# 인덱스 로딩용 상위집합 — 전공별로 "존재할 수 있는" 모든 인덱스(전공 인덱스 +
# 그 전공의 모든 강의 인덱스)를 기동 시 미리 메모리에 올려 둔다. 실제 검색 시
# 어떤 인덱스를 볼지는 courseId 기준으로 좁혀진다 (course_index_map, _indexes_for 참조).
INDEXES_BY_MAJOR: dict[str, tuple[str, ...]] = {
    "ai": ("major_ai", "lecture_kim_i2a"),
    "hss": (
        "major_humanities_social_sciences",
        "lecture_heo_korling",
        "lecture_nam_relsoc",
    ),
    "bme": ("major_biomedical_bioengineering", "lecture_lee_molbio"),
}


@dataclass(frozen=True)
class CourseIndexEntry:
    """RAG_COURSE_INDEX_MAP 한 과목분 엔트리 — 확정된 전공과 검색할 인덱스 목록."""

    major: str
    indexes: tuple[str, ...]


def parse_course_index_map(raw: str | None) -> dict[str, CourseIndexEntry]:
    """RAG_COURSE_INDEX_MAP 환경변수(JSON)를 파싱하고 즉시 검증한다.

    형식: {"<courseId>": {"major": "hss", "indexes": ["major_humanities_social_sciences", "lecture_heo_korling"]}}

    잘못된 major/index 이름은 무음으로 넘어가지 않고 기동 시점에 바로 실패시킨다 —
    오타 하나가 잘못된 강의자료를 프로덕션 검색에 섞이게 하는 사고를 막기 위함이다.
    등록되지 않은 courseId는 major만 검색하는 것으로 폴백한다(_indexes_for 참조).
    """
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"RAG_COURSE_INDEX_MAP JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("RAG_COURSE_INDEX_MAP must be a JSON object")

    result: dict[str, CourseIndexEntry] = {}
    for course_id, entry in parsed.items():
        if not isinstance(entry, dict):
            raise ValueError(f"RAG_COURSE_INDEX_MAP[{course_id}] must be a JSON object")
        major = entry.get("major")
        indexes = entry.get("indexes")
        if major not in MAJOR_PRIMARY_INDEX:
            raise ValueError(
                f"RAG_COURSE_INDEX_MAP[{course_id}].major must be one of "
                f"{sorted(MAJOR_PRIMARY_INDEX)} (got: {major!r})"
            )
        if not isinstance(indexes, list) or not indexes:
            raise ValueError(f"RAG_COURSE_INDEX_MAP[{course_id}].indexes must be a non-empty list")
        invalid = [name for name in indexes if name not in INDEX_SUBSETS]
        if invalid:
            raise ValueError(
                f"RAG_COURSE_INDEX_MAP[{course_id}].indexes has unknown index names: {invalid} "
                f"(valid: {sorted(INDEX_SUBSETS)})"
            )
        result[str(course_id)] = CourseIndexEntry(
            major=str(major), indexes=tuple(str(name) for name in indexes)
        )
    return result


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    score: float
    index_name: str
    chunk: dict[str, Any]


@dataclass
class Candidate:
    router: RagRouter
    decision: RouteDecision
    hits: list[SearchHit]
    index_names: tuple[str, ...]

    @property
    def top_score(self) -> float:
        return self.hits[0].score if self.hits else -1.0


class RagRuntime:
    """모델과 모든 데모 인덱스를 한 번만 로드해 재사용한다."""

    def __init__(
        self,
        *,
        model_key: str,
        embedder: Any,
        routers: dict[str, RagRouter],
        indexes: dict[str, tuple[Any, list[str]]],
        chunks: dict[str, dict[str, Any]],
        top_k: int = 3,
        context_max_chars: int = 4000,
        course_index_map: dict[str, CourseIndexEntry] | None = None,
    ) -> None:
        self.model_key = model_key
        self.embedder = embedder
        self.routers = routers
        self.indexes = indexes
        self.chunks = chunks
        self.top_k = max(1, top_k)
        self.context_max_chars = max(500, context_max_chars)
        self.course_index_map = course_index_map or {}
        self._search_lock = threading.Lock()

    @classmethod
    def load(
        cls,
        model_key: str = "kure",
        *,
        top_k: int = 3,
        context_max_chars: int = 4000,
        course_index_map_raw: str = "",
    ) -> "RagRuntime":
        chunks = {chunk["chunk_id"]: chunk for chunk in load_chunks()}
        routers = load_routers()
        index_names = sorted({name for names in INDEXES_BY_MAJOR.values() for name in names})
        indexes = {name: load_index(model_key, name) for name in index_names}
        embedder = get_embedder(model_key)
        course_index_map = parse_course_index_map(course_index_map_raw)
        return cls(
            model_key=model_key,
            embedder=embedder,
            routers=routers,
            indexes=indexes,
            chunks=chunks,
            top_k=top_k,
            context_max_chars=context_max_chars,
            course_index_map=course_index_map,
        )

    def retrieve(
        self,
        sentence: str,
        *,
        major: str = "auto",
        glossary_hits: list[str] | None = None,
        course_id: str = "",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        # courseId가 RAG_COURSE_INDEX_MAP에 등록돼 있으면 과목이 이미 확정된 것이므로
        # 요청의 major(="auto" 포함)를 그 과목의 전공으로 덮어쓴다 — 라우터 비교가 불필요해진다.
        course_entry = self.course_index_map.get(course_id) if course_id else None
        effective_major = course_entry.major if course_entry else major
        if effective_major != "auto" and effective_major not in self.routers:
            raise ValueError(f"unsupported major: {effective_major}")

        selected_routers = (
            self.routers.values() if effective_major == "auto" else (self.routers[effective_major],)
        )
        decisions = [router.route(sentence) for router in selected_routers]
        triggered = [decision for decision in decisions if decision.use_rag]

        # 과목별 glossary에만 있는 용어도 고정 전공 모드에서는 검색할 수 있게 한다.
        if not triggered and effective_major != "auto" and glossary_hits:
            hinted = self.routers[effective_major].route(f"{sentence} {' '.join(glossary_hits)}")
            if hinted.use_rag:
                triggered = [hinted]

        if not triggered:
            return self._off_response(started, reason="NO_TRIGGER", major=effective_major)

        candidates: list[Candidate] = []
        with self._search_lock:
            for decision in triggered:
                router = self.routers[decision.major]
                index_names = self._indexes_for(decision.major, course_entry)
                hits = self._search(decision, index_names)
                if not hits:
                    continue
                router.apply_gate(decision, hits[0].score)
                candidates.append(
                    Candidate(router=router, decision=decision, hits=hits, index_names=index_names)
                )

        if not candidates:
            return self._off_response(started, reason="NO_RESULTS", major=effective_major)

        eligible = [candidate for candidate in candidates if candidate.decision.use_rag]
        if not eligible:
            gated = max(candidates, key=lambda candidate: candidate.top_score)
            return self._off_response(
                started,
                reason="SCORE_BELOW_THRESHOLD",
                major=gated.decision.major,
                decision=gated.decision,
                top_score=gated.top_score,
            )

        winner = max(eligible, key=lambda candidate: candidate.top_score)
        results = [self._result_payload(hit) for hit in winner.hits[: self.top_k]]
        context = self._format_context(winner.hits[: self.top_k])
        return {
            "useRag": True,
            "reason": "ROUTED",
            "major": winner.decision.major,
            "query": winner.decision.query,
            "reasons": winner.decision.reasons,
            "matchedTerms": winner.decision.matched_terms,
            "topScore": round(winner.top_score, 4),
            "threshold": winner.router.score_threshold,
            "indexes": list(winner.index_names),
            "results": results,
            "context": context,
            "latencyMs": self._latency_ms(started),
        }

    def _indexes_for(
        self, decision_major: str, course_entry: CourseIndexEntry | None
    ) -> tuple[str, ...]:
        """courseId가 등록돼 있으면 그 과목의 인덱스 목록을, 아니면 전공 인덱스만 검색한다."""
        if course_entry is not None:
            return course_entry.indexes
        return (MAJOR_PRIMARY_INDEX[decision_major],)

    def _search(self, decision: RouteDecision, index_names: tuple[str, ...]) -> list[SearchHit]:
        vector = np.asarray(self.embedder.encode([decision.query]), dtype=np.float32)
        norms = np.linalg.norm(vector, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vector = vector / norms

        by_chunk: dict[str, SearchHit] = {}
        for index_name in index_names:
            index, chunk_ids = self.indexes[index_name]
            scores, positions = index.search(vector, self.top_k)
            for score, position in zip(scores[0], positions[0]):
                if position == -1:
                    continue
                chunk_id = chunk_ids[int(position)]
                hit = SearchHit(
                    chunk_id=chunk_id,
                    score=float(score),
                    index_name=index_name,
                    chunk=self.chunks.get(chunk_id, {}),
                )
                previous = by_chunk.get(chunk_id)
                if previous is None or hit.score > previous.score:
                    by_chunk[chunk_id] = hit
        return sorted(by_chunk.values(), key=lambda hit: hit.score, reverse=True)

    @staticmethod
    def _result_payload(hit: SearchHit) -> dict[str, Any]:
        metadata = hit.chunk.get("metadata") or {}
        return {
            "chunkId": hit.chunk_id,
            "source": hit.chunk.get("source", "unknown"),
            "docType": hit.chunk.get("doc_type", "unknown"),
            "section": metadata.get("section_title") or metadata.get("chapter") or "",
            "index": hit.index_name,
            "score": round(hit.score, 4),
        }

    def _format_context(self, hits: list[SearchHit]) -> str:
        blocks: list[str] = []
        used = 0
        for rank, hit in enumerate(hits, start=1):
            payload = self._result_payload(hit)
            header = (
                f"[검색 근거 {rank}] source={payload['source']} "
                f"section={payload['section']} score={payload['score']}"
            )
            block = f"{header}\n{hit.chunk.get('text', '')}".strip()
            remaining = self.context_max_chars - used
            if remaining <= 0:
                break
            if len(block) > remaining:
                block = block[:remaining]
            blocks.append(block)
            used += len(block) + 2
        return "\n\n".join(blocks)

    def _off_response(
        self,
        started: float,
        *,
        reason: str,
        major: str,
        decision: RouteDecision | None = None,
        top_score: float | None = None,
    ) -> dict[str, Any]:
        return {
            "useRag": False,
            "reason": reason,
            "major": decision.major if decision else major,
            "query": decision.query if decision else "",
            "reasons": decision.reasons if decision else [],
            "matchedTerms": decision.matched_terms if decision else [],
            "topScore": round(top_score, 4) if top_score is not None else None,
            "indexes": None,
            "results": [],
            "context": None,
            "latencyMs": self._latency_ms(started),
        }

    @staticmethod
    def _latency_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 1)
