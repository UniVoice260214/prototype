"""UniVoice 데모 RAG HTTP 서비스."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from runtime import RagRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("univoice_rag")


class RetrieveRequest(BaseModel):
    sentence: str = Field(min_length=1, max_length=2000)
    glossaryHits: list[str] = Field(default_factory=list)
    major: str = "auto"
    courseId: str = ""


class ReloadRequest(BaseModel):
    """indexer_daemon 이 인덱스 갱신 직후 호출한다."""

    courseId: str = Field(min_length=1, max_length=64)


@asynccontextmanager
async def lifespan(app: FastAPI):
    model = os.getenv("RAG_MODEL", "kure")
    top_k = int(os.getenv("RAG_TOP_K", "3"))
    context_max_chars = int(os.getenv("RAG_CONTEXT_MAX_CHARS", "4000"))
    logger.info("RAG runtime loading model=%s topK=%d", model, top_k)
    app.state.runtime = await asyncio.to_thread(
        RagRuntime.load,
        model,
        top_k=top_k,
        context_max_chars=context_max_chars,
    )
    logger.info("RAG runtime ready majors=%s", sorted(app.state.runtime.routers))
    yield


app = FastAPI(title="UniVoice Demo RAG", version="1.0", lifespan=lifespan)


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/reload")
async def admin_reload(payload: ReloadRequest, request: Request) -> dict[str, object]:
    """과목별 lecture 인덱스를 디스크에서 다시 읽는다.

    자료 업로드→인덱싱 완료 시 indexer_daemon 이 호출하며, 서비스 재시작 없이
    새 자료가 즉시 검색에 반영된다. (미로드 과목은 /retrieve 가 lazy load 도 한다.)
    """
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="RAG runtime is loading")
    name = await asyncio.to_thread(runtime.reload_course_index, payload.courseId)
    logger.info("admin reload course=%s -> %s", payload.courseId, name or "not-found")
    return {"reloaded": bool(name), "index": name}


@app.get("/health/ready")
def health_ready(request: Request) -> dict[str, object]:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="RAG runtime is loading")
    return {
        "status": "ok",
        "model": runtime.model_key,
        "majors": sorted(runtime.routers),
        "indexes": sorted(runtime.indexes),
    }


@app.post("/retrieve")
async def retrieve(payload: RetrieveRequest, request: Request) -> dict[str, object]:
    runtime: RagRuntime | None = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="RAG runtime is loading")
    try:
        result = await asyncio.to_thread(
            runtime.retrieve,
            payload.sentence,
            major=payload.major,
            glossary_hits=payload.glossaryHits,
            course_id=payload.courseId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "RAG %s course=%s major=%s query=%r matched=%s score=%s latencyMs=%s",
        "ON" if result["useRag"] else "OFF",
        payload.courseId,
        result["major"],
        result["query"],
        result["matchedTerms"],
        result["topScore"],
        result["latencyMs"],
    )
    return result
