import {
  BadRequestException,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { Repository } from 'typeorm';
import { CourseAccessService } from '../../common/access/course-access.service';
import { AuthUser } from '../../common/decorators/current-user.decorator';
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
    private readonly courseAccess: CourseAccessService,
    config: ConfigService,
  ) {
    this.ragQueue = config.get<string>(
      'RAG_INDEX_QUEUE',
      RAG_INDEX_QUEUE_DEFAULT,
    );
  }

  async upload(
    file: UploadFile,
    dto: UploadMaterialDto,
    user: AuthUser,
  ): Promise<Material> {
    await this.courseAccess.findCourseForUser(dto.courseId, user);
    if (dto.sessionId) {
      const session = await this.courseAccess.findSessionForUser(
        dto.sessionId,
        user,
      );
      if (session.courseId !== dto.courseId) {
        throw new BadRequestException('sessionId does not belong to courseId');
      }
    }

    const { blobUrl } = await this.blob.upload(file, 'materials');

    let material: Material;
    try {
      material = await this.repo.save(
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
    } catch (err) {
      await this.deleteBlobBestEffort(blobUrl, 'failed material DB save');
      throw err;
    }

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
    try {
      await this.events.publishMaterialIndexingRequested(job);
    } catch (err) {
      this.logger.warn(
        `Material ${material.id} enqueued, but live publish failed: ${this.errorMessage(err)}`,
      );
    }

    this.logger.log(`Material ${material.id} enqueued to ${this.ragQueue}`);
    return material;
  }

  findAll(opts: { courseId?: string; sessionId?: string }) {
    const where = Object.fromEntries(
      Object.entries(opts).filter(([, value]) => value !== undefined),
    );
    return this.repo.find({ where });
  }

  async findOne(id: string) {
    const m = await this.repo.findOne({ where: { id } });
    if (!m) throw new NotFoundException(`Material ${id} not found`);
    return m;
  }

  async remove(id: string, user: AuthUser) {
    const material = await this.findOne(id);
    await this.courseAccess.findCourseForUser(material.courseId, user);
    // Blob 원본 정리 (best-effort — 실패해도 DB 레코드는 삭제 진행)
    await this.deleteBlobBestEffort(material.blobUrl, `material ${id} delete`);
    await this.repo.delete(id);
  }

  private async deleteBlobBestEffort(
    blobUrl: string,
    reason: string,
  ): Promise<void> {
    try {
      await this.blob.deleteByUrl(blobUrl);
    } catch (err) {
      this.logger.warn(
        `Blob delete failed after ${reason}: ${this.errorMessage(err)}`,
      );
    }
  }

  private errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }
}
