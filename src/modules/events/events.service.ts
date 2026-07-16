import { Inject, Injectable, Logger } from '@nestjs/common';
import type Redis from 'ioredis';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';
import {
  EVENT_CHANNELS,
  EventChannel,
  MaterialsIndexingRequestedEvent,
  SessionsEndedEvent,
  SessionsStartedEvent,
} from './events.types';

/**
 * 모든 외부 시스템 이벤트(Pub/Sub) 발행의 단일 진입점.
 * NestJS → Python 워커 / RAG 워커로 전달되는 메시지는 반드시 이 서비스를 통해 publish.
 */
@Injectable()
export class EventsService {
  private readonly logger = new Logger(EventsService.name);

  constructor(@Inject(REDIS_CLIENT) private readonly redis: Redis) {}

  async publishSessionStarted(payload: SessionsStartedEvent): Promise<void> {
    await this.publish(EVENT_CHANNELS.SESSIONS_STARTED, payload);
  }

  async publishSessionEnded(payload: SessionsEndedEvent): Promise<void> {
    await this.publish(EVENT_CHANNELS.SESSIONS_ENDED, payload);
  }

  async publishMaterialIndexingRequested(
    payload: MaterialsIndexingRequestedEvent,
  ): Promise<void> {
    await this.publish(EVENT_CHANNELS.MATERIALS_INDEXING_REQUESTED, payload);
  }

  private async publish<T>(channel: EventChannel, payload: T): Promise<void> {
    const message = JSON.stringify(payload);
    const subscribers = await this.redis.publish(channel, message);
    this.logger.debug(
      `[${channel}] published to ${subscribers} subscriber(s): ${message}`,
    );
  }
}
