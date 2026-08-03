"""세 모델 전체에 대해 Recall@{1,3,5}, MRR, Full-Recall@5 평가 + top-1 점수 분석.

실행: python src/evaluate.py [--queries eval/queries.json] [--topk 5]
                             [--output eval/results.md]

- positive 질의: answer_chunk_ids 중 하나라도 top-k에 있으면 hit
- Full-Recall@k: 정답 chunk '전부'가 top-k에 포함된 질의 비율
- negative 질의(answer_chunk_ids: []): recall/MRR 집계에서 제외하고
  top-1 점수 분포 비교와 임계값 필터링 분석에 사용 (RAG OFF 케이스)
- 인덱스 없는 모델, API 오류가 난 모델은 경고 후 건너뜀
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import EVAL_DIR, INDEX_SUBSETS, MODELS, RESULTS_PATH
from embed import get_embedder
from search import load_index

RECALL_KS = (1, 3, 5)
THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(9)]  # 0.30 ~ 0.70


def load_queries(path: Path) -> list[dict[str, Any]]:
    queries = json.loads(path.read_text(encoding="utf-8"))
    for q in queries:
        assert q.get("query") and isinstance(q.get("answer_chunk_ids"), list), (
            f"형식 오류: {q}"
        )
    return queries


# ── 모델별 검색 실행 ──────────────────────────────────────────────────


def evaluate_model(
    model_key: str,
    queries: list[dict[str, Any]],
    topk: int,
    index_name: str | None = None,
) -> list[dict[str, Any]] | None:
    """질의별 순위/점수 기록. 인덱스 없거나 오류 시 None."""
    try:
        index, chunk_ids = load_index(model_key, index_name)
    except FileNotFoundError:
        print(f"⚠️  [{model_key}] 인덱스 없음 — 건너뜀 (python src/embed.py --model {model_key})")
        return None

    try:
        embedder = get_embedder(model_key)  # 질의도 인덱스와 같은 모델로 임베딩
        vectors = embedder.encode([q["query"] for q in queries]).astype(np.float32)
        scores, indices = index.search(vectors, topk)
    except Exception as exc:
        # 한 모델의 API/네트워크 오류가 전체 평가를 죽이지 않도록 격리
        print(f"⚠️  [{model_key}] 평가 실패 — 건너뜀: {type(exc).__name__}: {exc}")
        return None

    rows: list[dict[str, Any]] = []
    for q, idx_row, score_row in zip(queries, indices, scores):
        retrieved = [chunk_ids[i] for i in idx_row if i != -1]
        answers = set(q["answer_chunk_ids"])
        answer_ranks = [
            rank for rank, cid in enumerate(retrieved, start=1) if cid in answers
        ]
        rows.append(
            {
                "query": q["query"],
                "query_type": q.get("query_type", "unknown"),
                "is_negative": not answers,
                "first_rank": answer_ranks[0] if answer_ranks else None,
                "found": len(answer_ranks),
                "n_answers": len(answers),
                "top1_score": float(score_row[0]) if len(score_row) else 0.0,
                "retrieved": retrieved,
            }
        )
    return rows


# ── 집계 ──────────────────────────────────────────────────────────────


def metrics_of(rows: list[dict[str, Any]], topk: int) -> dict[str, float]:
    """positive 질의 그룹의 Recall@k / MRR / Full-Recall@topk."""
    n = len(rows)
    result: dict[str, float] = {"n": n}
    for k in RECALL_KS:
        result[f"recall@{k}"] = (
            sum(1 for r in rows if r["first_rank"] and r["first_rank"] <= k) / n
        )
    result["mrr"] = sum(1 / r["first_rank"] for r in rows if r["first_rank"]) / n
    result[f"full_recall@{topk}"] = (
        sum(1 for r in rows if r["found"] == r["n_answers"]) / n
    )
    return result


def aggregate(
    rows: list[dict[str, Any]], topk: int
) -> dict[str, dict[str, float]]:
    """{'전체' + query_type: metrics} — negative는 제외."""
    positives = [r for r in rows if not r["is_negative"]]
    groups: dict[str, list[dict[str, Any]]] = {"전체": positives}
    for row in positives:
        groups.setdefault(row["query_type"], []).append(row)
    return {name: metrics_of(items, topk) for name, items in groups.items() if items}


def score_split(rows: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    pos = [r["top1_score"] for r in rows if not r["is_negative"]]
    neg = [r["top1_score"] for r in rows if r["is_negative"]]
    return pos, neg


# ── 리포트 ────────────────────────────────────────────────────────────


def build_report(
    all_rows: dict[str, list[dict[str, Any]]],
    topk: int,
    source_label: str,
    n_queries: int,
) -> str:
    query_types: list[str] = []
    for rows in all_rows.values():
        for row in rows:
            if row["query_type"] not in query_types:
                query_types.append(row["query_type"])
        break  # 질의 순서는 모델과 무관

    lines = [
        "# 임베딩 모델 비교 평가 결과 (확장 지표)",
        "",
        f"- 질의 파일: {source_label} (총 {n_queries}개) / top-k = {topk}",
        f"- 평가 모델: {', '.join(all_rows) if all_rows else '(없음)'}",
        f"- Full-Recall@{topk}: 정답 chunk 전부가 top-{topk}에 포함된 질의 비율",
        "",
        "## 전체 평균 (positive 질의만)",
        "",
        f"| 모델 | R@1 | R@3 | R@5 | MRR | Full-R@{topk} | n |",
        "|------|----:|----:|----:|----:|------:|---:|",
    ]
    aggs = {key: aggregate(rows, topk) for key, rows in all_rows.items()}
    for model_key, agg in aggs.items():
        m = agg["전체"]
        lines.append(
            f"| {model_key} | {m['recall@1']:.3f} | {m['recall@3']:.3f} "
            f"| {m['recall@5']:.3f} | {m['mrr']:.3f} "
            f"| {m[f'full_recall@{topk}']:.3f} | {int(m['n'])} |"
        )

    lines += ["", "## query_type별 분리 집계", ""]
    lines.append(f"| 모델 | query_type | R@1 | R@3 | R@5 | MRR | Full-R@{topk} | n |")
    lines.append("|------|-----------|----:|----:|----:|----:|------:|---:|")
    for model_key, agg in aggs.items():
        for query_type in query_types:
            if query_type not in agg:
                continue
            m = agg[query_type]
            lines.append(
                f"| {model_key} | {query_type} | {m['recall@1']:.3f} "
                f"| {m['recall@3']:.3f} | {m['recall@5']:.3f} | {m['mrr']:.3f} "
                f"| {m[f'full_recall@{topk}']:.3f} | {int(m['n'])} |"
            )

    # top-1 점수 분포 (positive vs negative)
    has_negative = any(
        row["is_negative"] for rows in all_rows.values() for row in rows
    )
    if has_negative:
        lines += [
            "",
            "## top-1 유사도 점수 분포 (positive vs negative)",
            "",
            "| 모델 | positive 평균±표준편차 | negative 평균±표준편차 | 평균 차이 |",
            "|------|--------------------:|--------------------:|--------:|",
        ]
        for model_key, rows in all_rows.items():
            pos, neg = score_split(rows)
            pos_mean, pos_std = float(np.mean(pos)), float(np.std(pos))
            neg_mean, neg_std = float(np.mean(neg)), float(np.std(neg))
            lines.append(
                f"| {model_key} | {pos_mean:.4f} ± {pos_std:.4f} "
                f"| {neg_mean:.4f} ± {neg_std:.4f} | {pos_mean - neg_mean:+.4f} |"
            )

        lines += [
            "",
            "## 임계값별 필터링 효과",
            "",
            "top-1 점수 < 임계값이면 'RAG OFF'로 판정한다고 가정.",
            "셀 = negative 차단율 / positive 통과율 (둘 다 높을수록 좋음)",
            "",
            "| 임계값 | " + " | ".join(all_rows) + " |",
            "|-------:|" + "|".join(["------:"] * len(all_rows)) + "|",
        ]
        for threshold in THRESHOLDS:
            cells = []
            for model_key, rows in all_rows.items():
                pos, neg = score_split(rows)
                blocked = sum(1 for s in neg if s < threshold) / len(neg)
                passed = sum(1 for s in pos if s >= threshold) / len(pos)
                cells.append(f"{blocked:.0%} / {passed:.0%}")
            lines.append(f"| {threshold:.2f} | " + " | ".join(cells) + " |")

    # R@5 미검색 질의 (검수용)
    lines += ["", "## R@5 미검색 질의 (모델별)", ""]
    for model_key, rows in all_rows.items():
        missed = [r for r in rows if not r["is_negative"] and not r["first_rank"]]
        if not missed:
            lines.append(f"- **{model_key}**: 없음")
            continue
        lines.append(f"- **{model_key}**: {len(missed)}개")
        for row in missed:
            lines.append(
                f"  - ({row['query_type']}) {row['query']} "
                f"→ top-{topk}: {', '.join(row['retrieved'])}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Recall@k / MRR / 점수 분석 평가")
    parser.add_argument(
        "--queries", type=Path, nargs="+", default=[EVAL_DIR / "queries.json"],
        help="평가 질의 JSON (복수 지정 시 병합, 기본: eval/queries.json)",
    )
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument(
        "--index", choices=sorted(INDEX_SUBSETS), default=None,
        help="분리 인덱스 이름 (생략 시 통합 인덱스)",
    )
    parser.add_argument(
        "--output", type=Path, default=RESULTS_PATH,
        help="결과 마크다운 경로 (기본: eval/results.md)",
    )
    args = parser.parse_args()

    queries: list[dict[str, Any]] = []
    for queries_path in args.queries:
        if not queries_path.exists():
            sys.exit(f"질의 파일 없음: {queries_path}")
        queries.extend(load_queries(queries_path))
    source_label = ", ".join(f"`{p.name}`" for p in args.queries)
    n_negative = sum(1 for q in queries if not q["answer_chunk_ids"])
    print(f"질의 {len(queries)}개 로드 (positive {len(queries) - n_negative} / "
          f"negative {n_negative}): {source_label}")

    all_rows: dict[str, list[dict[str, Any]]] = {}
    for model_key in MODELS:
        rows = evaluate_model(model_key, queries, args.topk, index_name=args.index)
        if rows is not None:
            all_rows[model_key] = rows

    if args.index:
        source_label = f"{source_label} (index: `{args.index}`)"
    report = build_report(all_rows, args.topk, source_label, len(queries))
    print("\n" + report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
