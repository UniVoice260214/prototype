/**
 * Redis Pub/Sub channel names shared with the Python workers.
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

/**
 * Worker lifecycle is tracked through RedisKeys.workerStatus(sessionId) rather
 * than extra Pub/Sub events so restarts can recover from Redis state alone.
 */
export type WorkerStatus =
  | 'starting'
  | 'ready'
  | 'stopping'
  | 'stopped'
  | 'failed';

export interface WorkerStatusPayload {
  status: WorkerStatus;
  ts: number;
  error?: string;
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
