import {
  BadRequestException,
  ForbiddenException,
  Inject,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { Repository } from 'typeorm';
import { v4 as uuid } from 'uuid';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';
import { RedisKeys, SESSION_CONFIG_TTL_SEC } from '../../common/redis-keys';
import { LiveKitService } from '../../infra/livekit/livekit.service';
import { AuthService } from '../auth/auth.service';
import { Course } from '../course/entities/course.entity';
import { EventsService } from '../events/events.service';
import { Glossary } from '../glossary/entities/glossary.entity';
import { Session } from './entities/session.entity';
import {
  IssueStudentTokenDto,
  LiveKitTokenResponseDto,
  StartSessionDto,
} from './dto/session.dto';

@Injectable()
export class SessionService {
  constructor(
    @InjectRepository(Session) private readonly sessions: Repository<Session>,
    @InjectRepository(Course) private readonly courses: Repository<Course>,
    @InjectRepository(Glossary) private readonly glossaries: Repository<Glossary>,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    private readonly liveKit: LiveKitService,
    private readonly events: EventsService,
    private readonly auth: AuthService,
    private readonly config: ConfigService,
  ) {}

  /**
   * 세션 시작 워크플로 (CLAUDE.md 참조):
   *   1. Session 레코드 생성
   *   2. LiveKit Room 생성
   *   3. Redis prewarm (session:{id}:config, glossary:{courseId})
   *   4. sessions.started 이벤트 publish
   *   5. 교수용 LiveKit token 반환
   */
  async start(
    dto: StartSessionDto,
  ): Promise<{ session: Session; liveKit: LiveKitTokenResponseDto }> {
    const course = await this.courses.findOne({ where: { id: dto.courseId } });
    if (!course) throw new NotFoundException(`Course ${dto.courseId} not found`);

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

    // 한 단계라도 실패하면 고아 Session/Room/Redis를 정리하고 재던진다 (보상 트랜잭션).
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
        .del(RedisKeys.sessionConfig(session.id), RedisKeys.sessionStatus(session.id))
        .catch(() => undefined);
      throw err;
    }
  }

  async end(sessionId: string): Promise<Session> {
    const session = await this.findOne(sessionId);
    if (session.status === 'ended') return session;

    session.status = 'ended';
    session.endedAt = new Date();
    await this.sessions.save(session);

    await this.liveKit.deleteRoom(session.liveKitRoomName);
    await this.events.publishSessionEnded({ sessionId: session.id });

    // Redis 키 즉시 정리 (TTL 안전망과 별개로).
    await this.redis.del(
      RedisKeys.sessionConfig(session.id),
      RedisKeys.sessionStatus(session.id),
    );

    return session;
  }

  async issueStudentToken(
    sessionId: string,
    dto: IssueStudentTokenDto,
    authStudentId: string | null,
  ): Promise<LiveKitTokenResponseDto> {
    const session = await this.findOne(sessionId);
    if (session.status !== 'active') {
      throw new BadRequestException('Session is not active');
    }
    if (!session.targetLocales.includes(dto.locale)) {
      throw new BadRequestException(
        `Locale ${dto.locale} not enabled for this session`,
      );
    }

    // Identity 결정: Student JWT가 있으면 그 id, 없으면 JoinToken 검증
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

  findAll(courseId?: string) {
    return this.sessions.find({ where: courseId ? { courseId } : {} });
  }

  async findOne(id: string): Promise<Session> {
    const s = await this.sessions.findOne({ where: { id } });
    if (!s) throw new NotFoundException(`Session ${id} not found`);
    return s;
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
}
