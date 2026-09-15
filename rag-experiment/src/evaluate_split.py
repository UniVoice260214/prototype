"""전공 RAG(major_ai) vs 강의 RAG(lecture_kim_i2a) 독립 모델 비교.

실행: python src/evaluate_split.py [--queries eval/queries_positive.json ...]
                                   [--topk 5] [--output eval/results_split.md]

- major_ai 인덱스: definition/comparison/principle 질의로 평가
- lecture_kim_i2a 인덱스: lecture 질의로 평가
- 각 인덱스에 없는 doc_type의 정답 chunk는 라벨에서 제외하고 평가
  (정답이 전부 제외되는 질의는 건너뛰고 리포트에 기록)
- 목적: 두 RAG에 같은 모델을 쓸지 다른 모델을 쓸지 데이터로 결정
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import EVAL_DIR, INDEX_SUBSETS, MODELS
from embed import load_chunks
from evaluate import RECALL_KS, evaluate_model, load_queries, metrics_of

# 평가 대상 인덱스와 그 인덱스에 물어볼 질의 유형.
# 여기에 없는 인덱스(예: 평가셋이 아직 없는 전공)는 평가에서 조용히 제외된다.
INDEX_QUERY_TYPES: dict[str, list[str]] = {
    "major_ai": ["definition", "comparison", "principle", "paraphrase", "stt_noise"],
    "lecture_kim_i2a": ["lecture", "paraphrase", "stt_noise"],
}


def prepare_queries(
    queries: list[dict[str, Any]],
    index_name: str,
    chunk_doc_types: dict[str, str],
) -> tuple[list[dict[str, Any]], list[tuple[str, list[str]]], list[str]]:
    """인덱스에 맞는 질의만 골라 정답을 인덱스 내 chunk로 제한.

    반환: (질의 목록, 일부 정답 제외된 질의 노트, 전부 제외되어 건너뛴 질의)
    """
    allowed_types = set(INDEX_SUBSETS[index_name])
    subset: list[dict[str, Any]] = []
    filtered_notes: list[tuple[str, list[str]]] = []
    dropped: list[str] = []
    for q in queries:
        if q.get("query_type") not in INDEX_QUERY_TYPES[index_name]:
            continue
        kept = [
            cid for cid in q["answer_chunk_ids"]
            if chunk_doc_types.get(cid) in allowed_types
        ]
        if not kept:
            dropped.append(q["query"])
            continue
        lost = [cid for cid in q["answer_chunk_ids"] if cid not in kept]
        if lost:
            filtered_notes.append((q["query"], lost))
        subset.append({**q, "answer_chunk_ids": kept})
    return subset, filtered_notes, dropped


def rank_models(
    metrics: dict[str, dict[str, float]]
) -> list[tuple[str, dict[str, float]]]:
    """R@1 내림차순, 동률이면 MRR로 정렬."""
    return sorted(
        metrics.items(), key=lambda kv: (kv[1]["recall@1"], kv[1]["mrr"]), reverse=True
    )


def build_report(
    results: dict[str, dict[str, dict[str, float]]],
    notes: dict[str, list[tuple[str, list[str]]]],
    dropped: dict[str, list[str]],
    n_queries: dict[str, int],
    topk: int,
    source_label: str,
) -> str:
    lines = [
        "# 전공 RAG vs 강의 RAG — 임베딩 모델 독립 비교",
        "",
        f"- 질의 파일: {source_label} / top-k = {topk}",
        "- major_ai(전공): glossary + concept_doc / definition·comparison·principle 질의",
        "- lecture_kim_i2a(강의): lecture_slide / lecture 질의",
        "- 인덱스 밖 doc_type의 정답 chunk는 라벨에서 제외하고 평가",
        "",
        "## 인덱스 × 모델 지표",
        "",
        "| 인덱스 | 모델 | R@1 | R@3 | MRR | n |",
        "|--------|------|----:|----:|----:|---:|",
    ]
    for index_name, model_metrics in results.items():
        for model_key, m in model_metrics.items():
            lines.append(
                f"| {index_name} | {model_key} | {m['recall@1']:.3f} "
                f"| {m['recall@3']:.3f} | {m['mrr']:.3f} | {int(m['n'])} |"
            )

    # 인덱스별 1등과 격차
    winners: dict[str, str] = {}
    lines += ["", "## 인덱스별 1등 모델", ""]
    for index_name, model_metrics in results.items():
        ranked = rank_models(model_metrics)
        first_key, first = ranked[0]
        winners[index_name] = first_key
        if len(ranked) > 1:
            second_key, second = ranked[1]
            gap_r1 = (first["recall@1"] - second["recall@1"]) * 100
            gap_mrr = (first["mrr"] - second["mrr"]) * 100
            tie_note = " (R@1 동률 → MRR로 판정)" if gap_r1 == 0 else ""
            lines.append(
                f"- **{index_name}: {first_key}** — 2등 {second_key} 대비 "
                f"R@1 +{gap_r1:.1f}%p, MRR +{gap_mrr:.1f}%p{tie_note}"
            )
        else:
            lines.append(f"- **{index_name}: {first_key}** (비교 대상 없음)")

    # 판단 보조
    lines += ["", "## 판단 보조", ""]
    if len(winners) == 2:
        major_winner = winners.get("major_ai")
        lecture_winner = winners.get("lecture_kim_i2a")
        if major_winner == lecture_winner:
            lines.append(
                f"- 두 인덱스의 1등 모델이 **같음 ({major_winner})** → "
                "단일 모델로 두 RAG를 모두 구성해도 데이터상 손해 없음."
            )
        else:
            lecture_metrics = results["lecture_kim_i2a"]
            r1_lecture_winner = lecture_metrics[lecture_winner]["recall@1"]
            r1_major_winner = lecture_metrics[major_winner]["recall@1"]
            gap_pp = (r1_lecture_winner - r1_major_winner) * 100
            n_lecture = n_queries["lecture_kim_i2a"]
            n_diff = round(gap_pp / 100 * n_lecture, 1)
            lines += [
                f"- 두 인덱스의 1등 모델이 **다름**: "
                f"전공={major_winner}, 강의={lecture_winner}",
                f"- 강의 인덱스에서 {lecture_winner}가 전공 1등({major_winner})보다 "
                f"R@1 **+{gap_pp:.1f}%p** 높음",
                f"- lecture 질의 {n_lecture}개 기준 이 격차는 "
                f"**질의 {n_diff}개 차이** — 표본이 작으니 해석에 주의",
            ]

    # 라벨 조정 내역
    lines += ["", "## 라벨 조정 내역 (인덱스 밖 정답 제외)", ""]
    for index_name in results:
        note_list = notes.get(index_name, [])
        drop_list = dropped.get(index_name, [])
        if not note_list and not drop_list:
            lines.append(f"- {index_name}: 조정 없음")
            continue
        for query, lost in note_list:
            lines.append(f"- {index_name} | 일부 제외: {query} → {', '.join(lost)}")
        for query in drop_list:
            lines.append(f"- {index_name} | **질의 건너뜀** (정답 전부 인덱스 밖): {query}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="전공/강의 RAG 분리 모델 비교")
    parser.add_argument(
        "--queries", type=Path, nargs="+",
        default=[EVAL_DIR / "queries_positive.json"],
        help="평가 질의 JSON (복수 지정 시 병합)",
    )
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument(
        "--output", type=Path, default=EVAL_DIR / "results_split.md",
    )
    args = parser.parse_args()

    queries: list[dict[str, Any]] = []
    for queries_path in args.queries:
        if not queries_path.exists():
            sys.exit(f"질의 파일 없음: {queries_path}")
        queries.extend(load_queries(queries_path))
    source_label = ", ".join(f"`{p.name}`" for p in args.queries)

    chunk_doc_types = {c["chunk_id"]: c["doc_type"] for c in load_chunks()}

    results: dict[str, dict[str, dict[str, float]]] = {}
    notes: dict[str, list[tuple[str, list[str]]]] = {}
    dropped: dict[str, list[str]] = {}
    n_queries: dict[str, int] = {}
    for index_name in INDEX_QUERY_TYPES:
        subset, note_list, drop_list = prepare_queries(
            queries, index_name, chunk_doc_types
        )
        notes[index_name], dropped[index_name] = note_list, drop_list
        n_queries[index_name] = len(subset)
        print(f"[{index_name}] 질의 {len(subset)}개 "
              f"(일부 정답 제외 {len(note_list)} / 건너뜀 {len(drop_list)})")
        model_metrics: dict[str, dict[str, float]] = {}
        for model_key in MODELS:
            rows = evaluate_model(model_key, subset, args.topk, index_name=index_name)
            if rows is None:
                continue
            model_metrics[model_key] = metrics_of(rows, args.topk)
        if model_metrics:
            results[index_name] = model_metrics

    report = build_report(
        results, notes, dropped, n_queries, args.topk, source_label
    )
    print("\n" + report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
