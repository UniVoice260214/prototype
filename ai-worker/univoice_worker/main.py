"""AI 워커 엔트리포인트.

Core API(NestJS)가 발행하는 Redis Pub/Sub 이벤트를 구독한다.
채널/키 이름은 Core API의 src/common/redis-keys.ts, src/modules/events/events.types.ts 규약을 따른다.

  sessions.started  { sessionId, courseId, liveKitRoomName, targetLocales }
  sessions.ended    { sessionId }
  glossary:{courseId}  prewarm된 용어 JSON 배열 (STT Phrase List로 사용)
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from .config import load_config
from .glossary import GlossaryEntry, parse_glossary
from .session_worker import SessionWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("univoice_worker")

CHANNEL_SESSIONS_STARTED = "sessions.started"
CHANNEL_SESSIONS_ENDED = "sessions.ended"


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


async def main() -> None:
    config = load_config()
    redis = aioredis.from_url(config.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_SESSIONS_STARTED, CHANNEL_SESSIONS_ENDED)
    logger.info("Redis 구독 시작: %s, %s", CHANNEL_SESSIONS_STARTED, CHANNEL_SESSIONS_ENDED)

    workers: dict[str, tuple[SessionWorker, asyncio.Task]] = {}

    async def start_session(event: dict) -> None:
        session_id = event["sessionId"]
        if session_id in workers:
            logger.warning("[%s] 이미 실행 중인 세션, 무시", session_id)
            return
        glossary = await load_glossary(redis, event["courseId"])
        target_locales = event.get("targetLocales") or []
        if not target_locales:
            logger.error("[%s] targetLocales 비어 있음 — 세션 시작 건너뜀", session_id)
            return
        worker = SessionWorker(
            config=config,
            session_id=session_id,
            room_name=event["liveKitRoomName"],
            target_locales=target_locales,
            glossary=glossary,
            # rag=AzureSearchRagClient(...),  # ← 실제 RAG 를 붙일 때 여기서 주입
        )

        task = asyncio.create_task(worker.run(), name=f"session-{session_id}")

        def _done(t: asyncio.Task) -> None:
            workers.pop(session_id, None)
            if not t.cancelled() and t.exception():
                logger.error("[%s] 세션 워커 비정상 종료", session_id, exc_info=t.exception())

        task.add_done_callback(_done)
        workers[session_id] = (worker, task)
        logger.info(
            "[%s] 세션 워커 시작 (locales=%s, glossary %d개)",
            session_id, target_locales, len(glossary),
        )

    async def end_session(event: dict) -> None:
        entry = workers.get(event["sessionId"])
        if entry is None:
            return
        worker, _task = entry
        await worker.stop()

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                event = json.loads(message["data"])
            except json.JSONDecodeError:
                logger.warning("이벤트 payload 파싱 실패: %r", message["data"])
                continue

            if message["channel"] == CHANNEL_SESSIONS_STARTED:
                await start_session(event)
            elif message["channel"] == CHANNEL_SESSIONS_ENDED:
                await end_session(event)
    finally:
        for worker, task in list(workers.values()):
            await worker.stop()
            task.cancel()
        await pubsub.aclose()
        await redis.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("종료")
