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
import signal
from typing import Any, Awaitable, Callable

try:  # pragma: no cover - Redis is runtime-provided; tests use fakes.
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

from pathlib import Path

from .config import WorkerConfig, load_config
from .glossary import GlossaryEntry, parse_glossary
from .lexicon import LexiconRegistry, MajorLexicon
from .rag import HttpRagClient, NoOpRagClient, RagClient
from .session_worker import TRANSCRIPTS_SEGMENT_CHANNEL, SessionWorker
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
    try:
        raw = await redis.get(f"glossary:{course_id}")
    except Exception:  # noqa: BLE001 - Redis 순단으로 세션 기동을 통째로 죽이면 안 된다.
        logger.exception("glossary:%s 조회 실패 — 용어집 없이 시작", course_id)
        return []
    if not raw:
        logger.warning("glossary:%s 없음 — 용어집 없이 시작", course_id)
        return []
    try:
        return parse_glossary(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        logger.exception("glossary:%s 파싱 실패", course_id)
        return []


async def load_sequence_start(redis: aioredis.Redis, session_id: str) -> int:
    """워커 재기동 시 이전 런의 마지막 sequence 다음부터 이어간다.

    이게 없으면 재기동 런이 1부터 다시 세어, 세션 자막 조회(sequence ASC)에서
    두 런의 세그먼트가 뒤섞인다.
    """
    try:
        raw = await redis.get(f"session:{session_id}:lastSequence")
    except Exception:  # noqa: BLE001 - 보조 정보라 실패해도 세션은 떠야 한다.
        logger.exception("[%s] lastSequence 조회 실패 — 1부터 시작", session_id)
        return 1
    try:
        return int(raw) + 1 if raw else 1
    except (TypeError, ValueError):
        return 1


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
        logger.warning("[%s] unsupported locales skipped: %s", session_id, unknown)
    locales = [locale for locale in locales if locale in config.voice_map]
    if not locales:
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


def resolve_major(config: WorkerConfig, course_id: str) -> str:
    """과목 → 전공 키. RAG 클라이언트와 STT lexicon 이 같은 규칙을 쓴다."""
    return config.rag_course_major_map.get(course_id, config.rag_default_major)


def build_rag_client(config: WorkerConfig, course_id: str) -> RagClient:
    """세션 과목에 맞는 데모 RAG 클라이언트를 만든다."""
    if not config.rag_enabled:
        return NoOpRagClient()
    major = resolve_major(config, course_id)
    logger.info("RAG client configured: course=%s major=%s url=%s", course_id, major, config.rag_url)
    return HttpRagClient(
        config.rag_url,
        major=major,
        course_id=course_id,
        timeout_sec=config.rag_timeout_sec,
    )


async def preflight_rag(config: WorkerConfig) -> str:
    """RAG 서비스 상태를 확인해 로그로 드러내고 진단값을 돌려준다.

    반환: "ready" | "off" | "unreachable" | "no-index".
    기동 시 1회, 그리고 세션 시작마다 다시 호출한다 — 반환값은 세션 워커의
    diagnostics 로 실려 교수 화면 상태줄에 표시된다.
    RAG 는 실패해도 fail-open 이라 자막만 보고는 동작 여부를 알 수 없다.
    """
    if not config.rag_enabled:
        logger.warning(
            "RAG 비활성 (RAG_ENABLED=false) — 강의자료 문맥 없이 번역한다. "
            "인덱스를 빌드했다면 RAG_ENABLED=true 로 켜라."
        )
        return "off"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=config.rag_timeout_sec) as client:
            response = await client.get(f"{config.rag_url.rstrip('/')}/health/ready")
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 프리플라이트 실패가 워커를 막지는 않는다.
        logger.error(
            "RAG 프리플라이트 실패 (%s): %s — 문맥 없이 진행한다", config.rag_url, exc
        )
        return "unreachable"

    indexes = payload.get("indexes") or []
    logger.info(
        "RAG 준비 완료: model=%s majors=%s indexes=%s",
        payload.get("model"),
        payload.get("majors"),
        indexes,
    )
    if not indexes:
        logger.error("RAG 서비스에 인덱스가 하나도 없다 — 사실상 문맥 주입이 안 된다.")
        return "no-index"
    return "ready"


