"""데모용 전공 Router + KURE/FAISS 검색 런타임."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from config import CHUNKS_PATH
from embed import get_embedder, load_chunks
from router import RagRouter, RouteDecision, load_routers
from search import load_index

INDEXES_BY_MAJOR: dict[str, tuple[str, ...]] = {
    "ai": ("major_ai", "lecture_kim_i2a"),
    "hss": (
        "major_humanities_social_sciences",
        "lecture_heo_korling",
        "lecture_nam_relsoc",
    ),
    "bme": ("major_biomedical_bioengineering", "lecture_lee_molbio"),
}


def course_index_name(course_id: str) -> str:
    """업로드 자료로 누적되는 과목별 인덱스 이름 (indexer_daemon 과 계약)."""
    return f"lecture_{course_id}"


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
    ) -> None:
        self.model_key = model_key
        self.embedder = embedder
        self.routers = routers
        self.indexes = indexes
        self.chunks = chunks
        self.top_k = max(1, top_k)
        self.context_max_chars = max(500, context_max_chars)
        self._search_lock = threading.Lock()
        # 디스크에 없다고 확인된 과목 인덱스 — 요청마다 디스크를 두드리지 않기 위한
        # 네거티브 캐시. /admin/reload 가 지운다.
        self._missing_course_indexes: set[str] = set()

    # ── 과목별 lecture 인덱스 (업로드 자료 누적분) ────────────────────

    def ensure_course_index(self, course_id: str) -> str | None:
        """lecture_{courseId} 인덱스를 (필요 시 디스크에서) 로드해 이름을 돌려준다.

        인덱서 데몬이 os.replace 로 원자적으로 갱신하므로 파일이 있으면 항상
        완전한 상태다. 없으면 None — 아직 업로드된 자료가 없는 과목.
        """
        if not course_id:
            return None
        name = course_index_name(course_id)
        if name in self.indexes:
            return name
        if name in self._missing_course_indexes:
            return None
        return self.reload_course_index(course_id)

    def reload_course_index(self, course_id: str) -> str | None:
        """디스크에서 과목 인덱스+청크를 (다시) 읽는다. indexer 가 갱신 후 호출."""
        from search import load_index

        name = course_index_name(course_id)
        chunks_path = CHUNKS_PATH.parent / f"{name}.jsonl"
        with self._search_lock:
            try:
                loaded = load_index(self.model_key, name)
            except FileNotFoundError:
                self._missing_course_indexes.add(name)
                self.indexes.pop(name, None)
                return None
            self.indexes[name] = loaded
            if chunks_path.exists():
                with chunks_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            chunk = json.loads(line)
                            self.chunks[chunk["chunk_id"]] = chunk
            self._missing_course_indexes.discard(name)
        return name

    @classmethod
    def load(
        cls,
        model_key: str = "kure",
        *,
        top_k: int = 3,
        context_max_chars: int = 4000,
    ) -> "RagRuntime":
        chunks = {chunk["chunk_id"]: chunk for chunk in load_chunks()}
        routers = load_routers()
        index_names = sorted({name for names in INDEXES_BY_MAJOR.values() for name in names})
        indexes = {name: load_index(model_key, name) for name in index_names}
        embedder = get_embedder(model_key)
        return cls(
            model_key=model_key,
            embedder=embedder,
            routers=routers,
            indexes=indexes,
            chunks=chunks,
            top_k=top_k,
            context_max_chars=context_max_chars,
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
        if major != "auto" and major not in self.routers:
            raise ValueError(f"unsupported major: {major}")

        # 업로드 자료로 누적된 과목 인덱스가 있으면 함께 검색한다.
        # (락 안에서 로드하면 검색 락과 중첩되므로 여기서 미리 해석한다.)
        course_index = self.ensure_course_index(course_id)

        selected_routers = self.routers.values() if major == "auto" else (self.routers[major],)
        decisions = [router.route(sentence) for router in selected_routers]
        triggered = [decision for decision in decisions if decision.use_rag]

        # 과목별 glossary에만 있는 용어도 고정 전공 모드에서는 검색할 수 있게 한다.
        if not triggered and major != "auto" and glossary_hits:
            hinted = self.routers[major].route(f"{sentence} {' '.join(glossary_hits)}")
            if hinted.use_rag:
                triggered = [hinted]

        if not triggered:
            return self._off_response(started, reason="NO_TRIGGER", major=major)

        candidates: list[Candidate] = []
        with self._search_lock:
            for decision in triggered:
                router = self.routers[decision.major]
                hits = self._search(decision, course_index=course_index)
                if not hits:
                    continue
                router.apply_gate(decision, hits[0].score)
                candidates.append(Candidate(router=router, decision=decision, hits=hits))

        if not candidates:
            return self._off_response(started, reason="NO_RESULTS", major=major)

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
            "results": results,
            "context": context,
            "latencyMs": self._latency_ms(started),
        }

    def _search(
        self, decision: RouteDecision, *, course_index: str | None = None
    ) -> list[SearchHit]:
        vector = np.asarray(self.embedder.encode([decision.query]), dtype=np.float32)
        norms = np.linalg.norm(vector, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vector = vector / norms

        index_names: tuple[str, ...] = INDEXES_BY_MAJOR[decision.major]
        if course_index and course_index in self.indexes:
            index_names = index_names + (course_index,)

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
            "results": [],
            "context": None,
            "latencyMs": self._latency_ms(started),
        }

    @staticmethod
    def _latency_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 1)
