import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { Repository } from 'typeorm';
import { RAG_INDEX_QUEUE_DEFAULT } from '../../common/redis-keys';
import { BlobService } from '../../infra/blob/blob.service';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';
import { EventsService } from '../events/events.service';
import { Material } from './entities/material.entity';
import { UploadMaterialDto } from './dto/material.dto';

interface UploadFile {
  buffer: Buffer;
  originalname: string;
  mimetype: string;
  size: number;
}

@Injectable()
export class MaterialService {
  private readonly logger = new Logger(MaterialService.name);
  private readonly ragQueue: string;

  constructor(
    @InjectRepository(Material) private readonly repo: Repository<Material>,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    private readonly blob: BlobService,
    private readonly events: EventsService,
    config: ConfigService,
  ) {
    this.ragQueue = config.get<string>('RAG_INDEX_QUEUE', RAG_INDEX_QUEUE_DEFAULT);
  }

  async upload(file: UploadFile, dto: UploadMaterialDto): Promise<Material> {
    const { blobUrl } = await this.blob.upload(file, 'materials');

    const material = await this.repo.save(
      this.repo.create({
        courseId: dto.courseId,
        sessionId: dto.sessionId ?? null,
        blobUrl,
        originalFilename: file.originalname,
        sourceType: dto.sourceType,
        week: dto.week ?? null,
        indexingStatus: 'pending',
      }),
    );

    // RAG 인덱싱 트리거 — 2단계 전달 (best-of: 세희 pub/sub + 서영 durable queue)
    //  (1) 내구성 큐(Redis List)에 적재 → RAG 워커가 꺼져 있어도 유실 없음 (서영 설계)
    const job = {
      materialId: material.id,
      courseId: material.courseId,
      blobUrl: material.blobUrl,
      sourceType: material.sourceType,
      week: material.week ?? undefined,
    };
    await this.redis.lpush(this.ragQueue, JSON.stringify(job));
    //  (2) 라이브 알림 이벤트도 publish (세희 설계) → 워커가 떠 있으면 즉시 반응
    await this.events.publishMaterialIndexingRequested(job);

    this.logger.log(
      `Material ${material.id} enqueued to ${this.ragQueue} + event published`,
    );
    return material;
  }

  findAll(opts: { courseId?: string; sessionId?: string }) {
    return this.repo.find({ where: opts });
  }

  async findOne(id: string) {
    const m = await this.repo.findOne({ where: { id } });
    if (!m) throw new NotFoundException(`Material ${id} not found`);
    return m;
  }

  async remove(id: string) {
    const material = await this.findOne(id);
    // Blob 원본 정리 (best-effort — 실패해도 DB 레코드는 삭제 진행)
    try {
      await this.blob.deleteByUrl(material.blobUrl);
    } catch (err) {
      this.logger.warn(
        `Blob delete failed for material ${id}: ${(err as Error).message}`,
      );
    }
    await this.repo.delete(id);
  }
}
