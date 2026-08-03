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
