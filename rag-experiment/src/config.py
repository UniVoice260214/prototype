"""실험 공통 설정 — 경로, 비교 모델 3개, Azure OpenAI 환경변수."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_RAW_DIR = ROOT / "data" / "raw"
# 전공별 원본 자료 디렉터리 (raw/ 아래 전공 단위로 분리)
DATA_RAW_AI_DIR = DATA_RAW_DIR / "ai"
DATA_RAW_HSS_DIR = DATA_RAW_DIR / "Humanities_Social_Sciences"
DATA_RAW_BME_DIR = DATA_RAW_DIR / "Biomedical_Bioengineering"
DATA_RAW_DISTRACTOR_DIR = ROOT / "data" / "raw_distractor"
CHUNKS_PATH = ROOT / "data" / "chunks" / "chunks.jsonl"
INDEXES_DIR = ROOT / "indexes"
EVAL_DIR = ROOT / "eval"
RESULTS_PATH = EVAL_DIR / "results.md"


@dataclass(frozen=True)
class ModelSpec:
    key: str        # CLI에서 쓰는 이름 (indexes/{key}/ 폴더명)
    kind: str       # "sentence_transformers" | "azure_openai"
    model_name: str


# 비교 대상 임베딩 모델 3개
MODELS: dict[str, ModelSpec] = {
    "kure": ModelSpec(
        key="kure",
        kind="sentence_transformers",
        model_name="nlpai-lab/KURE-v1",
    ),
    "bge-m3": ModelSpec(  # dense 벡터만 사용
        key="bge-m3",
        kind="sentence_transformers",
        model_name="BAAI/bge-m3",
    ),
    "openai": ModelSpec(
        key="openai",
        kind="azure_openai",
        model_name="text-embedding-3-large",
    ),
}

# 분리 인덱스: doc_type 부분집합 → indexes/{index_name}/{model}/
# 전공 RAG는 전공마다 doc_type을 분리해 서로 섞이지 않게 한다.
INDEX_SUBSETS: dict[str, list[str]] = {
    "major_ai": ["glossary", "concept_doc", "textbook"],  # 전공 RAG: 용어사전 + 개념문서 + 입문교재
    "major_humanities_social_sciences": [                 # 전공 RAG: 인문사회 개념문서 + 입문교재
        "hss_concept_doc",
        "hss_textbook",
    ],
    "major_biomedical_bioengineering": [                  # 전공 RAG: 바이오의생명공학 입문교재
        "bme_concept_doc",
        "bme_textbook",
    ],
    "lecture_kim_i2a": ["lecture_slide"],     # 강의 RAG: 김교수 I2A 슬라이드
    # 강의 RAG는 과목 단위다. 같은 전공이라도 과목이 다르면 인덱스를 나눈다
    # (인문사회에 국어학개론·종교사회학 두 과목이 있다).
    "lecture_heo_korling": ["korling_lecture_slide"],   # 허용 · 국어학개론
    "lecture_nam_relsoc": ["relsoc_lecture_slide"],     # 남은경 · 종교사회학
    "lecture_lee_molbio": ["molbio_lecture_slide"],     # 이우일 · 분자생물학
}

# Azure OpenAI (.env에서 로드)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")


def torch_device() -> str:
    """로컬 모델용 디바이스 — CUDA 가능하면 자동 사용, 아니면 CPU."""
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
