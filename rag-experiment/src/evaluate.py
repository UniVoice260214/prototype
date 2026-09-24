"""세 모델 전체에 대해 Recall@{1,3,5}, MRR, Full-Recall@5 평가 + top-1 점수 분석.

실행: python src/evaluate.py [--queries eval/queries.json] [--topk 5]
                             [--output eval/results.md]
                             [--major ai|hss|bme] [--no-relaxed]

- positive 질의: answer_chunk_ids 중 하나라도 top-k에 있으면 hit (엄격 지표)
- 완화 지표: 정답 chunk와 같은 (source, chapter)에 속한 textbook/concept_doc
  chunk 전체를 정답으로 인정 (예: 정답이 ch06_s1이면 ch06_terms/ch06_summary도
  인정). glossary는 이미 용어 단위로 원자적이라 대상에서 제외.
  → '틀린 chunk를 줬다'와 '같은 장의 다른 chunk를 줬다'를 구분해서 보기 위함.
  --no-relaxed 로 끌 수 있다.
- --major 지정 시 RagRouter.normalize()(음차 치환 + 필러 제거)를 질의에
  적용한 뒤 임베딩한다 — 실제 파이프라인이 STT 문장을 정규화한 뒤 검색하는
  것과 동일한 조건으로 재현. lexicon 매칭에 따른 extra_terms 병기는 적용하지
  않는다(그건 results_router.md가 별도로 측정하는 트리거 단계의 효과다).
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
from embed import get_embedder, load_chunks
from router import MAJOR_ROUTERS, RagRouter
from search import load_index

RECALL_KS = (1, 3, 5)
THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(9)]  # 0.30 ~ 0.70

# 형제(완화) 관계를 인정하는 doc_type — 장/절 구조가 있는 것만.
# glossary는 용어 하나당 chunk 하나로 이미 원자적이라 대상에서 제외.
# doc_type은 전공마다 접두어가 달라진다 (textbook/concept_doc, hss_textbook/
# hss_concept_doc, bme_textbook — ingest.py 상단 표 참조) 이므로 접미사로 매칭한다.
_CHAPTER_DOC_SUFFIXES = ("textbook", "concept_doc")


def _is_chapter_doc_type(doc_type: str) -> bool:
    return doc_type.endswith(_CHAPTER_DOC_SUFFIXES)


def load_queries(path: Path) -> list[dict[str, Any]]:
    queries = json.loads(path.read_text(encoding="utf-8"))
    for q in queries:
        assert q.get("query") and isinstance(q.get("answer_chunk_ids"), list), (
            f"형식 오류: {q}"
        )
    return queries


def build_chapter_siblings(chunks: list[dict[str, Any]]) -> dict[str, set[str]]:
    """chunk_id → 같은 (source, chapter)를 공유하는 형제 chunk_id 집합(자기 포함).

    textbook/concept_doc만 대상. 절 본문(_s{N})은 이미 절과 1:1이라 묶어도
    바뀌는 게 없고, _terms/_summary/_intro 처럼 장 전체를 커버하는 chunk를
    같은 장의 본문과 묶어주는 것이 이 함수의 실질적인 효과다.
    """
    groups: dict[tuple[str, str], set[str]] = {}
    for c in chunks:
        if not _is_chapter_doc_type(c.get("doc_type", "")):
            continue
        chapter = (c.get("metadata") or {}).get("chapter")
        if not chapter:
            continue
        key = (c["source"], chapter)
        groups.setdefault(key, set()).add(c["chunk_id"])

    siblings: dict[str, set[str]] = {}
    for chunk_ids in groups.values():
        for cid in chunk_ids:
            siblings[cid] = chunk_ids
    return siblings


# ── 모델별 검색 실행 ──────────────────────────────────────────────────


def evaluate_model(
    model_key: str,
    queries: list[dict[str, Any]],
    topk: int,
    index_names: list[str | None] | None = None,
    chapter_siblings: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]] | None:
    """질의별 순위/점수 기록. 인덱스 없거나 오류 시 None.

    index_names에 여러 인덱스를 주면 각각 검색한 뒤 chunk_id 기준으로 병합한다
    (같은 chunk는 최고 점수 채택, 점수 내림차순 정렬 후 top-k).
    runtime.RagRuntime._search 가 한 전공의 여러 인덱스를 병합하는 방식과 동일
    — 프로덕션은 전공 인덱스와 강의 인덱스를 함께 검색하므로, 정답이 두 인덱스에
    걸친 질의를 재현하려면 평가도 같은 방식이어야 한다.
    """
    index_names = index_names or [None]
    loaded: list[tuple[Any, list[str]]] = []
    for name in index_names:
        try:
            loaded.append(load_index(model_key, name))
        except FileNotFoundError:
            label = f" --index {name}" if name else ""
            print(
                f"⚠️  [{model_key}] 인덱스 없음 — 건너뜀 "
                f"(python src/embed.py --model {model_key}{label})"
            )
            return None

    try:
        embedder = get_embedder(model_key)  # 질의도 인덱스와 같은 모델로 임베딩
        embed_texts = [q.get("_embed_text", q["query"]) for q in queries]
        vectors = embedder.encode(embed_texts).astype(np.float32)
        # 인덱스별 검색 결과를 질의 단위로 모은다: per_query[i] = {chunk_id: score}
        per_query: list[dict[str, float]] = [{} for _ in queries]
        for index, chunk_ids in loaded:
            scores, indices = index.search(vectors, topk)
            for slot, (idx_row, score_row) in enumerate(zip(indices, scores)):
                for position, score in zip(idx_row, score_row):
                    if position == -1:
                        continue
                    cid = chunk_ids[int(position)]
                    prev = per_query[slot].get(cid)
                    if prev is None or float(score) > prev:
                        per_query[slot][cid] = float(score)
    except Exception as exc:
        # 한 모델의 API/네트워크 오류가 전체 평가를 죽이지 않도록 격리
        print(f"⚠️  [{model_key}] 평가 실패 — 건너뜀: {type(exc).__name__}: {exc}")
        return None

    chapter_siblings = chapter_siblings or {}
    rows: list[dict[str, Any]] = []
    for q, hits in zip(queries, per_query):
        ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)[:topk]
        retrieved = [cid for cid, _ in ranked]
        top1 = ranked[0][1] if ranked else 0.0
        answers = set(q["answer_chunk_ids"])
        answer_ranks = [
            rank for rank, cid in enumerate(retrieved, start=1) if cid in answers
        ]
        # 완화 정답 = 정답 chunk + 같은 장(chapter)의 형제 chunk 전체
        relaxed_answers: set[str] = set()
        for cid in answers:
            relaxed_answers |= chapter_siblings.get(cid, {cid})
        relaxed_ranks = [
            rank for rank, cid in enumerate(retrieved, start=1) if cid in relaxed_answers
        ]
        rows.append(
            {
                "query": q["query"],
                "embed_text": q.get("_embed_text", q["query"]),
                "query_type": q.get("query_type", "unknown"),
                "is_negative": not answers,
                "first_rank": answer_ranks[0] if answer_ranks else None,
                "found": len(answer_ranks),
                "n_answers": len(answers),
                "first_rank_relaxed": relaxed_ranks[0] if relaxed_ranks else None,
                "found_relaxed": len(relaxed_ranks),
                "n_answers_relaxed": len(relaxed_answers),
                "top1_score": top1,
                "retrieved": retrieved,
            }
        )
    return rows


# ── 집계 ──────────────────────────────────────────────────────────────


def metrics_of(
    rows: list[dict[str, Any]], topk: int, variant: str = ""
) -> dict[str, float]:
    """positive 질의 그룹의 Recall@k / MRR / Full-Recall@topk.

    variant="" 는 엄격 기준(first_rank/found/n_answers),
    variant="_relaxed" 는 같은 장 형제 chunk까지 인정하는 완화 기준.
    """
    rank_key, found_key, n_key = (
        f"first_rank{variant}",
        f"found{variant}",
        f"n_answers{variant}",
    )
    n = len(rows)
    result: dict[str, float] = {"n": n}
    for k in RECALL_KS:
        result[f"recall@{k}"] = (
            sum(1 for r in rows if r[rank_key] and r[rank_key] <= k) / n
        )
    result["mrr"] = sum(1 / r[rank_key] for r in rows if r[rank_key]) / n
    result[f"full_recall@{topk}"] = (
        sum(1 for r in rows if r[found_key] == r[n_key]) / n
    )
    return result


def aggregate(
    rows: list[dict[str, Any]], topk: int, variant: str = ""
) -> dict[str, dict[str, float]]:
    """{'전체' + query_type: metrics} — negative는 제외."""
    positives = [r for r in rows if not r["is_negative"]]
    groups: dict[str, list[dict[str, Any]]] = {"전체": positives}
    for row in positives:
        groups.setdefault(row["query_type"], []).append(row)
    return {
        name: metrics_of(items, topk, variant)
        for name, items in groups.items()
        if items
    }


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
    *,
    relaxed: bool = True,
    major: str | None = None,
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
    ]
    if major:
        lines.append(
            f"- 라우터 정규화 적용: major={major} (RagRouter.normalize — 음차 치환 + 필러 제거)"
        )
    if relaxed:
        lines.append(
            "- 완화 지표: 정답 chunk와 같은 장(chapter)에 속한 textbook/concept_doc "
            "chunk 전체를 정답으로 인정 (glossary 제외)"
        )
    lines += [
        "",
        "## 전체 평균 (positive 질의만, 엄격 기준)",
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

    if relaxed:
        lines += [
            "",
            "## 전체 평균 (positive 질의만, 완화 기준 — 같은 장 형제 chunk 허용)",
            "",
            "Full-Recall@k는 표기하지 않는다 — 완화 정답 집합(같은 장 chunk 전체)이 "
            "보통 top-k보다 커서 '전부 포함'이 정의상 거의 항상 불가능하다. "
            "완화 기준에서는 R@k(하나라도 맞으면 hit)만 의미가 있다.",
            "",
            "| 모델 | R@1 | R@3 | R@5 | MRR | n |",
            "|------|----:|----:|----:|----:|---:|",
        ]
        aggs_relaxed = {
            key: aggregate(rows, topk, variant="_relaxed")
            for key, rows in all_rows.items()
        }
        for model_key, agg in aggs_relaxed.items():
            m = agg["전체"]
            lines.append(
                f"| {model_key} | {m['recall@1']:.3f} | {m['recall@3']:.3f} "
                f"| {m['recall@5']:.3f} | {m['mrr']:.3f} | {int(m['n'])} |"
            )

    lines += ["", "## query_type별 분리 집계 (엄격 기준)", ""]
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

    # R@5 미검색 질의 (검수용) — 완화 기준에서 회수되는지 함께 표시
    lines += ["", "## R@5 미검색 질의 (모델별)", ""]
    if relaxed:
        lines.append(
            "'완화 회수' = 엄격 기준으로는 놓쳤지만 같은 장의 형제 chunk는 "
            "top-k에 있음 (틀린 chunk가 아니라 같은 장의 다른 chunk를 준 경우).\n"
        )
    for model_key, rows in all_rows.items():
        missed = [r for r in rows if not r["is_negative"] and not r["first_rank"]]
        if not missed:
            lines.append(f"- **{model_key}**: 없음")
            continue
        still_missed = [r for r in missed if relaxed and not r["first_rank_relaxed"]]
        recovered = [r for r in missed if relaxed and r["first_rank_relaxed"]]
        if relaxed:
            lines.append(
                f"- **{model_key}**: {len(missed)}개 "
                f"(완화 회수 {len(recovered)}개 / 진짜 실패 {len(still_missed)}개)"
            )
        else:
            lines.append(f"- **{model_key}**: {len(missed)}개")
        for row in missed:
            tag = ""
            if relaxed:
                tag = " [완화 회수]" if row["first_rank_relaxed"] else " [진짜 실패]"
            lines.append(
                f"  - ({row['query_type']}) {row['query']}{tag} "
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
        "--index", choices=sorted(INDEX_SUBSETS), default=None, nargs="+",
        help="분리 인덱스 이름 (생략 시 통합 인덱스). 여러 개 지정하면 각각 검색 후 "
             "chunk_id 기준 병합 — 프로덕션이 전공+강의 인덱스를 함께 보는 것과 동일. "
             "예: --index major_ai lecture_kim_i2a",
    )
    parser.add_argument(
        "--output", type=Path, default=RESULTS_PATH,
        help="결과 마크다운 경로 (기본: eval/results.md)",
    )
    parser.add_argument(
        "--major", choices=sorted(MAJOR_ROUTERS), default=None,
        help="지정 시 RagRouter.normalize()를 질의에 적용한 뒤 임베딩 "
             "(실제 STT→검색 경로와 동일 조건으로 재현)",
    )
    parser.add_argument(
        "--no-relaxed", action="store_true",
        help="같은 장 형제 chunk 완화 지표 계산을 끄고 엄격 기준만 리포트",
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

    if args.major:
        router = RagRouter(args.major)
        n_changed = 0
        for q in queries:
            normalized = router.normalize(q["query"])
            q["_embed_text"] = normalized
            if normalized != q["query"]:
                n_changed += 1
        print(f"[normalize] major={args.major} 적용 — {n_changed}/{len(queries)}개 질의 변경됨")

    relaxed = not args.no_relaxed
    chapter_siblings = build_chapter_siblings(load_chunks()) if relaxed else {}

    index_names: list[str | None] = list(args.index) if args.index else [None]

    all_rows: dict[str, list[dict[str, Any]]] = {}
    for model_key in MODELS:
        rows = evaluate_model(
            model_key, queries, args.topk,
            index_names=index_names, chapter_siblings=chapter_siblings,
        )
        if rows is not None:
            all_rows[model_key] = rows

    if args.index:
        joined = ", ".join(f"`{n}`" for n in args.index)
        source_label = f"{source_label} (index: {joined})"
    report = build_report(
        all_rows, args.topk, source_label, len(queries),
        relaxed=relaxed, major=args.major,
    )
    print("\n" + report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
