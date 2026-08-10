import { Inject, Injectable, Logger, OnModuleInit } from '@nestjs/common';
import type Redis from 'ioredis';
import { REDIS_SUBSCRIBER } from '../../infra/redis/redis.module';
import { EVENT_CHANNELS, TranscriptSegmentEvent } from '../events/events.types';
import { TranscriptService } from './transcript.service';

/**
 * Python AI 워커가 발행하는 transcripts.segment 이벤트를 구독해 DB 에 저장한다.
 * 저장 실패는 로그만 남긴다 — 실시간 자막 전달(LiveKit DataChannel)과는 독립 경로다.
 */
@Injectable()
export class TranscriptSubscriber implements OnModuleInit {
  private readonly logger = new Logger(TranscriptSubscriber.name);

  constructor(
    @Inject(REDIS_SUBSCRIBER) private readonly subscriber: Redis,
    private readonly service: TranscriptService,
  ) {}

  async onModuleInit(): Promise<void> {
    await this.subscriber.subscribe(EVENT_CHANNELS.TRANSCRIPTS_SEGMENT);
    this.subscriber.on('message', (channel, raw) => {
      if (channel !== EVENT_CHANNELS.TRANSCRIPTS_SEGMENT) return;
      void this.handle(raw);
    });
    this.logger.log(`Subscribed to ${EVENT_CHANNELS.TRANSCRIPTS_SEGMENT}`);
  }

  private async handle(raw: string): Promise<void> {
    let event: TranscriptSegmentEvent;
    try {
      event = JSON.parse(raw) as TranscriptSegmentEvent;
    } catch {
      this.logger.warn(`Malformed transcript event: ${raw}`);
      return;
    }
    if (
      !event?.sessionId ||
      !event.segmentId ||
      typeof event.sequence !== 'number' ||
      typeof event.textKo !== 'string'
    ) {
      this.logger.warn(
        `Transcript event missing required fields: ${raw.slice(0, 200)}`,
      );
      return;
    }

    try {
      await this.service.upsertFromEvent(event);
    } catch (err) {
      // 종료 직후 도착 등으로 세션 FK 가 깨질 수 있다. 저장 실패가 다른 경로를 막지 않는다.
      this.logger.error(
        `Failed to persist transcript ${event.segmentId}: ${this.errorMessage(err)}`,
      );
    }
  }

  private errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }
}
