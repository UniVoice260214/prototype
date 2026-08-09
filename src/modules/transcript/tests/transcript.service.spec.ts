jest.mock('bcrypt', () => ({
  compare: jest.fn(),
  hash: jest.fn(),
}));

import {
  BadRequestException,
  ForbiddenException,
  NotFoundException,
} from '@nestjs/common';
import { AuthUser } from '../../../common/decorators/current-user.decorator';
import { TranscriptSegmentEvent } from '../../events/events.types';
import { TranscriptService } from '../transcript.service';

const PROFESSOR_USER: AuthUser = {
  sub: 'user-1',
  role: 'professor',
  type: 'user',
};

function makeEvent(
  overrides: Partial<TranscriptSegmentEvent> = {},
): TranscriptSegmentEvent {
  return {
    type: 'transcript.segment',
    sessionId: 'session-1',
    segmentId: 'session-1-seg-000001',
    sequence: 1,
    textKo: '안녕하세요.',
    rawTextKo: null,
    sttConfidence: 0.9,
    translations: {
      'vi-VN': { text: 'xin chao', isFallback: false },
    },
    ts: 1700000000,
    ...overrides,
  };
}

function makeService(options: {
  session?: unknown;
  found?: unknown[];
  sessionAccessError?: Error;
  joinPayload?: { sub: string; sessionId: string };
  joinError?: Error;
  /** 로그인 학생의 참여 기록. 없으면 미참여(=Forbidden) 취급. */
  attendance?: unknown;
}) {
  const segments = {
    find: jest.fn(() => Promise.resolve(options.found ?? [])),
    upsert: jest.fn(() => Promise.resolve(undefined)),
  };
  const sessions = {
    findOne: jest.fn(() => Promise.resolve(options.session ?? null)),
  };
  const attendances = {
    findOne: jest.fn(() => Promise.resolve(options.attendance ?? null)),
  };
  const courseAccess = {
    findSessionForUser: jest.fn(() =>
      options.sessionAccessError
        ? Promise.reject(options.sessionAccessError)
        : Promise.resolve(options.session ?? { id: 'session-1' }),
    ),
  };
  const auth = {
    verifyJoinToken: jest.fn(() =>
      options.joinError
        ? Promise.reject(options.joinError)
        : Promise.resolve(
            options.joinPayload ?? { sub: 'guest', sessionId: 'session-1' },
          ),
    ),
  };
  const service = new TranscriptService(
    segments as never,
    sessions as never,
    attendances as never,
    courseAccess as never,
    auth as never,
  );
  return { service, segments, sessions, attendances, courseAccess, auth };
}

describe('TranscriptService', () => {
  it('lists segments for a professor after access check', async () => {
    const rows = [{ sequence: 1 }, { sequence: 2 }];
    const { service, segments, courseAccess } = makeService({ found: rows });

    const result = await service.listForUser('session-1', {}, PROFESSOR_USER);

    expect(courseAccess.findSessionForUser).toHaveBeenCalledWith(
      'session-1',
      PROFESSOR_USER,
    );
    expect(result).toBe(rows);
    expect(segments.find).toHaveBeenCalledWith(
      expect.objectContaining({
        where: expect.objectContaining({ sessionId: 'session-1' }) as object,
        take: 200,
      }),
    );
  });

  it('applies afterSequence and clamps limit', async () => {
    const { service, segments } = makeService({ found: [] });

    await service.listForUser(
      'session-1',
      { afterSequence: 10, limit: 400 },
      PROFESSOR_USER,
    );

    const args = (segments.find.mock.calls[0] as unknown[])[0] as {
      where: Record<string, unknown>;
      take: number;
    };
    expect(args.take).toBe(400);
    expect(args.where.sequence).toBeDefined();
  });

  it('rejects student query without JWT or joinToken', async () => {
    const { service } = makeService({ session: { id: 'session-1' } });

    await expect(
      service.listForStudent('session-1', {}, null),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  it('rejects joinToken issued for another session', async () => {
    const { service } = makeService({
      session: { id: 'session-1' },
      joinPayload: { sub: 'guest', sessionId: 'other-session' },
    });

    await expect(
      service.listForStudent('session-1', { joinToken: 'token' }, null),
    ).rejects.toBeInstanceOf(ForbiddenException);
  });

  it('returns rows for a valid joinToken', async () => {
    const rows = [{ sequence: 1 }];
    const { service } = makeService({
      session: { id: 'session-1' },
      found: rows,
      joinPayload: { sub: 'guest', sessionId: 'session-1' },
    });

    await expect(
      service.listForStudent('session-1', { joinToken: 'token' }, null),
    ).resolves.toBe(rows);
  });

  it('allows an authenticated student who attended the session', async () => {
    const rows = [{ sequence: 1 }];
    const { service, auth, attendances } = makeService({
      session: { id: 'session-1' },
      found: rows,
      attendance: { studentId: 'student-1', sessionId: 'session-1' },
    });

    await expect(
      service.listForStudent('session-1', {}, 'student-1'),
    ).resolves.toBe(rows);
    expect(auth.verifyJoinToken).not.toHaveBeenCalled();
    expect(attendances.findOne).toHaveBeenCalledWith({
      where: { studentId: 'student-1', sessionId: 'session-1' },
    });
  });

  it('rejects an authenticated student without an attendance record', async () => {
    // 예전에는 Student JWT 만 있으면 아무 세션이나 무검증 통과되는 구멍이 있었다.
    const { service } = makeService({
      session: { id: 'session-1' },
      attendance: null,
    });

    await expect(
      service.listForStudent('session-1', {}, 'student-1'),
    ).rejects.toBeInstanceOf(ForbiddenException);
  });

  it('throws NotFound for an unknown session on student query', async () => {
    const { service } = makeService({ session: null });

    await expect(
      service.listForStudent('missing', { joinToken: 't' }, null),
    ).rejects.toBeInstanceOf(NotFoundException);
  });

  it('upserts events idempotently by segmentId', async () => {
    const { service, segments } = makeService({});

    await service.upsertFromEvent(makeEvent());
    await service.upsertFromEvent(makeEvent({ textKo: '수정된 문장.' }));

    expect(segments.upsert).toHaveBeenCalledTimes(2);
    expect(segments.upsert).toHaveBeenLastCalledWith(
      expect.objectContaining({
        segmentId: 'session-1-seg-000001',
        textKo: '수정된 문장.',
      }),
      ['segmentId'],
    );
  });
});
