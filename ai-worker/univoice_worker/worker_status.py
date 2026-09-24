"""Shared worker status Redis contract."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Literal, Protocol

logger = logging.getLogger(__name__)

WorkerStatusValue = Literal["starting", "ready", "stopping", "stopped", "failed"]


def worker_status_key(session_id: str) -> str:
    return f"session:{session_id}:worker:status"


@dataclass(frozen=True)
class WorkerStatus:
    status: WorkerStatusValue
    ts: float
    error: str | None = None
    # 교수 화면이 그대로 읽는 진단 정보.
    # 예: {"glossary": 0, "lexicon": "ai", "phraseList": 334, "rag": "off"}
    diagnostics: dict[str, object] | None = None

    def to_json(self) -> str:
        payload: dict[str, object] = {"status": self.status, "ts": self.ts}
        if self.error:
            payload["error"] = self.error
        if self.diagnostics:
            payload["diagnostics"] = self.diagnostics
        return json.dumps(payload, ensure_ascii=False)


class WorkerStatusStore(Protocol):
    async def set_status(
        self,
        session_id: str,
        status: WorkerStatusValue,
        *,
        error: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        """Persist worker status for a session."""


class NoOpWorkerStatusStore:
    async def set_status(
        self,
        session_id: str,
        status: WorkerStatusValue,
        *,
        error: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        return None


class RedisWorkerStatusStore:
    def __init__(self, redis_client: object, *, ttl_sec: int = 3600) -> None:
        self._redis = redis_client
        self._ttl_sec = ttl_sec

    async def set_status(
        self,
        session_id: str,
        status: WorkerStatusValue,
        *,
        error: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        payload = WorkerStatus(
            status=status, ts=time.time(), error=error, diagnostics=diagnostics
        ).to_json()
        await self._redis.set(worker_status_key(session_id), payload, ex=self._ttl_sec)
