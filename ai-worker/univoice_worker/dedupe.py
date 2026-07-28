"""Dedupe stores for per-segment/locale TTS work."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol


class DedupeStore(Protocol):
    async def try_acquire(self, key: str) -> bool:
        """Atomically mark a key as processing if it is currently available."""

    async def mark_done(self, key: str) -> None:
        """Persist successful completion for the configured done TTL."""

    async def mark_failed(self, key: str) -> None:
        """Release or briefly mark a failed key so retry policy can apply."""

    async def is_done(self, key: str) -> bool:
        """Return True when a key has already completed successfully."""


@dataclass
class _Entry:
    state: str
    expires_at: float


class InMemoryDedupeStore:
    """Process-local dedupe store used by tests and single-worker deployments."""

    def __init__(self, ttl_sec: int = 3600, failed_ttl_sec: int = 30) -> None:
        self._ttl_sec = ttl_sec
        self._failed_ttl_sec = failed_ttl_sec
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def try_acquire(self, key: str) -> bool:
        async with self._lock:
            self._purge_expired_locked()
            entry = self._entries.get(key)
            if entry is not None:
                return False
            self._entries[key] = _Entry("processing", time.monotonic() + self._ttl_sec)
            return True

    async def mark_done(self, key: str) -> None:
        async with self._lock:
            self._entries[key] = _Entry("done", time.monotonic() + self._ttl_sec)

    async def mark_failed(self, key: str) -> None:
        async with self._lock:
            if self._failed_ttl_sec <= 0:
                self._entries.pop(key, None)
                return
            self._entries[key] = _Entry("failed", time.monotonic() + self._failed_ttl_sec)

    async def is_done(self, key: str) -> bool:
        async with self._lock:
            self._purge_expired_locked()
            entry = self._entries.get(key)
            return entry is not None and entry.state == "done"

    def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)


class RedisDedupeStore:
    """Redis SET NX/EX implementation for cross-worker TTS dedupe."""

    def __init__(
        self,
        redis_client: object,
        *,
        ttl_sec: int = 3600,
        failed_ttl_sec: int = 30,
        prefix: str = "univoice:tts-dedupe:",
    ) -> None:
        self._redis = redis_client
        self._ttl_sec = ttl_sec
        self._failed_ttl_sec = failed_ttl_sec
        self._prefix = prefix

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        ttl_sec: int = 3600,
        failed_ttl_sec: int = 30,
        prefix: str = "univoice:tts-dedupe:",
    ) -> "RedisDedupeStore":
        try:
            from redis import asyncio as redis_asyncio
        except ImportError as exc:  # pragma: no cover - dependency is runtime-provided
            raise RuntimeError("redis package is required for RedisDedupeStore") from exc
        return cls(
            redis_asyncio.from_url(redis_url, decode_responses=True),
            ttl_sec=ttl_sec,
            failed_ttl_sec=failed_ttl_sec,
            prefix=prefix,
        )

    async def try_acquire(self, key: str) -> bool:
        result = await self._redis.set(
            self._key(key),
            "processing",
            ex=self._ttl_sec,
            nx=True,
        )
        return bool(result)

    async def mark_done(self, key: str) -> None:
        await self._redis.set(self._key(key), "done", ex=self._ttl_sec)

    async def mark_failed(self, key: str) -> None:
        redis_key = self._key(key)
        if self._failed_ttl_sec <= 0:
            await self._redis.delete(redis_key)
            return
        await self._redis.set(redis_key, "failed", ex=self._failed_ttl_sec)

    async def is_done(self, key: str) -> bool:
        return await self._redis.get(self._key(key)) == "done"

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"


def tts_dedupe_key(session_id: str, segment_id: str, locale: str) -> str:
    return f"{session_id}:{segment_id}:{locale}"
