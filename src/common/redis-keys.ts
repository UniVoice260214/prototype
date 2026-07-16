/**
 * Redis 키/큐 규약 — AI 워커(Python) · RAG 워커와 공유하는 인터페이스.
 * (서영 구현의 sessions.constants.ts 패턴을 통합본 표준으로 채택)
 *
 * 이름을 바꾸면 워커도 같이 바꿔야 하므로 한 곳에 모아둔다.
 * 채널(Pub/Sub) 규약은 modules/events/events.types.ts 의 EVENT_CHANNELS 참조.
 */
export const RedisKeys = {
  /** 세션 설정 스냅샷 (JSON): sessionId, courseId, roomName, locales, startedAt */
  sessionConfig: (sessionId: string) => `session:${sessionId}:config`,
  /** 세션 상태 문자열: 'active' | 'ending' | 'ended' (ending은 Redis 전용 진행 상태) */
  sessionStatus: (sessionId: string) => `session:${sessionId}:status`,
  /** Python AI Worker 상태 JSON: { status, ts, error? } */
  workerStatus: (sessionId: string) => `session:${sessionId}:worker:status`,
  /** 과목 glossary prewarm (JSON 배열) — 세션 시작 시 적재 */
  glossaryByCourse: (courseId: string) => `glossary:${courseId}`,
} as const;

/**
 * RAG 인덱싱 작업 큐 (Redis List).
 * Pub/Sub이 아니라 List로 두는 이유: 인덱싱 잡은 유실되면 안 되므로,
 * RAG 워커가 꺼져 있어도 큐에 쌓였다가 polling(BRPOP)으로 소비되도록 한다.
 * (서영 구현의 rag:index:queue 설계 채택)
 */
export const RAG_INDEX_QUEUE_DEFAULT = 'rag:index:queue';

/** 세션 설정/glossary 키 TTL (초) — 종료 이벤트 유실 대비 자동 정리 안전망. 24h */
export const SESSION_CONFIG_TTL_SEC = 60 * 60 * 24;