def load_lexicons(config: WorkerConfig) -> LexiconRegistry:
    """rag_assets/lexicon_*.json 로드. STT 전공 용어 교정의 자산이다."""
    base = Path(config.rag_assets_dir)
    if not base.is_absolute():
        # 워커 패키지 상위(ai-worker/)를 기준으로 잡아 cwd 에 덜 의존하게 한다.
        candidate = Path(__file__).resolve().parent.parent / base
        base = candidate if candidate.is_dir() else base
    return LexiconRegistry.load_dir(base)


class WorkerRegistry:
    def __init__(
        self,
        redis: aioredis.Redis,
        config: WorkerConfig,
        lexicons: LexiconRegistry | None = None,
        rag_status: str = "off",
    ) -> None:
        self._redis = redis
        self._config = config
        self._lexicons = lexicons if lexicons is not None else LexiconRegistry({})
        self._rag_status = rag_status
        self._status_store = RedisWorkerStatusStore(redis, ttl_sec=config.worker_status_ttl_sec)
        self._workers: dict[str, tuple[SessionWorker, asyncio.Task[None]]] = {}
        # 백그라운드로 분리한 end_session 태스크 (GC 방지 + stop_all 에서 대기).
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _lexicon_for(self, session_id: str, course_id: str) -> MajorLexicon | None:
        major = resolve_major(self._config, course_id)
        if major == "auto":
            # 전공 union 은 위험하다 — bme 의 '피디' → 'PD' 가 AI 강의에서 발동하면
            # 자막이 오히려 망가진다. 전공을 특정할 수 없으면 교정을 끈다.
            logger.warning(
                "[%s] RAG_DEFAULT_MAJOR=auto — STT lexicon 교정 비활성. "
                "과목별 전공을 RAG_COURSE_MAJOR_MAP 에 지정하라 (course=%s)",
                session_id,
                course_id,
            )
            return None
        lexicon = self._lexicons.get(major)
        if lexicon is None:
            logger.error(
                "[%s] 전공 '%s' lexicon 자산 없음 (보유: %s) — 전공 용어 교정 비활성",
                session_id,
                major,
                self._lexicons.majors,
            )
        return lexicon

    async def start_session(self, event: dict[str, Any]) -> None:
        validated = validate_started_payload(event, self._config)
        if validated is None:
            logger.warning("sessions.started payload invalid: %r", event)
            return
        session_id = validated["sessionId"]
        if session_id in self._workers:
            logger.warning("[%s] 이미 실행 중인 세션, 무시", session_id)
            return
        try:
            await self._start_session_inner(session_id, validated)
        except Exception as exc:  # noqa: BLE001
            # 예전에는 여기서 난 예외가 조용히 삼켜져 워커 상태 키조차 안 써졌고,
            # 교수 화면은 "AI 워커 응답 대기"로 영원히 머물렀다. 실패를 기록해야
            # 화면 폴링(GET /sessions/:id/status)이 원인을 보여줄 수 있다.
            logger.exception("[%s] 세션 워커 기동 실패", session_id)
            try:
                await self._status_store.set_status(session_id, "failed", error=str(exc))
            except Exception:  # noqa: BLE001 - 상태 기록 실패까지는 어쩔 수 없다.
                logger.exception("[%s] 기동 실패 상태 기록도 실패", session_id)

    async def _start_session_inner(self, session_id: str, validated: dict[str, Any]) -> None:
        course_id = validated["courseId"]
        glossary = await load_glossary(self._redis, course_id)
        lexicon = self._lexicon_for(session_id, course_id)
        rag = build_rag_client(self._config, course_id)
        # 세션마다 다시 확인한다 — 워커 기동 뒤에 rag-service 를 띄우거나 인덱스를 빌드해도
        # 진단값이 따라오게. 꺼져 있으면 호출하지 않는다(기동 시 이미 경고했다).
        rag_status = await preflight_rag(self._config) if self._config.rag_enabled else "off"
        self._rag_status = rag_status
        sequence_start = await load_sequence_start(self._redis, session_id)
        if sequence_start > 1:
            logger.info(
                "[%s] 이전 런의 자막 이어가기 — sequence %d 부터", session_id, sequence_start
            )
        worker = SessionWorker(
            config=self._config,
            session_id=session_id,
            room_name=validated["liveKitRoomName"],
            target_locales=validated["targetLocales"],
            glossary=glossary,
            lexicon=lexicon,
            status_store=self._status_store,
            transcript_publisher=self._publish_transcript,
            sequence_start=sequence_start,
            rag=rag,
            rag_status=rag_status,
        )

        task = asyncio.create_task(worker.run(), name=f"session-{session_id}")
        task.add_done_callback(lambda t, sid=session_id: self._on_worker_done(sid, t))
        self._workers[session_id] = (worker, task)
        # 한 줄로 진단이 끝나야 한다: glossary 0개 / lexicon 없음 / RAG 미동작을 즉시 본다.
        logger.info(
            "[%s] 세션 워커 시작 locales=%s | glossary=%d | lexicon=%s | RAG=%s",
            session_id,
            validated["targetLocales"],
            len(glossary),
            f"{lexicon.major}({len(lexicon.lexicon)}패턴)" if lexicon else "NONE",
            rag_status,
        )
        if not glossary and lexicon is None:
            logger.error(
                "[%s] glossary 도 lexicon 도 없다 — 전공 용어 인식·번역 보정이 전혀 걸리지 않는다.",
                session_id,
            )

    async def _publish_transcript(self, payload: dict[str, Any]) -> None:
        """자막 세그먼트를 Redis Pub/Sub 으로 발행한다. NestJS 가 구독해 DB 저장."""
        # Redis 가 느려질 때 publish 가 hang 하면 (예외가 아니라 대기라서)
        # 파이프라인의 except 가 잡지 못하고 세그먼트 컨슈머가 통째로 멈춘다.
        await asyncio.wait_for(
            self._redis.publish(
                TRANSCRIPTS_SEGMENT_CHANNEL, json.dumps(payload, ensure_ascii=False)
            ),
            timeout=2,
        )
        session_id = payload.get("sessionId")
        sequence = payload.get("sequence")
        if session_id and isinstance(sequence, int):
            # 워커 재기동 시 이어갈 마지막 sequence (load_sequence_start 가 읽음).
            try:
                await asyncio.wait_for(
                    self._redis.set(
                        f"session:{session_id}:lastSequence", sequence, ex=86400
                    ),
                    timeout=2,
                )
            except Exception:  # noqa: BLE001 - 보조 정보라 발행 실패로 승격하지 않는다.
                logger.warning("[%s] lastSequence 기록 실패", session_id)

    async def end_session(self, event: dict[str, Any]) -> None:
        validated = validate_ended_payload(event)
        if validated is None:
            logger.warning("sessions.ended payload invalid: %r", event)
            return
        session_id = validated["sessionId"]
        entry = self._workers.get(session_id)
        if entry is None:
            return
        worker, task = entry
        try:
            # 종료가 hang 해도 여기서 끊는다. 이 대기가 무제한이면 (직렬이든
            # 태스크 분리든) 워커 태스크와 registry 엔트리가 영구히 남는다.
            await asyncio.wait_for(
                self._stop_worker(worker, task),
                timeout=self._config.session_stop_timeout_sec,
            )
        except asyncio.TimeoutError:
            logger.error(
                "[%s] 세션 종료가 %.0f초 내 끝나지 않아 강제 취소한다",
                session_id,
                self._config.session_stop_timeout_sec,
            )
            task.cancel()
            try:
                await self._status_store.set_status(
                    session_id, "failed", error="session stop timeout"
                )
            except Exception:  # noqa: BLE001
                logger.exception("[%s] 강제 종료 상태 기록 실패", session_id)
        current = self._workers.get(session_id)
        if current is not None and current[1] is task:
            self._workers.pop(session_id, None)

    @staticmethod
    async def _stop_worker(worker: SessionWorker, task: asyncio.Task[None]) -> None:
        await worker.stop()
        await asyncio.gather(task, return_exceptions=True)

    def spawn_end_session(self, event: dict[str, Any]) -> None:
        """sessions.ended 를 백그라운드로 처리한다.

        pubsub 루프에서 직접 await 하면 종료가 오래 걸리는 동안 다음 수업의
        sessions.started 가 블로킹된다 — "수업을 다시 시작하면 활성화가 안 된다"
        는 증상의 절반이 이 직렬성이었다.
        """
        task = asyncio.create_task(self.end_session(event), name="end-session")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def stop_all(self) -> None:
        if self._background_tasks:
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
        entries = list(self._workers.values())
        for worker, _task in entries:
            try:
                await asyncio.wait_for(
                    worker.stop(), timeout=self._config.session_stop_timeout_sec
                )
            except asyncio.TimeoutError:
                logger.error("세션 워커 정지가 제한 시간을 초과해 건너뛴다")
            except Exception:  # noqa: BLE001
                logger.exception("세션 워커 정지 실패")
        pending = [task for _worker, task in entries if not task.done()]
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=self._config.session_stop_timeout_sec,
                )
            except asyncio.TimeoutError:
                for task in pending:
                    task.cancel()
        self._workers.clear()

    def _on_worker_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        current = self._workers.get(session_id)
        if current is not None and current[1] is task:
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
        # 종료 처리는 백그라운드로 — 직렬로 await 하면 종료가 끝날 때까지
        # 다음 수업의 sessions.started 가 처리되지 않는다.
        registry.spawn_end_session(event)


