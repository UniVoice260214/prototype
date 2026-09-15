import {
  BadRequestException,
  ForbiddenException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { AuthService } from '../../modules/auth/auth.service';
import { Session } from '../../modules/session/entities/session.entity';
import { SessionAttendance } from '../../modules/session/entities/session-attendance.entity';

/**
 * 학생(회원/게스트)의 세션 접근 검증.
 * Student JWT 는 실제 참여 기록이 있는 세션만, 게스트는 해당 세션에 발급된
 * QR JoinToken 으로만 통과한다. (TranscriptService.listForStudent 와 같은 규칙)
 */
@Injectable()
export class StudentSessionAccessService {
  constructor(
    @InjectRepository(Session) private readonly sessions: Repository<Session>,
    @InjectRepository(SessionAttendance)
    private readonly attendances: Repository<SessionAttendance>,
    private readonly auth: AuthService,
  ) {}

  async findSessionForStudent(
    sessionId: string,
    joinToken: string | undefined,
    authStudentId: string | null,
  ): Promise<Session> {
    const session = await this.sessions.findOne({ where: { id: sessionId } });
    if (!session) throw new NotFoundException(`Session ${sessionId} not found`);

    if (authStudentId) {
      const attended = await this.attendances.findOne({
        where: { studentId: authStudentId, sessionId },
      });
      if (!attended) {
        throw new ForbiddenException('No attendance record for this session');
      }
      return session;
    }

    if (!joinToken) {
      throw new BadRequestException(
        'Either Bearer Student JWT or joinToken is required',
      );
    }
    const payload = await this.auth.verifyJoinToken(joinToken);
    if (payload.sessionId !== sessionId) {
      throw new ForbiddenException('JoinToken sessionId mismatch');
    }
    return session;
  }
}
