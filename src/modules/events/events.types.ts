/**
 * Pub/Sub 채널 표준 — CLAUDE.md "Redis 키 / 채널 표준" 참조.
 * Python 워커 / RAG 워커가 이 채널을 구독한다.
 */
export const EVENT_CHANNELS = {
  SESSIONS_STARTED: 'sessions.started',
  SESSIONS_ENDED: 'sessions.ended',
  MATERIALS_INDEXING_REQUESTED: 'materials.indexing.requested',
  MATERIALS_INDEXING_COMPLETED: 'materials.indexing.completed',
} as const;

export type EventChannel = (typeof EVENT_CHANNELS)[keyof typeof EVENT_CHANNELS];

export interface SessionsStartedEvent {
  sessionId: string;
  courseId: string;
  liveKitRoomName: string;
  targetLocales: string[];
}

export interface SessionsEndedEvent {
  sessionId: string;
}

export interface MaterialsIndexingRequestedEvent {
  materialId: string;
  blobUrl: string;
  sourceType: 'lecture' | 'major';
  courseId: string;
  week?: number;
}

export interface MaterialsIndexingCompletedEvent {
  materialId: string;
  status: 'done' | 'failed';
  error?: string;
}
