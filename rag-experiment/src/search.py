"""수동 확인용 검색 도구.

실행: python src/search.py --model kure --query "탐색 문제의 구성요소는?" [--topk 5]
질의 임베딩은 인덱스를 만든 모델과 동일한 모델로 수행된다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import INDEX_SUBSETS, INDEXES_DIR, MODELS
from embed import get_embedder, load_chunks


def load_index(
    model_key: str, index_name: str | None = None
) -> tuple[Any, list[str]]:
    index_dir = (
        INDEXES_DIR / index_name / model_key if index_name else INDEXES_DIR / model_key
    )
    index_path = index_dir / "faiss.index"
    ids_path = index_dir / "chunk_ids.json"
    if not index_path.exists() or not ids_path.exists():
        index_opt = f" --index {index_name}" if index_name else ""
        raise FileNotFoundError(
            f"{index_dir} 에 인덱스 없음 — 먼저 "
            f"python src/embed.py --model {model_key}{index_opt} 실행"
        )
    # 존재 확인 뒤에 import 한다 — "인덱스 없음" 판정(동적 lecture_{courseId} 폴백)에
    # faiss 설치가 필요하지 않도록.
    import faiss

    index = faiss.read_index(str(index_path))
    chunk_ids = json.loads(ids_path.read_text(encoding="utf-8"))
    return index, chunk_ids


def search(
    model_key: str, query: str, topk: int, index_name: str | None = None
) -> list[tuple[str, float]]:
    index, chunk_ids = load_index(model_key, index_name)
    embedder = get_embedder(model_key)  # 인덱스와 같은 모델로 질의 임베딩
    vector = embedder.encode([query]).astype(np.float32)
    scores, indices = index.search(vector, topk)
    return [
        (chunk_ids[idx], float(score))
        for idx, score in zip(indices[0], scores[0])
        if idx != -1
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="top-k chunk 수동 확인")
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument("--query", required=True)
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument(
        "--index", choices=sorted(INDEX_SUBSETS), default=None,
        help="분리 인덱스 이름 (생략 시 통합 인덱스)",
    )
    args = parser.parse_args()

    chunk_by_id = {c["chunk_id"]: c for c in load_chunks()}
    results = search(args.model, args.query, args.topk, args.index)

    index_label = args.index or "통합"
    print(f"\n질의: {args.query}  (model={args.model}, index={index_label}, topk={args.topk})")
    print("=" * 70)
    for rank, (chunk_id, score) in enumerate(results, start=1):
        chunk = chunk_by_id.get(chunk_id, {})
        preview = chunk.get("text", "")[:200].replace("\n", " ")
        print(f"[{rank}] {score:.4f}  {chunk_id}  ({chunk.get('doc_type', '?')})")
        print(f"     {preview}")
        print("-" * 70)


if __name__ == "__main__":
    main()
