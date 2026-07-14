"""RAG Router — rule trigger + 질의 정규화 + score gate.

파이프라인 위치 (prototype/ai-worker의 RagClient 구현부에 해당):
  STT 문장 → route(): 음차 치환 + 필러 제거 + 용어 매칭 → useRag/query/reason
           → (트리거 시) 임베딩 검색 → apply_gate(): top-1 < 임계값이면 OFF

산출 스키마 (RouteDecision.to_json):
  {"useRag": true, "query": "...", "reason": ["GLOSSARY_TERM", "LECTURE_CONCEPT"]}

어휘 사전(lexicon) 소스:
  - GLOSSARY_TERM : data/raw/ai_glossary*.json 의 term_ko/term_en/abbr/aliases
  - LECTURE_CONCEPT: tools/content_part*.py (교재 원본)의 장별 key_terms
  - TRANSLITERATIONS: glossary aliases가 못 덮는 음차 보충 (하드 평가 실패 사례 기반)

ai-worker 포팅 시에는 export_lexicon()으로 JSON을 떨궈 tools/ 의존 없이 로드한다.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_RAW_DIR, ROOT

RAG_SCORE_THRESHOLD = 0.50  # eval/results_v2.md: kure 기준 negative 100% 차단 / positive 99% 통과

# 음차 → 코퍼스 표기 보충 사전 (glossary aliases에 없는 것만).
# 근거: eval/_miss_analysis_textbook_hard.txt 의 실패 사례.
TRANSLITERATIONS: dict[str, str] = {
    "에이치엔에스더블유": "HNSW",
    "케이 민즈": "K-평균 군집화",
    "케이민즈": "K-평균 군집화",
    "케이 평균": "K-평균",
    "트랜스퍼 러닝": "전이학습",
    "트랜스퍼러닝": "전이학습",
    "하이어라키컬 클러스터링": "계층적 군집",
    "엘에스티엠": "LSTM",
    "지알유": "GRU",
    "알오씨": "ROC",
    "에이유씨": "AUC",
    "엠에이이": "MAE",
    "알엠에스이": "RMSE",
    "엘원": "L1",
    "엘투": "L2",
    "데이터 리키지": "데이터 누수",
    "데이터 리케이지": "데이터 누수",
    "어그멘테이션": "데이터 증강",
    "백프로파게이션": "역전파",
    "포워드 체이닝": "전방향 추론",
    "백워드 체이닝": "후방향 추론",
    "배리언스": "분산",
    "피이에이에스": "PEAS",
    "스케일링 로": "스케일링 법칙",
    "덴스 검색": "밀집 검색",
    "스파스 검색": "희소 검색",
    "에이스타": "A* 탐색",
    "케이엔엔": "KNN",
    "에스브이엠": "SVM",
    "피시에이": "PCA",
    "챙킹": "청킹",
    "엘보 방법": "엘보우 방법",
    "라그": "RAG",
    "알에이지": "RAG",
}

# 교재에는 있으나 glossary·key_terms에 빠진 개념 패턴 보충 (LECTURE_CONCEPT).
# 근거: eval/results_router.md rule 미발동 목록 중 용어가 실제로 언급된 질의.
SUPPLEMENT_CONCEPTS: list[str] = [
    "ROC 곡선", "ROC", "AUC",
    "전방향 추론", "후방향 추론",
    "데이터 누수", "엘보우 방법", "HNSW", "IVF",
    "스케일링 법칙", "밀집 검색", "희소 검색", "하이브리드 검색",
    "리랭킹", "청킹", "온톨로지", "명제 논리", "술어 논리", "명제논리", "술어논리",
]

# 강의 발화의 담화 표지 — 임베딩 질의에서 정보가 없는 조각만 보수적으로 제거
FILLER_PATTERNS = [
    re.compile(r"^(어|음|자|그|저)\s+"),
    re.compile(r"그러니까\s*"),
    re.compile(r"뭐시기\s*"),
    re.compile(r"인가\s+그\s+"),
    re.compile(r"\s+그거\s+"),
    re.compile(r"\s+그게\s+"),
]


@dataclass
class RouteDecision:
    use_rag: bool
    query: str
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    score: float | None = None  # apply_gate 이후 top-1 유사도
    gated_off: bool = False     # score gate로 꺼졌는지

    def to_json(self) -> dict[str, Any]:
        reason = list(self.reasons)
        if self.gated_off:
            reason.append("SCORE_LOW")
        elif not self.use_rag and not reason:
            reason.append("NO_TRIGGER")
        return {"useRag": self.use_rag, "query": self.query, "reason": reason}


def _load_glossary_lexicon() -> list[tuple[str, str, str]]:
    """(패턴, 정식 용어, reason) 목록 — glossary 전 필드."""
    entries: list[tuple[str, str, str]] = []
    paths = sorted(DATA_RAW_DIR.glob("ai_glossary*.json"))
    if not paths:
        return entries
    terms = json.loads(paths[0].read_text(encoding="utf-8"))["terms"]
    for t in terms:
        patterns = {t["term_ko"], t.get("term_en") or "", t.get("abbr") or ""}
        patterns.update(t.get("aliases", []))
        for p in patterns:
            p = p.strip()
            if len(p) >= 2:
                entries.append((p, t["term_ko"], "GLOSSARY_TERM"))
    return entries


_TERM_PAREN_RE = re.compile(r"^([^(]+?)\s*(?:\(([^)]*)\))?$")


def _load_textbook_lexicon() -> list[tuple[str, str, str]]:
    """교재(tools/content_part*.py) 장별 key_terms → LECTURE_CONCEPT 패턴."""
    entries: list[tuple[str, str, str]] = []
    tools_dir = ROOT / "tools"
    for part in sorted(tools_dir.glob("content_part*.py")):
        spec = importlib.util.spec_from_file_location(part.stem, part)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue  # 교재 원본이 없어도 라우터는 동작해야 함
        for ch in getattr(module, "CHAPTERS", []):
            for kt in ch.get("key_terms", []):
                match = _TERM_PAREN_RE.match(kt["term"].strip())
                if not match:
                    continue
                ko = match.group(1).strip()
                if len(ko) >= 2:
                    entries.append((ko, ko, "LECTURE_CONCEPT"))
                for en in (match.group(2) or "").split(","):
                    en = en.strip()
                    if len(en) >= 2:
                        entries.append((en, ko, "LECTURE_CONCEPT"))
    return entries


class RagRouter:
    def __init__(self, score_threshold: float = RAG_SCORE_THRESHOLD) -> None:
        self.score_threshold = score_threshold
        # GLOSSARY_TERM을 먼저 넣고, 같은 패턴의 LECTURE_CONCEPT는 무시 (glossary 우선)
        self._lexicon: dict[str, tuple[str, str]] = {}  # 패턴(소문자) → (정식 용어, reason)
        supplements = [(p, p, "LECTURE_CONCEPT") for p in SUPPLEMENT_CONCEPTS]
        for pattern, canonical, reason in (
            _load_glossary_lexicon() + _load_textbook_lexicon() + supplements
        ):
            key = pattern.lower()
            if key not in self._lexicon:
                self._lexicon[key] = (canonical, reason)
        # ASCII 패턴은 단어 경계 필요 ("AI"가 "said"에 걸리지 않도록)
        self._ascii_res: dict[str, re.Pattern[str]] = {
            k: re.compile(rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])")
            for k in self._lexicon
            if k.isascii()
        }
        # 음차 치환은 긴 패턴 먼저
        self._translit = sorted(
            TRANSLITERATIONS.items(), key=lambda kv: len(kv[0]), reverse=True
        )

    # ── 1단: rule trigger + query 생성 ────────────────────────────────
    def route(self, sentence: str) -> RouteDecision:
        normalized = self.normalize(sentence)
        lowered = normalized.lower()

        matched: dict[str, str] = {}  # 정식 용어 → reason
        for pattern, (canonical, reason) in self._lexicon.items():
            if pattern in self._ascii_res:
                hit = bool(self._ascii_res[pattern].search(lowered))
            else:
                hit = pattern in lowered
            if hit and canonical not in matched:
                matched[canonical] = reason
            elif hit and reason == "GLOSSARY_TERM":
                matched[canonical] = reason  # glossary 우선

        reasons = sorted({r for r in matched.values()})
        # 질의 = 정규화 문장 + (문장에 아직 없는) 정식 용어 병기
        extra_terms = [t for t in matched if t.lower() not in lowered]
        query = normalized if not extra_terms else f"{normalized} {' '.join(extra_terms)}"
        return RouteDecision(
            use_rag=bool(matched),
            query=query,
            reasons=reasons,
            matched_terms=sorted(matched),
        )

    def normalize(self, sentence: str) -> str:
        """음차 → 코퍼스 표기 치환 + 담화 필러 제거."""
        text = sentence.strip()
        for src, dst in self._translit:
            if src in text:
                text = text.replace(src, dst)
        for pattern in FILLER_PATTERNS:
            text = pattern.sub(" ", text)
        return re.sub(r"\s+", " ", text).strip()

    # ── 2단: score gate ───────────────────────────────────────────────
    def apply_gate(self, decision: RouteDecision, top1_score: float) -> RouteDecision:
        decision.score = top1_score
        if decision.use_rag and top1_score < self.score_threshold:
            decision.use_rag = False
            decision.gated_off = True
        return decision

    # ── ai-worker 포팅용 lexicon 내보내기 ─────────────────────────────
    def export_lexicon(self, path: Path) -> None:
        payload = {
            "score_threshold": self.score_threshold,
            "transliterations": TRANSLITERATIONS,
            "lexicon": [
                {"pattern": k, "canonical": v[0], "reason": v[1]}
                for k, v in sorted(self._lexicon.items())
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    # 수동 확인: python src/router.py "케이민즈 그거 어떤 순서로 돌아간다 했죠"
    router = RagRouter()
    sentence = " ".join(sys.argv[1:]) or "컨볼루션이 이미지에서 특징을 뽑아낸다고 했죠"
    decision = router.route(sentence)
    print(json.dumps(decision.to_json(), ensure_ascii=False, indent=2))
    print(f"matched: {decision.matched_terms}")
