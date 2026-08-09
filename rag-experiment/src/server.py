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


@asynccontextmanager
async def lifespan(app: FastAPI):
    model = os.getenv("RAG_MODEL", "kure")
    top_k = int(os.getenv("RAG_TOP_K", "3"))
    context_max_chars = int(os.getenv("RAG_CONTEXT_MAX_CHARS", "4000"))
    course_index_map_raw = os.getenv("RAG_COURSE_INDEX_MAP", "")
    logger.info("RAG runtime loading model=%s topK=%d", model, top_k)
    # RAG_COURSE_INDEX_MAP이 잘못돼 있으면 여기서 예외가 그대로 전파돼 기동이 실패한다
    # (오검색이 프로덕션에 새어나가지 않도록 무음 폴백 대신 fail-fast).
    app.state.runtime = await asyncio.to_thread(
        RagRuntime.load,
        model,
        top_k=top_k,
        context_max_chars=context_max_chars,
        course_index_map_raw=course_index_map_raw,
    )
    logger.info(
        "RAG runtime ready majors=%s courses=%s",
        sorted(app.state.runtime.routers),
        sorted(app.state.runtime.course_index_map),
    )
    yield


app = FastAPI(title="UniVoice Demo RAG", version="1.0", lifespan=lifespan)


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


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
        "courses": sorted(runtime.course_index_map),
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
        "RAG %s course=%s major=%s query=%r matched=%s score=%s indexes=%s latencyMs=%s",
        "ON" if result["useRag"] else "OFF",
        payload.courseId,
        result["major"],
        result["query"],
        result["matchedTerms"],
        result["topScore"],
        result["indexes"],
        result["latencyMs"],
    )
    return result
