"""기존 제공 PDF로 데모용 전공/강의 FAISS 인덱스를 생성한다."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from config import CHUNKS_PATH, INDEXES_DIR, INDEX_SUBSETS
from embed import _normalize, get_embedder, load_chunks

MODEL = "kure"
INDEX_NAMES = tuple(INDEX_SUBSETS)


def index_ready(index_name: str) -> bool:
    directory = INDEXES_DIR / index_name / MODEL
    return (directory / "faiss.index").exists() and (directory / "chunk_ids.json").exists()


def run_ingest() -> None:
    subprocess.run([sys.executable, str(Path(__file__).with_name("ingest.py"))], check=True)


def build_index(index_name: str, chunks: list[dict[str, Any]], embedder: Any) -> None:
    import faiss

    allowed = set(INDEX_SUBSETS[index_name])
    selected = [chunk for chunk in chunks if chunk["doc_type"] in allowed]
    if not selected:
        raise RuntimeError(f"{index_name}: no chunks for {sorted(allowed)}")

    started = time.monotonic()
    vectors = _normalize(embedder.encode([chunk["text"] for chunk in selected]))
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(np.asarray(vectors, dtype=np.float32))

    directory = INDEXES_DIR / index_name / MODEL
    directory.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(directory / "faiss.index"))
    (directory / "chunk_ids.json").write_text(
        json.dumps([chunk["chunk_id"] for chunk in selected], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[demo-index] {index_name}: {len(selected)} chunks "
        f"({time.monotonic() - started:.1f}s)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build all UniVoice demo RAG indexes")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.force or not CHUNKS_PATH.exists():
        run_ingest()

    pending = [name for name in INDEX_NAMES if args.force or not index_ready(name)]
    if not pending:
        print("[demo-index] all indexes already exist; nothing to do")
        return

    chunks = load_chunks()
    embedder = get_embedder(MODEL)
    for index_name in pending:
        build_index(index_name, chunks, embedder)
    print(f"[demo-index] ready: {', '.join(INDEX_NAMES)}")


if __name__ == "__main__":
    main()