async def main() -> None:
    if aioredis is None:
        raise RuntimeError("redis package is required for the AI worker")
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()

    def request_shutdown() -> None:
        if main_task is not None and not main_task.done():
            main_task.cancel()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, request_shutdown)
        except NotImplementedError:  # pragma: no cover - Windows local runtime.
            pass

    config = load_config()
    lexicons = load_lexicons(config)
    rag_status = await preflight_rag(config)

    redis = aioredis.from_url(config.redis_url, decode_responses=True)
    registry = WorkerRegistry(redis, config, lexicons, rag_status=rag_status)
    pubsub: Any = None
    reconnect_delay = 1.0

    try:
        # Redis 순단으로 listen() 이터레이션이 예외를 던지면 예전에는 프로세스가
        # 통째로 죽었다(잡는 건 CancelledError 뿐이었다). 재구독 루프로 감싼다.
        while True:
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe(CHANNEL_SESSIONS_STARTED, CHANNEL_SESSIONS_ENDED)
                logger.info(
                    "Redis 구독 시작: %s, %s", CHANNEL_SESSIONS_STARTED, CHANNEL_SESSIONS_ENDED
                )
                # 구독 공백(부팅 직후 또는 재연결) 동안 발행된 sessions.started 는
                # Pub/Sub 특성상 유실된다. active 세션 스캔으로 보상한다 —
                # 이미 실행 중인 세션은 _workers 가드가 무시하므로 멱등하다.
                await recover_active_sessions(redis, config, registry.start_session)
                reconnect_delay = 1.0
                async for message in pubsub.listen():
                    try:
                        await handle_pubsub_message(message, registry)
                    except Exception:  # noqa: BLE001
                        logger.exception("Pub/Sub message handling failed: %r", message)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Pub/Sub 연결이 끊겼다 — %.0f초 후 재구독한다", reconnect_delay
                )
                try:
                    if pubsub is not None:
                        await pubsub.aclose()
                except Exception:  # noqa: BLE001
                    pass
                pubsub = None
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30.0)
    except asyncio.CancelledError:
        logger.info("shutdown signal received")
    finally:
        await registry.stop_all()
        if pubsub is not None:
            await pubsub.aclose()
        await redis.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("종료")