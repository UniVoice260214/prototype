import { Inject, Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { Repository } from 'typeorm';
import { REDIS_SUBSCRIBER } from '../../infra/redis/redis.module';
import {
  EVENT_CHANNELS,
  MaterialsIndexingCompletedEvent,
} from '../events/events.types';
import { Material } from './entities/material.entity';

/**
 * RAG 워커 → Core 역방향 이벤트 수신기.
 * `materials.indexing.completed`를 구독해 Material.indexingStatus를 갱신한다.
 *
 * (교차검증에서 발견한 갭 보완: 세희 베이스는 completed 이벤트 타입만 정의하고
 *  구독자가 없어 indexingStatus가 영원히 'pending'에 머물렀음.)
 */
@Injectable()
export class MaterialIndexingSubscriber implements OnModuleInit {
  private readonly logger = new Logger(MaterialIndexingSubscriber.name);

  constructor(
    @Inject(REDIS_SUBSCRIBER) private readonly subscriber: Redis,
    @InjectRepository(Material) private readonly materials: Repository<Material>,
  ) {}

  async onModuleInit(): Promise<void> {
    await this.subscriber.subscribe(EVENT_CHANNELS.MATERIALS_INDEXING_COMPLETED);
    this.subscriber.on('message', (channel, raw) => {
      if (channel !== EVENT_CHANNELS.MATERIALS_INDEXING_COMPLETED) return;
      void this.handle(raw);
    });
    this.logger.log(
      `Subscribed to ${EVENT_CHANNELS.MATERIALS_INDEXING_COMPLETED}`,
    );
  }

  private async handle(raw: string): Promise<void> {
    let event: MaterialsIndexingCompletedEvent;
    try {
      event = JSON.parse(raw) as MaterialsIndexingCompletedEvent;
    } catch {
      this.logger.warn(`Malformed completed event: ${raw}`);
      return;
    }

    const res = await this.materials.update(
      { id: event.materialId },
      { indexingStatus: event.status },
    );
    if (res.affected) {
      this.logger.log(
        `Material ${event.materialId} indexingStatus → ${event.status}`,
      );
    } else {
      this.logger.warn(
        `Completed event for unknown material ${event.materialId}`,
      );
    }
  }
}
