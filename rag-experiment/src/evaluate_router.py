"""RAG Router 평가 — rule trigger / score gate / 정규화 검색 개선폭.

실행: python src/evaluate_router.py [--threshold 0.50] [--output eval/results_router.md]

세 가지를 측정한다:
1. rule 단계: positive 질의에서 트리거 재현율, negative에서 오발동률
2. 최종 결정(rule + score gate, kure·통합 인덱스): positive 통과율 / negative 차단율
   + 발화형 테스트 문장(eval/router_test_sentences.json) 판정표
3. 검색 개선폭: queries_textbook_hard를 원문 질의 vs 라우터 정규화 질의로
   각각 검색(major_ai)했을 때 R@1/R@5 비교 — 음차 치환의 효과 측정
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import EVAL_DIR
from embed import get_embedder, load_chunks
from router import RagRouter
from search import load_index

MODEL = "kure"  # 확정 모델 (REPORT.md 5절)

POSITIVE_FILES = [
    "queries_positive_v2.json",
    "queries_hard_v2.json",          # negative 10개는 아래서 분리
    "queries_hard_newterms.json",
    "queries_textbook.json",
    "queries_textbook_hard.json",
]


def load_sets() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    for fname in POSITIVE_FILES:
        for q in json.loads((EVAL_DIR / fname).read_text(encoding="utf-8")):
            q = {**q, "source": fname}
            (positives if q["answer_chunk_ids"] else negatives).append(q)
    return positives, negatives


def recall_at(retrieved: list[str], answers: set[str], k: int) -> bool:
    return any(cid in answers for cid in retrieved[:k])


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Router 평가")
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--output", type=Path, default=EVAL_DIR / "results_router.md")
    args = parser.parse_args()

    router = RagRouter(score_threshold=args.threshold)
    positives, negatives = load_sets()
    utterances = json.loads(
        (EVAL_DIR / "router_test_sentences.json").read_text(encoding="utf-8")
    )
    print(f"positive {len(positives)} / negative {len(negatives)} / 발화 {len(utterances)}")

    # ── 1) rule 단계 ──────────────────────────────────────────────────
    pos_decisions = [router.route(q["query"]) for q in positives]
    neg_decisions = [router.route(q["query"]) for q in negatives]
    pos_rule_on = sum(d.use_rag for d in pos_decisions)
    neg_rule_on = sum(d.use_rag for d in neg_decisions)
    pos_missed_rule = [
        q["query"] for q, d in zip(positives, pos_decisions) if not d.use_rag
    ]

    # ── 2) score gate (kure, 통합 인덱스 — 임계값 산정과 동일 조건) ──
    embedder = get_embedder(MODEL)
    index_global, _ = load_index(MODEL)

    def top1_scores(texts: list[str]) -> list[float]:
        vectors = embedder.encode(texts).astype(np.float32)
        scores, _ = index_global.search(vectors, 1)
        return [float(s[0]) for s in scores]

    pos_on = [(q, d) for q, d in zip(positives, pos_decisions) if d.use_rag]
    neg_on = [(q, d) for q, d in zip(negatives, neg_decisions) if d.use_rag]
    for (_, d), score in zip(pos_on, top1_scores([d.query for _, d in pos_on])):
        router.apply_gate(d, score)
    if neg_on:
        for (_, d), score in zip(neg_on, top1_scores([d.query for _, d in neg_on])):
            router.apply_gate(d, score)
    pos_final_on = sum(d.use_rag for d in pos_decisions)
    neg_final_on = sum(d.use_rag for d in neg_decisions)
    pos_gated_off = [
        (q["query"], d.score) for q, d in zip(positives, pos_decisions) if d.gated_off
    ]

    # 발화형 테스트 문장
    utt_decisions = [router.route(u["text"]) for u in utterances]
    utt_on = [d for d in utt_decisions if d.use_rag]
    if utt_on:
        for d, score in zip(utt_on, top1_scores([d.query for d in utt_on])):
            router.apply_gate(d, score)
    utt_rows = []
    n_utt_correct, n_utt_scored = 0, 0
    for u, d in zip(utterances, utt_decisions):
        actual = "true" if d.use_rag else "false"
        if u["expect"] == "either":
            verdict = "—"
        else:
            n_utt_scored += 1
            ok = actual == u["expect"]
            n_utt_correct += ok
            verdict = "✅" if ok else "❌"
        utt_rows.append((u, d, actual, verdict))

    # ── 3) 정규화 질의 검색 개선폭 (textbook_hard, major_ai) ─────────
    hard = json.loads((EVAL_DIR / "queries_textbook_hard.json").read_text(encoding="utf-8"))
    index_major, chunk_ids = load_index(MODEL, "major_ai")

    def search_top5(texts: list[str]) -> list[list[str]]:
        vectors = embedder.encode(texts).astype(np.float32)
        _, idx = index_major.search(vectors, 5)
        return [[chunk_ids[i] for i in row if i != -1] for row in idx]

    raw_results = search_top5([q["query"] for q in hard])
    norm_queries = [router.route(q["query"]).query for q in hard]
    norm_results = search_top5(norm_queries)
    uplift: dict[str, dict[str, float]] = {}
    for label, results in [("원문 질의", raw_results), ("라우터 정규화 질의", norm_results)]:
        n = len(hard)
        uplift[label] = {
            "R@1": sum(recall_at(r, set(q["answer_chunk_ids"]), 1) for q, r in zip(hard, results)) / n,
            "R@5": sum(recall_at(r, set(q["answer_chunk_ids"]), 5) for q, r in zip(hard, results)) / n,
        }

    # ── 리포트 ────────────────────────────────────────────────────────
    lines = [
        "# RAG Router 평가",
        "",
        f"- 모델: {MODEL} / score gate 임계값: {args.threshold} (통합 인덱스 top-1)",
        f"- 라벨 데이터: positive {len(positives)} / negative {len(negatives)}"
        f" / 발화형 테스트 문장 {len(utterances)}",
        "",
        "## 1. 단계별 라우팅 정확도",
        "",
        "| 단계 | positive ON (재현율) | negative OFF (차단율) |",
        "|------|----:|----:|",
        f"| rule만 | {pos_rule_on}/{len(positives)} ({pos_rule_on / len(positives):.1%})"
        f" | {len(negatives) - neg_rule_on}/{len(negatives)}"
        f" ({(len(negatives) - neg_rule_on) / len(negatives):.1%}) |",
        f"| rule + score gate | {pos_final_on}/{len(positives)}"
        f" ({pos_final_on / len(positives):.1%})"
        f" | {len(negatives) - neg_final_on}/{len(negatives)}"
        f" ({(len(negatives) - neg_final_on) / len(negatives):.1%}) |",
        "",
        "### rule 미발동 positive (트리거 사각지대)",
        "",
    ]
    if pos_missed_rule:
        lines += [f"- {q}" for q in pos_missed_rule]
    else:
        lines.append("- 없음")
    lines += ["", "### score gate가 끈 positive (과차단)", ""]
    if pos_gated_off:
        lines += [f"- [{s:.3f}] {q}" for q, s in pos_gated_off]
    else:
        lines.append("- 없음")

    lines += [
        "",
        "## 2. 발화형 테스트 문장 판정",
        "",
        "| 판정 | 기대 | 실제 | score | reason | 문장 |",
        "|:--:|:--:|:--:|----:|------|------|",
    ]
    for u, d, actual, verdict in utt_rows:
        score = f"{d.score:.3f}" if d.score is not None else "-"
        reason = ",".join(d.to_json()["reason"])
        lines.append(
            f"| {verdict} | {u['expect']} | {actual} | {score} | {reason} | {u['text']} |"
        )
    lines.append("")
    lines.append(
        f"발화 정확도: **{n_utt_correct}/{n_utt_scored}**"
        f" ({n_utt_correct / n_utt_scored:.1%}, 'either' 제외)"
    )

    lines += [
        "",
        "## 3. 라우터 정규화의 검색 개선폭 (queries_textbook_hard 48개, major_ai)",
        "",
        "| 질의 | R@1 | R@5 |",
        "|------|----:|----:|",
    ]
    for label, m in uplift.items():
        lines.append(f"| {label} | {m['R@1']:.3f} | {m['R@5']:.3f} |")

    report = "\n".join(lines) + "\n"
    print("\n" + report)
    args.output.write_text(report, encoding="utf-8")
    print(f"결과 저장: {args.output}")


if __name__ == "__main__":
    main()
