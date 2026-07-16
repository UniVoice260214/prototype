"""AI worker entrypoint.

Core API(NestJS)가 발행하는 Redis Pub/Sub 이벤트를 구독한다.

  sessions.started  { sessionId, courseId, liveKitRoomName, targetLocales }
  sessions.ended    { sessionId }
  glossary:{courseId}  prewarm된 용어 JSON 배열 (STT Phrase List로 사용)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

try:  # pragma: no cover - Redis is runtime-provided; tests use fakes.
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

from .config import WorkerConfig, load_config
from .glossary import GlossaryEntry, parse_glossary
from .session_worker import SessionWorker
from .worker_status import RedisWorkerStatusStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("univoice_worker")

CHANNEL_SESSIONS_STARTED = "sessions.started"
CHANNEL_SESSIONS_ENDED = "sessions.ended"
SESSION_STATUS_PATTERN = "session:*:status"


async def load_glossary(redis: aioredis.Redis, course_id: str) -> list[GlossaryEntry]:
    """Core API 가 prewarm 한 glossary:{courseId} (JSON 배열)을 읽어 파싱."""
    raw = await redis.get(f"glossary:{course_id}")
    if not raw:
        logger.warning("glossary:%s 없음 — 용어집 없이 시작", course_id)
        return []
    try:
        return parse_glossary(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        logger.exception("glossary:%s 파싱 실패", course_id)
        return []


def validate_started_payload(payload: Any, config: WorkerConfig) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("sessionId")
    course_id = payload.get("courseId")
    room_name = payload.get("liveKitRoomName") or payload.get("roomName")
    target_locales = payload.get("targetLocales") or payload.get("locales")
    if not all(isinstance(value, str) and value for value in (session_id, course_id, room_name)):
        return None
    if not isinstance(target_locales, list) or not target_locales:
        return None
    locales = [locale for locale in target_locales if isinstance(locale, str) and locale]
    if len(locales) != len(target_locales):
        return None
    unknown = [locale for locale in locales if locale not in config.voice_map]
    if unknown:
        logger.warning("[%s] 알 수 없는 locale: %s", session_id, unknown)
        return None
    return {
        "sessionId": session_id,
        "courseId": course_id,
        "liveKitRoomName": room_name,
        "targetLocales": locales,
    }


def validate_ended_payload(payload: Any) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return None
    return {"sessionId": session_id}


def _session_id_from_status_key(key: str) -> str | None:
    parts = key.split(":")
    if len(parts) != 3 or parts[0] != "session" or parts[2] != "status":
        return None
    return parts[1]


async def recover_active_sessions(
    redis: aioredis.Redis,
    config: WorkerConfig,
    start_session: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    async for status_key in redis.scan_iter(match=SESSION_STATUS_PATTERN, count=100):
        session_id = _session_id_from_status_key(str(status_key))
        if session_id is None:
            continue
        try:
            status = await redis.get(status_key)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] session status read failed", session_id)
            continue
        if status != "active":
            continue
        raw_config = await redis.get(f"session:{session_id}:config")
        if not raw_config:
            logger.warning("[%s] active session config missing; recovery skipped", session_id)
            continue
        try:
            session_config = json.loads(raw_config)
        except json.JSONDecodeError:
            logger.warning("[%s] active session config JSON invalid; recovery skipped", session_id)
            continue
        event = validate_started_payload(session_config, config)
        if event is None:
            logger.warning("[%s] active session config invalid; recovery skipped", session_id)
            continue
        await start_session(event)


class WorkerRegistry:
    def __init__(self, redis: aioredis.Redis, config: WorkerConfig) -> None:
        self._redis = redis
        self._config = config
        self._status_store = RedisWorkerStatusStore(redis, ttl_sec=config.worker_status_ttl_sec)
        self._workers: dict[str, tuple[SessionWorker, asyncio.Task[None]]] = {}

    async def start_session(self, event: dict[str, Any]) -> None:
        validated = validate_started_payload(event, self._config)
        if validated is None:
            logger.warning("sessions.started payload invalid: %r", event)
            return
        session_id = validated["sessionId"]
        if session_id in self._workers:
            logger.warning("[%s] 이미 실행 중인 세션, 무시", session_id)
            return
        glossary = await load_glossary(self._redis, validated["courseId"])
        worker = SessionWorker(
            config=self._config,
            session_id=session_id,
            room_name=validated["liveKitRoomName"],
            target_locales=validated["targetLocales"],
            glossary=glossary,
            status_store=self._status_store,
            # rag=AzureSearchRagClient(...),  # 실제 RAG 를 붙일 때 여기서 주입
        )

        task = asyncio.create_task(worker.run(), name=f"session-{session_id}")
        task.add_done_callback(lambda t, sid=session_id: self._on_worker_done(sid, t))
        self._workers[session_id] = (worker, task)
        logger.info(
            "[%s] 세션 워커 시작 (locales=%s, glossary %d개)",
            session_id,
            validated["targetLocales"],
            len(glossary),
        )

    async def end_session(self, event: dict[str, Any]) -> None:
        validated = validate_ended_payload(event)
        if validated is None:
            logger.warning("sessions.ended payload invalid: %r", event)
            return
        entry = self._workers.get(validated["sessionId"])
        if entry is None:
            return
        worker, _task = entry
        await worker.stop()

    async def stop_all(self) -> None:
        entries = list(self._workers.values())
        for worker, _task in entries:
            await worker.stop()
        await asyncio.gather(*(task for _worker, task in entries), return_exceptions=True)

def _on_worker_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        self._workers.pop(session_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error(
            "[%s] 세션 워커 비정상 종료",
            session_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        asyncio.create_task(
            self._status_store.set_status(session_id, "failed", error=str(exc))
        )


async def handle_pubsub_message(message: dict[str, Any], registry: WorkerRegistry) -> None:
    if message.get("type") != "message":
        return
    try:
        event = json.loads(message.get("data", ""))
    except json.JSONDecodeError:
        logger.warning("이벤트 payload 파싱 실패: %r", message.get("data"))
        return

    channel = message.get("channel")
    if channel == CHANNEL_SESSIONS_STARTED:
        await registry.start_session(event)
    elif channel == CHANNEL_SESSIONS_ENDED:
        await registry.end_session(event)


async def main() -> None:
    if aioredis is None:
        raise RuntimeError("redis package is required for the AI worker")
    config = load_config()
    redis = aioredis.from_url(config.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    registry = WorkerRegistry(redis, config)
    await pubsub.subscribe(CHANNEL_SESSIONS_STARTED, CHANNEL_SESSIONS_ENDED)
    logger.info("Redis 구독 시작: %s, %s", CHANNEL_SESSIONS_STARTED, CHANNEL_SESSIONS_ENDED)

    await recover_active_sessions(redis, config, registry.start_session)

    try:
        async for message in pubsub.listen():
            try:
                await handle_pubsub_message(message, registry)
            except Exception:  # noqa: BLE001
                logger.exception("Pub/Sub message handling failed: %r", message)
    finally:
        await registry.stop_all()
        await pubsub.aclose()
        await redis.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("종료")
