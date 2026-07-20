/**
 * Redis key and queue names shared with the Python AI worker and the RAG worker.
 * Keep the names centralized here so backend and worker changes stay in sync.
 */
export const RedisKeys = {
  /** Session config snapshot JSON: sessionId, courseId, roomName, locales, startedAt. */
  sessionConfig: (sessionId: string) => `session:${sessionId}:config`,
  /** Session status string: active | ending | ended. */
  sessionStatus: (sessionId: string) => `session:${sessionId}:status`,
  /** Python AI worker status JSON: { status, ts, error? }. */
  workerStatus: (sessionId: string) => `session:${sessionId}:worker:status`,
  /** Course glossary preload JSON written when a session starts. */
  glossaryByCourse: (courseId: string) => `glossary:${courseId}`,
} as const;

/**
 * Durable Redis list used for RAG indexing jobs.
 * Unlike Pub/Sub, items stay queued while the worker is offline.
 */
export const RAG_INDEX_QUEUE_DEFAULT = 'rag:index:queue';

/** 24-hour TTL for session config and glossary cache keys. */
export const SESSION_CONFIG_TTL_SEC = 60 * 60 * 24;
