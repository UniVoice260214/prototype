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

@Injectable()
export class MaterialIndexingSubscriber implements OnModuleInit {
  private readonly logger = new Logger(MaterialIndexingSubscriber.name);

  constructor(
    @Inject(REDIS_SUBSCRIBER) private readonly subscriber: Redis,
    @InjectRepository(Material)
    private readonly materials: Repository<Material>,
  ) {}

  async onModuleInit(): Promise<void> {
    await this.subscriber.subscribe(
      EVENT_CHANNELS.MATERIALS_INDEXING_COMPLETED,
    );
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

    try {
      const res = await this.materials.update(
        { id: event.materialId },
        { indexingStatus: event.status },
      );
      if (res.affected) {
        this.logger.log(
          `Material ${event.materialId} indexingStatus updated to ${event.status}`,
        );
      } else {
        this.logger.warn(
          `Completed event for unknown material ${event.materialId}`,
        );
      }
    } catch (err) {
      this.logger.error(
        `Failed to update material ${event.materialId} indexingStatus: ${this.errorMessage(err)}`,
      );
    }
  }

  private errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }
}
