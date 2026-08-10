"""강의자료 자동 인덱싱 데몬.

NestJS 가 자료 업로드 시 적재하는 Redis 큐(rag:index:queue)를 소비해
과목별 lecture 인덱스(lecture_{courseId})에 **누적** 인덱싱한다.
major 인덱스(ai/hss/bme)는 손대지 않는다 — 고정 자산이다.

흐름:
  BRPOPLPUSH rag:index:queue → rag:index:processing   (크래시 내구성)
  → materials.indexing.completed {status: processing} 발행
  → blob 다운로드 (PDF 만; PPT 는 안내와 함께 failed)
  → 범용 청킹 (WeekN 슬라이드 규칙 → 실패 시 문서형 규칙)
  → 신규 청크만 KURE 임베딩 → 기존 인덱스에 add → tmp 파일에 쓰고 os.replace
  → data/chunks/lecture_{courseId}.jsonl 에 append
  → {status: done} 발행 + rag-service /admin/reload 호출

실행:
  python src/indexer_daemon.py          # REDIS_URL 필수
환경변수:
  REDIS_URL              (필수) 예: redis://localhost:6379
  RAG_INDEX_QUEUE        기본 rag:index:queue  (NestJS redis-keys.ts 와 계약)
  RAG_SERVICE_URL        설정 시 인덱싱 성공 후 POST {url}/admin/reload 호출
  RAG_MODEL              기본 kure
  BLOB_URL_REWRITE       "공개base=>내부base" — Docker 내부에서 공개 URL 이
                         닿지 않을 때 치환 (예: https://demo.example.com=>http://azurite:10000)
                         운영(Azure Blob)에서는 SAS 토큰이 달린 URL 을 그대로 쓰거나
                         계정 키 기반 다운로드로 교체해야 한다.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from config import CHUNKS_PATH, INDEXES_DIR
from ingest import Chunk, ingest_concept_pdf, ingest_lecture_pdf, _slug

QUEUE_KEY = os.environ.get("RAG_INDEX_QUEUE", "rag:index:queue")
PROCESSING_KEY = f"{QUEUE_KEY}:processing"
COMPLETED_CHANNEL = "materials.indexing.completed"
MODEL_KEY = os.environ.get("RAG_MODEL", "kure")
COURSE_CHUNKS_DIR = CHUNKS_PATH.parent

_running = True


def _log(message: str) -> None:
    print(f"[indexer] {message}", flush=True)


def course_index_name(course_id: str) -> str:
    return f"lecture_{course_id}"


def course_chunks_path(course_id: str) -> Path:
    return COURSE_CHUNKS_DIR / f"{course_index_name(course_id)}.jsonl"


def rewrite_blob_url(blob_url: str) -> str:
    rule = os.environ.get("BLOB_URL_REWRITE", "").strip()
    if not rule or "=>" not in rule:
        return blob_url
    public_base, internal_base = (part.strip() for part in rule.split("=>", 1))
    if public_base and blob_url.startswith(public_base):
        return internal_base + blob_url[len(public_base):]
    return blob_url


def download_blob(blob_url: str) -> bytes:
    import httpx

    url = rewrite_blob_url(blob_url)
    response = httpx.get(url, timeout=60, follow_redirects=True)
    response.raise_for_status()
    return response.content


def chunk_pdf(pdf_bytes: bytes, *, course_id: str, material_id: str, original_filename: str, week: int | None) -> list[Chunk]:
    """업로드된 임의 PDF 를 청킹한다.

    파일명별 하드코딩 파서(ingest.py 의 데모 코퍼스 경로)와 달리, 처음 보는
    PDF 에도 동작해야 하므로 distractor 코퍼스와 같은 휴리스틱을 쓴다:
    'WeekN' 슬라이드 마커가 있으면 슬라이드 규칙, 없으면 문서형 규칙.
    """
    prefix = f"{course_index_name(course_id)}_{_slug(material_id)}"
    doc_type = f"uploaded_{course_index_name(course_id)}"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(pdf_bytes)
        tmp_path = Path(handle.name)
    try:
        chunks = ingest_lecture_pdf(tmp_path, doc_type=doc_type, id_prefix=prefix)
        if not chunks:  # Week 마커 없음 → 문서형 규칙
            chunks = ingest_concept_pdf(tmp_path, doc_type=doc_type, id_prefix=prefix)
    finally:
        tmp_path.unlink(missing_ok=True)

    for chunk in chunks:
        chunk.metadata.setdefault("materialId", material_id)
        chunk.metadata.setdefault("originalFilename", original_filename)
        if week is not None:
            chunk.metadata.setdefault("week", week)
        # source 는 검색 근거 표기에 그대로 노출된다 — 임시파일명 대신 원본 파일명.
        chunk.source = original_filename
    return chunks


def load_existing_chunk_ids(course_id: str) -> set[str]:
    path = course_chunks_path(course_id)
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                ids.add(json.loads(line)["chunk_id"])
    return ids


def append_course_chunks(course_id: str, chunks: list[Chunk]) -> None:
    from dataclasses import asdict

    path = course_chunks_path(course_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")


def add_to_course_index(course_id: str, chunks: list[Chunk], embedder: Any) -> int:
    """기존 lecture_{courseId} 인덱스에 신규 청크를 누적한다.

    IndexFlatIP 는 학습이 필요 없어 read → add → write 가 안전하다.
    전체 재빌드(자료가 쌓일수록 수 분)를 피하고 신규 청크만 임베딩한다.
    쓰기는 tmp 파일 + os.replace 로 원자적으로 — rag-service 가 읽는 도중
    반쯤 쓰인 파일을 보지 않게 한다.
    """
    import faiss

    index_dir = INDEXES_DIR / course_index_name(course_id) / MODEL_KEY
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / "faiss.index"
    ids_path = index_dir / "chunk_ids.json"

    vectors = np.asarray(embedder.encode([chunk.text for chunk in chunks]), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms

    if index_path.exists() and ids_path.exists():
        index = faiss.read_index(str(index_path))
        chunk_ids: list[str] = json.loads(ids_path.read_text(encoding="utf-8"))
    else:
        index = faiss.IndexFlatIP(vectors.shape[1])
        chunk_ids = []

    index.add(vectors)
    chunk_ids.extend(chunk.chunk_id for chunk in chunks)

    tmp_index = index_dir / "faiss.index.tmp"
    tmp_ids = index_dir / "chunk_ids.json.tmp"
    faiss.write_index(index, str(tmp_index))
    tmp_ids.write_text(json.dumps(chunk_ids, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_index, index_path)
    os.replace(tmp_ids, ids_path)
    return index.ntotal


def publish_status(redis_client: Any, material_id: str, status: str, error: str | None = None) -> None:
    payload: dict[str, Any] = {"materialId": material_id, "status": status}
    if error:
        payload["error"] = error
    redis_client.publish(COMPLETED_CHANNEL, json.dumps(payload, ensure_ascii=False))


def notify_rag_service(course_id: str) -> None:
    base = os.environ.get("RAG_SERVICE_URL", "").strip()
    if not base:
        return
    try:
        import httpx

        httpx.post(
            f"{base.rstrip('/')}/admin/reload",
            json={"courseId": course_id},
            timeout=30,
        ).raise_for_status()
        _log(f"rag-service reload 완료: {course_index_name(course_id)}")
    except Exception as exc:  # noqa: BLE001 - 리로드 실패가 인덱싱 성공을 뒤집지 않는다.
        _log(f"⚠️ rag-service reload 실패 (다음 재시작 때 lazy load 됨): {exc}")


def is_pdf(job: dict[str, Any]) -> bool:
    mimetype = str(job.get("mimetype") or "").lower()
    filename = str(job.get("originalFilename") or "").lower()
    if mimetype == "application/pdf":
        return True
    if not mimetype and filename.endswith(".pdf"):
        return True
    # blobUrl 확장자 폴백 (구버전 payload 에 filename/mimetype 이 없을 때)
    return not mimetype and not filename and str(job.get("blobUrl", "")).lower().endswith(".pdf")


def handle_job(redis_client: Any, embedder: Any, raw: str) -> None:
    try:
        job = json.loads(raw)
    except json.JSONDecodeError:
        _log(f"⚠️ 파싱 불가 잡 폐기: {raw[:200]!r}")
        return

    material_id = str(job.get("materialId") or "")
    course_id = str(job.get("courseId") or "")
    blob_url = str(job.get("blobUrl") or "")
    if not material_id or not course_id or not blob_url:
        _log(f"⚠️ 필수 필드 누락 잡 폐기: {job}")
        return

    publish_status(redis_client, material_id, "processing")
    _log(f"인덱싱 시작: material={material_id} course={course_id}")

    try:
        if not is_pdf(job):
            raise ValueError("PPT는 아직 인덱싱 미지원 — PDF로 변환 후 업로드하세요")

        pdf_bytes = download_blob(blob_url)
        chunks = chunk_pdf(
            pdf_bytes,
            course_id=course_id,
            material_id=material_id,
            original_filename=str(job.get("originalFilename") or f"{material_id}.pdf"),
            week=job.get("week"),
        )
        if not chunks:
            raise ValueError("PDF에서 인덱싱할 텍스트를 추출하지 못했습니다 (스캔 이미지 PDF?)")

        # 같은 자료 재처리(재시도/중복 큐) 시 이미 넣은 청크는 건너뛴다.
        existing = load_existing_chunk_ids(course_id)
        fresh = [chunk for chunk in chunks if chunk.chunk_id not in existing]
        if fresh:
            total = add_to_course_index(course_id, fresh, embedder)
            append_course_chunks(course_id, fresh)
            _log(
                f"인덱싱 완료: material={material_id} 신규 {len(fresh)}청크 "
                f"(인덱스 총 {total}벡터)"
            )
        else:
            _log(f"이미 인덱싱된 자료: material={material_id} — 스킵")

        publish_status(redis_client, material_id, "done")
        notify_rag_service(course_id)
    except Exception as exc:  # noqa: BLE001 - 한 자료의 실패가 데몬을 죽이면 안 된다.
        _log(f"❌ 인덱싱 실패: material={material_id}: {exc}")
        publish_status(redis_client, material_id, "failed", error=str(exc)[:500])


def recover_processing(redis_client: Any) -> None:
    """이전 크래시로 processing 리스트에 남은 잡을 큐로 되돌린다."""
    moved = 0
    while True:
        raw = redis_client.rpoplpush(PROCESSING_KEY, QUEUE_KEY)
        if raw is None:
            break
        moved += 1
    if moved:
        _log(f"미완료 잡 {moved}건을 큐로 복구")


def main() -> int:
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        _log("REDIS_URL 이 필요합니다")
        return 2

    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(redis_url, decode_responses=True)

    def _stop(*_args: Any) -> None:
        global _running
        _running = False
        _log("종료 신호 수신 — 현재 잡을 마치고 종료합니다")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):  # pragma: no cover - 플랫폼별 제약
            pass

    _log(f"임베딩 모델 로드 중 ({MODEL_KEY}) — 20~30초 걸릴 수 있습니다")
    from embed import get_embedder

    embedder = get_embedder(MODEL_KEY)
    recover_processing(redis_client)
    _log(f"대기 시작: 큐={QUEUE_KEY}")

    while _running:
        try:
            raw = redis_client.brpoplpush(QUEUE_KEY, PROCESSING_KEY, timeout=5)
        except redis_lib.RedisError as exc:
            _log(f"⚠️ Redis 오류 — 5초 후 재시도: {exc}")
            time.sleep(5)
            continue
        if raw is None:
            continue
        try:
            handle_job(redis_client, embedder, raw)
        finally:
            # 성공/실패 모두 completed 이벤트로 보고했으므로 processing 에서 제거.
            redis_client.lrem(PROCESSING_KEY, 1, raw)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
