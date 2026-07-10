"""실시간 관점 지연 벤치마크 — 모델별 콜드 스타트 / 질의 임베딩 / FAISS 검색.

실행: python src/benchmark.py [--limit N] [--output eval/results_latency.md]

- 질의 임베딩은 배치 1(단건)로 측정: 실시간 파이프라인은 세그먼트가 하나씩 들어옴
- 워밍업 3회 후 본 측정, 첫 호출(웜업 전) 시간은 별도 기록
- 통합 인덱스(전체 chunk) 기준 검색, 개별 측정 후 p50/p95/max 보고
- openai는 네트워크 왕복 포함이므로 로컬 모델과 성격이 다름에 유의
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import EVAL_DIR, MODELS, torch_device
from embed import get_embedder
from search import load_index

QUERY_FILES = [
    "queries_positive.json",
    "queries_hard.json",
    "queries_hard_newterms.json",
]
WARMUP_RUNS = 3


def load_benchmark_queries(limit: int | None) -> list[str]:
    texts: list[str] = []
    for fname in QUERY_FILES:
        path = EVAL_DIR / fname
        if not path.exists():
            print(f"⚠️  질의 파일 없음, 건너뜀: {path}")
            continue
        texts.extend(q["query"] for q in json.loads(path.read_text(encoding="utf-8")))
    if limit is not None:
        texts = texts[:limit]
    return texts


def percentile_stats(samples_ms: list[float]) -> dict[str, float]:
    arr = np.asarray(samples_ms)
    return {
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
    }


def bench_model(model_key: str, queries: list[str]) -> dict[str, Any] | None:
    """콜드 스타트 / 단건 임베딩 / 검색 지연 측정. 실패 시 None."""
    try:
        index, _ = load_index(model_key)
    except FileNotFoundError as exc:
        print(f"⚠️  [{model_key}] {exc}")
        return None

    # 콜드 스타트 (모델 로드)
    start = time.perf_counter()
    try:
        embedder = get_embedder(model_key)
    except Exception as exc:
        print(f"⚠️  [{model_key}] 로드 실패 — 건너뜀: {type(exc).__name__}: {exc}")
        return None
    cold_start_s = time.perf_counter() - start

    # 첫 호출 (웜업 전) + 워밍업
    first_call_start = time.perf_counter()
    embedder.encode([queries[0]])
    first_call_ms = (time.perf_counter() - first_call_start) * 1000
    for warm_query in queries[1 : 1 + WARMUP_RUNS]:
        embedder.encode([warm_query])

    # 본 측정: 질의별 단건 임베딩 + 검색
    embed_ms: list[float] = []
    search_ms: list[float] = []
    total_ms: list[float] = []
    failed = 0
    for query in queries:
        try:
            t0 = time.perf_counter()
            vector = embedder.encode([query]).astype(np.float32)
            t1 = time.perf_counter()
            index.search(vector, 5)
            t2 = time.perf_counter()
        except Exception as exc:
            failed += 1
            print(f"⚠️  [{model_key}] 질의 실패({type(exc).__name__}): {query[:30]}")
            continue
        embed_ms.append((t1 - t0) * 1000)
        search_ms.append((t2 - t1) * 1000)
        total_ms.append((t2 - t0) * 1000)

    if not embed_ms:
        return None
    return {
        "cold_start_s": cold_start_s,
        "first_call_ms": first_call_ms,
        "embed": percentile_stats(embed_ms),
        "search": percentile_stats(search_ms),
        "total": percentile_stats(total_ms),
        "n": len(embed_ms),
        "failed": failed,
    }


def environment_info() -> str:
    cpu = os.environ.get("PROCESSOR_IDENTIFIER", platform.processor() or "unknown")
    device = torch_device()
    return f"{platform.system()} {platform.release()} / {cpu} / device={device}"


def build_report(
    results: dict[str, dict[str, Any]], n_queries: int, env: str
) -> str:
    lines = [
        "# 실시간 지연 벤치마크",
        "",
        f"- 환경: {env}",
        f"- 질의 {n_queries}개, 배치 1(단건) 임베딩, 워밍업 {WARMUP_RUNS}회 후 측정",
        "- 검색: 통합 인덱스(전체 chunk), top-5, IndexFlatIP",
        "- openai는 Azure API 네트워크 왕복 포함 — 로컬 모델과 직접 비교 시 주의",
        "",
        "## 요약 (단위: ms)",
        "",
        "| 모델 | 콜드 스타트 | 첫 호출 | 임베딩 p50 | 임베딩 p95 | 임베딩 max "
        "| 검색 p50 | 검색 p95 | E2E p95 |",
        "|------|--------:|--------:|--------:|--------:|--------:|--------:|--------:|--------:|",
    ]
    for model_key, r in results.items():
        lines.append(
            f"| {model_key} | {r['cold_start_s']:.1f}s | {r['first_call_ms']:.0f} "
            f"| {r['embed']['p50']:.0f} | {r['embed']['p95']:.0f} "
            f"| {r['embed']['max']:.0f} "
            f"| {r['search']['p50']:.2f} | {r['search']['p95']:.2f} "
            f"| {r['total']['p95']:.0f} |"
        )
    lines += [
        "",
        "## 해석 가이드",
        "",
        "- **E2E p95**: 세그먼트당 RAG 검색이 번역 지연 예산에서 가져가는 몫 (임베딩+검색)",
        "- **콜드 스타트**: 워커 기동 시 1회 — 세션 시작 전 사전 로드 필요 여부 판단",
        "- 측정 실패 질의: "
        + ", ".join(f"{k}={r['failed']}" for k, r in results.items()),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="지연 벤치마크")
    parser.add_argument("--limit", type=int, default=None, help="질의 수 제한")
    parser.add_argument(
        "--output", type=Path, default=EVAL_DIR / "results_latency.md",
    )
    args = parser.parse_args()

    queries = load_benchmark_queries(args.limit)
    if not queries:
        sys.exit("측정할 질의 없음")
    print(f"질의 {len(queries)}개로 벤치마크 시작")

    results: dict[str, dict[str, Any]] = {}
    for model_key in MODELS:
        print(f"[bench] {model_key} 측정 중...")
        result = bench_model(model_key, queries)
        if result is not None:
            results[model_key] = result

    report = build_report(results, len(queries), environment_info())
    print("\n" + report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
