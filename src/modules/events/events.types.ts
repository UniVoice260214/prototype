/**
 * Redis Pub/Sub channel names shared with the Python workers.
 */
export const EVENT_CHANNELS = {
  SESSIONS_STARTED: 'sessions.started',
  SESSIONS_ENDED: 'sessions.ended',
  MATERIALS_INDEXING_REQUESTED: 'materials.indexing.requested',
  MATERIALS_INDEXING_COMPLETED: 'materials.indexing.completed',
  TRANSCRIPTS_SEGMENT: 'transcripts.segment',
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

/**
 * AI 워커 진단 요약. 자막만 봐서는 알 수 없는 설정 누락을 교수 화면에 노출한다.
 * (glossary 0개 / lexicon 미적용 / RAG off)
 */
export interface WorkerDiagnostics {
  glossary: number;
  lexicon: string | null;
  phraseList: number;
  rag: 'on' | 'off';
}

export interface WorkerStatusPayload {
  status: WorkerStatus;
  ts: number;
  error?: string;
  diagnostics?: WorkerDiagnostics;
}

/** 로케일별 자막 항목. isFallback 이면 번역 실패로 한국어 원문이 그대로 전달된 것. */
export interface TranscriptTranslationEntry {
  text: string;
  isFallback: boolean;
}

/**
 * Python AI 워커가 번역 완료된 세그먼트마다 발행한다 (session_worker._publish_transcript).
 * NestJS TranscriptSubscriber 가 구독해 transcript_segments 테이블에 저장한다.
 */
export interface TranscriptSegmentEvent {
  type: 'transcript.segment';
  sessionId: string;
  segmentId: string;
  sequence: number;
  textKo: string;
  rawTextKo?: string | null;
  sttConfidence?: number | null;
  translations: Record<string, TranscriptTranslationEntry>;
  ts: number;
}

export interface MaterialsIndexingRequestedEvent {
  materialId: string;
  blobUrl: string;
  sourceType: 'lecture' | 'major';
  courseId: string;
  week?: number;
  /** 인덱서가 파서(PDF/PPT)를 고르는 데 쓴다. */
  originalFilename?: string;
  mimetype?: string;
}

export interface MaterialsIndexingCompletedEvent {
  materialId: string;
  /**
   * processing: 인덱서가 잡을 집었을 때 (같은 채널 재사용 — Material enum 에
   * processing 이 이미 있어 subscriber 는 그대로 기록하면 된다).
   */
  status: 'processing' | 'done' | 'failed';
  error?: string;
}
