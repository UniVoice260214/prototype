import {
  BadRequestException,
  ForbiddenException,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { MoreThan, Repository } from 'typeorm';
import { CourseAccessService } from '../../common/access/course-access.service';
import { AuthUser } from '../../common/decorators/current-user.decorator';
import { AuthService } from '../auth/auth.service';
import { TranscriptSegmentEvent } from '../events/events.types';
import { Session } from '../session/entities/session.entity';
import { SessionAttendance } from '../session/entities/session-attendance.entity';
import { TranscriptSegment } from './entities/transcript-segment.entity';
import {
  ListTranscriptsQueryDto,
  StudentTranscriptQueryDto,
  TRANSCRIPT_DEFAULT_LIMIT,
  TRANSCRIPT_MAX_LIMIT,
} from './dto/transcript.dto';

@Injectable()
export class TranscriptService {
  private readonly logger = new Logger(TranscriptService.name);

  constructor(
    @InjectRepository(TranscriptSegment)
    private readonly segments: Repository<TranscriptSegment>,
    @InjectRepository(Session)
    private readonly sessions: Repository<Session>,
    @InjectRepository(SessionAttendance)
    private readonly attendances: Repository<SessionAttendance>,
    private readonly courseAccess: CourseAccessService,
    private readonly auth: AuthService,
  ) {}

  /** 교수/관리자용 이력 조회. 세션 접근 권한을 CourseAccessService 로 검증한다. */
  async listForUser(
    sessionId: string,
    query: ListTranscriptsQueryDto,
    user: AuthUser,
  ): Promise<TranscriptSegment[]> {
    await this.courseAccess.findSessionForUser(sessionId, user);
    return this.list(sessionId, query);
  }

  /**
   * 학생용 이력 조회. Student JWT 또는 QR JoinToken 으로 접근한다.
   * JoinToken 은 해당 세션에 발급된 것이어야 한다.
   */
  async listForStudent(
    sessionId: string,
    dto: StudentTranscriptQueryDto,
    authStudentId: string | null,
  ): Promise<TranscriptSegment[]> {
    const session = await this.sessions.findOne({ where: { id: sessionId } });
    if (!session) throw new NotFoundException(`Session ${sessionId} not found`);

    if (authStudentId) {
      // 실제로 참여한 세션만 열람할 수 있다. 예전에는 Student JWT 만 있으면
      // 아무 세션이나 무검증 통과되는 구멍이 있었다.
      const attended = await this.attendances.findOne({
        where: { studentId: authStudentId, sessionId },
      });
      if (!attended) {
        throw new ForbiddenException('No attendance record for this session');
      }
    } else {
      if (!dto.joinToken) {
        throw new BadRequestException(
          'Either Bearer Student JWT or joinToken is required',
        );
      }
      const payload = await this.auth.verifyJoinToken(dto.joinToken);
      if (payload.sessionId !== sessionId) {
        throw new ForbiddenException('JoinToken sessionId mismatch');
      }
    }
    return this.list(sessionId, dto);
  }

  private list(
    sessionId: string,
    query: ListTranscriptsQueryDto,
  ): Promise<TranscriptSegment[]> {
    const limit = Math.min(
      query.limit ?? TRANSCRIPT_DEFAULT_LIMIT,
      TRANSCRIPT_MAX_LIMIT,
    );
    return this.segments.find({
      where: {
        sessionId,
        ...(query.afterSequence !== undefined
          ? { sequence: MoreThan(query.afterSequence) }
          : {}),
      },
      order: { sequence: 'ASC', createdAt: 'ASC' },
      take: limit,
    });
  }

  /** Redis 이벤트로 받은 세그먼트를 저장한다. segmentId 재수신은 최신 값으로 덮어쓴다. */
  async upsertFromEvent(event: TranscriptSegmentEvent): Promise<void> {
    await this.segments.upsert(
      {
        sessionId: event.sessionId,
        segmentId: event.segmentId,
        sequence: event.sequence,
        textKo: event.textKo,
        rawTextKo: event.rawTextKo ?? null,
        sttConfidence: event.sttConfidence ?? null,
        translations: event.translations ?? {},
      },
      ['segmentId'],
    );
  }
}
