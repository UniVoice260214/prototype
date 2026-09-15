"""chunks.jsonl 전체를 지정 모델로 임베딩해 FAISS 인덱스 생성.

실행: python src/embed.py --model {kure|bge-m3|openai}
산출: indexes/{model}/faiss.index, indexes/{model}/chunk_ids.json

질의 임베딩(search/evaluate)도 이 모듈의 Embedder를 통해 수행해
인덱스와 반드시 같은 모델을 쓰도록 강제한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    CHUNKS_PATH,
    INDEX_SUBSETS,
    INDEXES_DIR,
    MODELS,
    ModelSpec,
    torch_device,
)


def load_chunks() -> list[dict[str, Any]]:
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"{CHUNKS_PATH} 없음 — 먼저 python src/ingest.py 실행")
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformersEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        device = torch_device()
        print(f"[embed] {model_name} 로드 중 (device={device})...")
        self._model = SentenceTransformer(model_name, device=device)
        max_seq_length = int(os.getenv("RAG_MAX_SEQ_LENGTH", "0"))
        if max_seq_length > 0:
            self._model.max_seq_length = max_seq_length
            print(f"[embed] max_seq_length={max_seq_length}")

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 8,
        )
        return np.asarray(vectors, dtype=np.float32)


class AzureOpenAIEmbedder:
    BATCH_SIZE = 32
    MAX_RETRIES = 5

    def __init__(self, deployment_fallback: str) -> None:
        if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_API_KEY:
            raise RuntimeError(
                "Azure OpenAI 설정 없음 — .env에 AZURE_OPENAI_ENDPOINT, "
                "AZURE_OPENAI_API_KEY, AZURE_OPENAI_EMBEDDING_DEPLOYMENT 필요"
            )
        from openai import AzureOpenAI

        self._client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        self._deployment = AZURE_OPENAI_EMBEDDING_DEPLOYMENT or deployment_fallback

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            vectors.extend(self._embed_batch(batch))
            print(f"[embed] openai {min(i + self.BATCH_SIZE, len(texts))}/{len(texts)}")
        array = np.asarray(vectors, dtype=np.float32)
        return _normalize(array)

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        from openai import APIConnectionError, APIStatusError, APITimeoutError

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.embeddings.create(
                    model=self._deployment, input=batch
                )
                return [item.embedding for item in response.data]
            except (APIStatusError, APITimeoutError, APIConnectionError) as exc:
                status = getattr(exc, "status_code", None)
                retryable = status is None or status == 429 or status >= 500
                if not retryable or attempt == self.MAX_RETRIES - 1:
                    raise
                wait = 2**attempt
                print(f"[embed] API 오류(status={status}) — {wait}s 후 재시도")
                time.sleep(wait)
        raise RuntimeError("unreachable")


def _normalize(array: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return array / norms


def get_embedder(model_key: str) -> Embedder:
    spec: ModelSpec = MODELS[model_key]
    if spec.kind == "sentence_transformers":
        return SentenceTransformersEmbedder(spec.model_name)
    return AzureOpenAIEmbedder(spec.model_name)


def build_index(model_key: str, index_name: str | None = None) -> None:
    import faiss

    chunks = load_chunks()
    if index_name is not None:
        allowed = set(INDEX_SUBSETS[index_name])
        chunks = [c for c in chunks if c["doc_type"] in allowed]
        out_dir = INDEXES_DIR / index_name / model_key
    else:
        out_dir = INDEXES_DIR / model_key
    texts = [c["text"] for c in chunks]
    chunk_ids = [c["chunk_id"] for c in chunks]

    embedder = get_embedder(model_key)
    start = time.monotonic()
    vectors = _normalize(embedder.encode(texts))
    elapsed = time.monotonic() - start

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / "faiss.index"))
    (out_dir / "chunk_ids.json").write_text(
        json.dumps(chunk_ids, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[embed] 완료: {len(chunks)}개 chunk, dim={vectors.shape[1]}, "
        f"{elapsed:.1f}s → {out_dir}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="임베딩 + FAISS 인덱스 생성")
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument(
        "--index", choices=sorted(INDEX_SUBSETS), default=None,
        help="분리 인덱스 이름 (생략 시 전체 chunk로 통합 인덱스)",
    )
    args = parser.parse_args()
    build_index(args.model, args.index)


if __name__ == "__main__":
    main()
