import {
  BadRequestException,
  ForbiddenException,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { Repository } from 'typeorm';
import { v4 as uuid } from 'uuid';
import { RedisKeys, SESSION_CONFIG_TTL_SEC } from '../../common/redis-keys';
import { CourseAccessService } from '../../common/access/course-access.service';
import { AuthUser } from '../../common/decorators/current-user.decorator';
import { LiveKitService } from '../../infra/livekit/livekit.service';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';
import { AuthService } from '../auth/auth.service';
import { EventsService } from '../events/events.service';
import { WorkerStatusPayload } from '../events/events.types';
import { Glossary } from '../glossary/entities/glossary.entity';
import { Session } from './entities/session.entity';
import {
  IssueStudentTokenDto,
  LiveKitTokenResponseDto,
  StartSessionDto,
} from './dto/session.dto';

@Injectable()
export class SessionService {
  private readonly logger = new Logger(SessionService.name);

  constructor(
    @InjectRepository(Session) private readonly sessions: Repository<Session>,
    @InjectRepository(Glossary)
    private readonly glossaries: Repository<Glossary>,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    private readonly liveKit: LiveKitService,
    private readonly events: EventsService,
    private readonly auth: AuthService,
    private readonly config: ConfigService,
    private readonly courseAccess: CourseAccessService,
  ) {}

  async start(
    dto: StartSessionDto,
    user: AuthUser,
  ): Promise<{ session: Session; liveKit: LiveKitTokenResponseDto }> {
    const course = await this.courseAccess.findCourseForUser(
      dto.courseId,
      user,
    );

    const roomName = `session-${uuid()}`;
    const session = await this.sessions.save(
      this.sessions.create({
        courseId: dto.courseId,
        liveKitRoomName: roomName,
        status: 'active',
        targetLocales: dto.targetLocales,
        startedAt: new Date(),
      }),
    );

    try {
      await this.liveKit.createRoom(roomName);
      await this.prewarmRedis(session);
      await this.events.publishSessionStarted({
        sessionId: session.id,
        courseId: session.courseId,
        liveKitRoomName: session.liveKitRoomName,
        targetLocales: session.targetLocales,
      });

      const token = await this.liveKit.createAccessToken({
        identity: `professor-${course.professorId}`,
        roomName,
        canPublish: true,
        canSubscribe: true,
        canPublishData: true,
        name: 'Professor',
        metadata: { role: 'professor', sessionId: session.id },
      });

      return {
        session,
        liveKit: {
          liveKitUrl: this.config.get<string>('LIVEKIT_URL') ?? '',
          token,
          roomName,
          identity: `professor-${course.professorId}`,
        },
      };
    } catch (err) {
      await this.sessions.delete(session.id).catch(() => undefined);
      await this.liveKit.deleteRoom(roomName).catch(() => undefined);
      await this.redis
        .del(
          RedisKeys.sessionConfig(session.id),
          RedisKeys.sessionStatus(session.id),
        )
        .catch(() => undefined);
      throw err;
    }
  }

  async end(sessionId: string, user: AuthUser): Promise<Session> {
    const session = await this.courseAccess.findSessionForUser(sessionId, user);
    if (session.status === 'ended') return session;

    await this.redis.set(
      RedisKeys.sessionStatus(session.id),
      'ending',
      'EX',
      SESSION_CONFIG_TTL_SEC,
    );

    try {
      await this.events.publishSessionEnded({ sessionId: session.id });
    } catch (err) {
      this.logger.warn(
        `Failed to publish sessions.ended for ${session.id}: ${this.errorMessage(err)}`,
      );
    }

    await this.waitForWorkerStopped(session.id);

    try {
      await this.liveKit.deleteRoom(session.liveKitRoomName);
    } catch (err) {
      this.logger.warn(
        `Failed to delete LiveKit room ${session.liveKitRoomName}: ${this.errorMessage(err)}`,
      );
    }

    session.status = 'ended';
    session.endedAt = new Date();
    try {
      await this.sessions.save(session);
    } catch (err) {
      this.logger.error(
        `Failed to persist ended session ${session.id}: ${this.errorMessage(err)}`,
      );
      throw err;
    }

    await this.redis.del(
      RedisKeys.sessionConfig(session.id),
      RedisKeys.sessionStatus(session.id),
      RedisKeys.workerStatus(session.id),
    );

    return session;
  }

  async issueStudentToken(
    sessionId: string,
    dto: IssueStudentTokenDto,
    authStudentId: string | null,
  ): Promise<LiveKitTokenResponseDto> {
    const session = await this.findOneById(sessionId);
    if (session.status !== 'active') {
      throw new BadRequestException('Session is not active');
    }
    if (!session.targetLocales.includes(dto.locale)) {
      throw new BadRequestException(
        `Locale ${dto.locale} not enabled for this session`,
      );
    }

    let identitySub: string;
    if (authStudentId) {
      identitySub = authStudentId;
    } else if (dto.joinToken) {
      const payload = await this.auth.verifyJoinToken(dto.joinToken);
      if (payload.sessionId !== sessionId) {
        throw new ForbiddenException('JoinToken sessionId mismatch');
      }
      identitySub = payload.sub;
    } else {
      throw new BadRequestException(
        'Either Bearer Student JWT or joinToken is required',
      );
    }

    const identity = `student-${identitySub}-${uuid().slice(0, 8)}`;
    const token = await this.liveKit.createAccessToken({
      identity,
      roomName: session.liveKitRoomName,
      canPublish: false,
      canSubscribe: true,
      canPublishData: false,
      name: 'Student',
      metadata: { role: 'student', locale: dto.locale, sessionId },
    });

    return {
      liveKitUrl: this.config.get<string>('LIVEKIT_URL') ?? '',
      token,
      roomName: session.liveKitRoomName,
      identity,
    };
  }

  findAll(courseId: string | undefined, user: AuthUser): Promise<Session[]> {
    return this.courseAccess.findSessionsForUser({ courseId }, user);
  }

  findOne(id: string, user: AuthUser): Promise<Session> {
    return this.courseAccess.findSessionForUser(id, user);
  }

  private async findOneById(id: string): Promise<Session> {
    const session = await this.sessions.findOne({ where: { id } });
    if (!session) throw new NotFoundException(`Session ${id} not found`);
    return session;
  }

  private async prewarmRedis(session: Session): Promise<void> {
    const configKey = RedisKeys.sessionConfig(session.id);
    const statusKey = RedisKeys.sessionStatus(session.id);
    const glossaryKey = RedisKeys.glossaryByCourse(session.courseId);

    const glossaries = await this.glossaries.find({
      where: { courseId: session.courseId },
    });

    const pipe = this.redis.multi();
    pipe.set(
      configKey,
      JSON.stringify({
        sessionId: session.id,
        courseId: session.courseId,
        liveKitRoomName: session.liveKitRoomName,
        targetLocales: session.targetLocales,
        startedAt: session.startedAt.toISOString(),
      }),
      'EX',
      SESSION_CONFIG_TTL_SEC,
    );
    pipe.set(statusKey, 'active', 'EX', SESSION_CONFIG_TTL_SEC);
    pipe.set(
      glossaryKey,
      JSON.stringify(
        glossaries.map((g) => ({
          term: g.term,
          pronunciation: g.pronunciation,
          definition: g.definition,
          translations: g.translations,
        })),
      ),
      'EX',
      SESSION_CONFIG_TTL_SEC,
    );
    await pipe.exec();
  }

  private async waitForWorkerStopped(sessionId: string): Promise<void> {
    const timeoutSec = this.config.get<number>('WORKER_STOP_TIMEOUT_SEC', 8);
    const pollIntervalMs =
      this.config.get<number>('WORKER_STOP_POLL_INTERVAL_MS') ??
      Number(this.config.get<string>('WORKER_STOP_POLL_INTERVAL_MS') ?? 200);
    const deadline = Date.now() + Math.max(0, timeoutSec) * 1000;
    const interval = Math.max(50, pollIntervalMs);

    while (Date.now() <= deadline) {
      const status = await this.readWorkerStatus(sessionId);
      if (status?.status === 'stopped') return;
      if (status?.status === 'failed') {
        this.logger.warn(
          `Worker for session ${sessionId} failed during shutdown: ${status.error ?? 'unknown error'}`,
        );
        return;
      }
      await this.sleep(interval);
    }
    this.logger.warn(
      `Timed out waiting for worker ${sessionId} to stop after ${timeoutSec}s`,
    );
  }

  private async readWorkerStatus(
    sessionId: string,
  ): Promise<WorkerStatusPayload | null> {
    let raw: string | null;
    try {
      raw = await this.redis.get(RedisKeys.workerStatus(sessionId));
    } catch (err) {
      this.logger.warn(
        `Failed to read worker status for ${sessionId}: ${this.errorMessage(err)}`,
      );
      return null;
    }
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as WorkerStatusPayload;
      if (
        parsed &&
        ['starting', 'ready', 'stopping', 'stopped', 'failed'].includes(
          parsed.status,
        )
      ) {
        return parsed;
      }
    } catch {
      if (
        ['starting', 'ready', 'stopping', 'stopped', 'failed'].includes(raw)
      ) {
        return {
          status: raw as WorkerStatusPayload['status'],
          ts: Date.now() / 1000,
        };
      }
    }
    this.logger.warn(
      `Ignoring malformed worker status for ${sessionId}: ${raw}`,
    );
    return null;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }
}
