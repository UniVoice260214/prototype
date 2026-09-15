import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
  OnApplicationBootstrap,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { IsNull, Repository } from 'typeorm';
import { CourseAccessService } from '../../common/access/course-access.service';
import { StudentSessionAccessService } from '../../common/access/student-session-access.service';
import { AuthUser } from '../../common/decorators/current-user.decorator';
import { RAG_INDEX_QUEUE_DEFAULT } from '../../common/redis-keys';
import { BlobService, DownloadResult } from '../../infra/blob/blob.service';
import { LiveKitService } from '../../infra/livekit/livekit.service';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';
import { EventsService } from '../events/events.service';
import { Session } from '../session/entities/session.entity';
import { Material } from './entities/material.entity';
import { MaterialPreviewService } from './material-preview.service';
import {
  StudentMaterialDto,
  StudentMaterialQueryDto,
  UploadMaterialDto,
} from './dto/material.dto';

/** 학생 화면에 LiveKit data 채널로 보내는 자료 변경 알림의 topic. */
export const MATERIALS_DATA_TOPIC = 'materials';

interface UploadFile {
  buffer: Buffer;
  originalname: string;
  mimetype: string;
  size: number;
}

@Injectable()
export class MaterialService implements OnApplicationBootstrap {
  private readonly logger = new Logger(MaterialService.name);
  private readonly ragQueue: string;

  constructor(
    @InjectRepository(Material) private readonly repo: Repository<Material>,
    @InjectRepository(Session) private readonly sessions: Repository<Session>,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    private readonly blob: BlobService,
    private readonly events: EventsService,
    private readonly courseAccess: CourseAccessService,
    private readonly studentAccess: StudentSessionAccessService,
    private readonly preview: MaterialPreviewService,
    private readonly liveKit: LiveKitService,
    config: ConfigService,
  ) {
    this.ragQueue = config.get<string>(
      'RAG_INDEX_QUEUE',
      RAG_INDEX_QUEUE_DEFAULT,
    );
  }

