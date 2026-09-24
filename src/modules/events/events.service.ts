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
 * Single entry point for outbound Redis Pub/Sub events.
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