  /**
   * 변환은 프로세스 안에서만 돌므로 재시작 중 끊긴 pending 은 영원히 남는다.
   * 기동 시 failed 로 정리해 학생 화면이 "변환 중"에 갇히지 않게 한다.
   */
  async onApplicationBootstrap(): Promise<void> {
    try {
      const result = await this.repo.update(
        { previewStatus: 'pending' },
        { previewStatus: 'failed' },
      );
      if (result.affected) {
        this.logger.warn(
          `Marked ${result.affected} interrupted material preview(s) as failed`,
        );
      }
    } catch (err) {
      this.logger.warn(
        `Pending preview cleanup failed: ${this.errorMessage(err)}`,
      );
    }
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
    // PDF 는 원본이 곧 학생용 미리보기. PPT 는 저장 후 비동기로 변환한다.
    const isPdf = this.preview.isPdf(file);

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
          previewBlobUrl: isPdf ? blobUrl : null,
          previewStatus: isPdf ? 'ready' : 'pending',
        }),
      );
    } catch (err) {
      await this.deleteBlobBestEffort(blobUrl, 'failed material DB save');
      throw err;
    }

    // Deliver the indexing job through both a durable queue and a live event.
    const job = {
      materialId: material.id,
      courseId: material.courseId,
      blobUrl: material.blobUrl,
      sourceType: material.sourceType,
      week: material.week ?? undefined,
      // 인덱서가 PDF/PPT 를 구분해 파서를 고르는 데 필요하다.
      originalFilename: material.originalFilename,
      mimetype: file.mimetype,
    };
    await this.redis.lpush(this.ragQueue, JSON.stringify(job));
    try {
      await this.events.publishMaterialIndexingRequested(job);
    } catch (err) {
      this.logger.warn(
        `Material ${material.id} enqueued, but live publish failed: ${this.errorMessage(err)}`,
      );
    }

    this.logger.log(`Material ${material.id} enqueued to ${this.ragQueue}`);

    await this.notifyStudents(material, 'material.uploaded');
    if (!isPdf) {
      // 응답을 막지 않는다 — 변환은 수십 초가 걸릴 수 있고, 학생 화면은
      // 완료 알림(material.updated)을 받으면 그때 그린다.
      void this.buildPreview(material, file);
    }
    return material;
  }

  /** PPT/PPTX 를 PDF 로 변환해 previewBlobUrl 에 올린다. 실패해도 자료는 남는다. */
  private async buildPreview(
    material: Material,
    file: UploadFile,
  ): Promise<void> {
    try {
      const pdf = await this.preview.convertToPdf(file);
      if (pdf) {
        const { blobUrl } = await this.blob.upload(
          {
            buffer: pdf,
            originalname: `${stripExtension(file.originalname)}.pdf`,
            mimetype: 'application/pdf',
          },
          'previews',
        );
        material.previewBlobUrl = blobUrl;
        material.previewStatus = 'ready';
      } else {
        material.previewStatus = 'failed';
      }
    } catch (err) {
      this.logger.warn(
        `Preview build failed for material ${material.id}: ${this.errorMessage(err)}`,
      );
      material.previewStatus = 'failed';
    }
    let affected: number | null | undefined;
    try {
      ({ affected } = await this.repo.update(material.id, {
        previewBlobUrl: material.previewBlobUrl,
        previewStatus: material.previewStatus,
      }));
    } catch (err) {
      this.logger.warn(
        `Preview status save failed for material ${material.id}: ${this.errorMessage(err)}`,
      );
      return;
    }
    if (!affected) {
      // 변환 중에 삭제됐다 — 방금 올린 미리보기 blob 만 정리하고 조용히 끝낸다.
      if (material.previewBlobUrl) {
        await this.deleteBlobBestEffort(
          material.previewBlobUrl,
          `material ${material.id} deleted during preview`,
        );
      }
      return;
    }
    this.logger.log(
      `Material ${material.id} preview ${material.previewStatus}`,
    );
    await this.notifyStudents(material, 'material.updated');
  }

  /**
   * 과목의 진행 중인 세션 방마다 자료 변경을 브로드캐스트한다.
   * 알림 실패가 업로드/삭제 자체를 실패시키면 안 된다.
   */
  private async notifyStudents(
    material: Material,
    type: 'material.uploaded' | 'material.updated' | 'material.removed',
  ): Promise<void> {
    let active: Session[];
    try {
      // 세션에 묶인 자료는 그 세션 방에만, 과목 단위 자료는 과목의 모든 진행 중 방에.
      active = await this.sessions.find({
        where: material.sessionId
          ? { id: material.sessionId, status: 'active' }
          : { courseId: material.courseId, status: 'active' },
      });
    } catch (err) {
      this.logger.warn(
        `Active session lookup failed for course ${material.courseId}: ${this.errorMessage(err)}`,
      );
      return;
    }
    const payload = { type, material: this.toStudentView(material) };
    await Promise.all(
      active.map(async (session) => {
        try {
          await this.liveKit.sendData(
            session.liveKitRoomName,
            payload,
            MATERIALS_DATA_TOPIC,
          );
        } catch (err) {
          this.logger.warn(
            `Material notify failed for room ${session.liveKitRoomName}: ${this.errorMessage(err)}`,
          );
        }
      }),
    );
  }

  /**
   * 학생에게 보이는 자료: 강의안(lecture)만, 이 세션에 올린 것 + 세션 지정 없이
   * 미리 올린 것. 전공 자료(major)는 RAG 입력용이라 학생 화면에 내보내지 않는다.
   */
  private studentVisibleWhere(session: Session) {
    return [
      {
        courseId: session.courseId,
        sourceType: 'lecture' as const,
        sessionId: session.id,
      },
      {
        courseId: session.courseId,
        sourceType: 'lecture' as const,
        sessionId: IsNull(),
      },
    ];
  }

  async listForStudent(
    sessionId: string,
    dto: StudentMaterialQueryDto,
    authStudentId: string | null,
  ): Promise<StudentMaterialDto[]> {
    const session = await this.studentAccess.findSessionForStudent(
      sessionId,
      dto.joinToken,
      authStudentId,
    );
    const materials = await this.repo.find({
      where: this.studentVisibleWhere(session),
      order: { createdAt: 'ASC' },
    });
    return materials.map((material) => this.toStudentView(material));
  }

  async streamForStudent(
    sessionId: string,
    materialId: string,
    dto: StudentMaterialQueryDto,
    authStudentId: string | null,
  ): Promise<DownloadResult & { filename: string }> {
    const session = await this.studentAccess.findSessionForStudent(
      sessionId,
      dto.joinToken,
      authStudentId,
    );
    const material = await this.repo.findOne({
      where: this.studentVisibleWhere(session).map((where) => ({
        ...where,
        id: materialId,
      })),
    });
    if (!material) {
      throw new NotFoundException(`Material ${materialId} not found`);
    }
    if (material.previewStatus !== 'ready' || !material.previewBlobUrl) {
      throw new ConflictException(
        `Material preview is ${material.previewStatus}`,
      );
    }
    const download = await this.blob.download(material.previewBlobUrl);
    return {
      ...download,
      filename: `${stripExtension(material.originalFilename)}.pdf`,
    };
  }

  private toStudentView(material: Material): StudentMaterialDto {
    return {
      id: material.id,
      originalFilename: material.originalFilename,
      sourceType: material.sourceType,
      week: material.week,
      previewStatus: material.previewStatus,
      createdAt: material.createdAt,
    };
  }

  findAll(
    opts: { courseId?: string; sessionId?: string },
    user: AuthUser,
  ): Promise<Material[]> {
    return this.courseAccess.findMaterialsForUser(opts, user);
  }

  findOne(id: string, user: AuthUser): Promise<Material> {
    return this.courseAccess.findMaterialForUser(id, user);
  }

  async remove(id: string, user: AuthUser) {
    const material = await this.findOne(id, user);
    await this.deleteBlobBestEffort(material.blobUrl, `material ${id} delete`);
    if (
      material.previewBlobUrl &&
      material.previewBlobUrl !== material.blobUrl
    ) {
      await this.deleteBlobBestEffort(
        material.previewBlobUrl,
        `material ${id} preview delete`,
      );
    }
    await this.repo.delete(id);
    await this.notifyStudents(material, 'material.removed');
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

function stripExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
}
