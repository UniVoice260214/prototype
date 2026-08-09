jest.mock('bcrypt', () => ({
  compare: jest.fn(),
  hash: jest.fn(),
}));

import { SessionService } from './session.service';
import { RedisKeys } from '../../common/redis-keys';
import { AuthUser } from '../../common/decorators/current-user.decorator';

const ADMIN_USER: AuthUser = {
  sub: 'admin-1',
  role: 'admin',
  type: 'user',
};

function makeSession(overrides: Record<string, unknown> = {}) {
  return {
    id: 'session-123',
    courseId: 'course-1',
    liveKitRoomName: 'room-1',
    status: 'active',
    targetLocales: ['vi-VN'],
    startedAt: new Date('2026-01-01T00:00:00.000Z'),
    endedAt: null,
    ...overrides,
  } as any;
}

function makeService(options: {
  session?: any;
  workerStatus?: string | null;
  order?: string[];
  timeoutSec?: number;
  redisGetError?: Error;
  deleteRoomError?: Error;
}) {
  const order = options.order ?? [];
  const session = options.session ?? makeSession();
  const sessions = {
    findOne: jest.fn(async () => session),
    save: jest.fn(async (entity) => {
      order.push('db.save');
      return entity;
    }),
    create: jest.fn((entity) => entity),
    delete: jest.fn(),
  };
  const redis = {
    set: jest.fn(async (...args: unknown[]) => {
      order.push(`redis.set:${args[1]}`);
    }),
    get: jest.fn(async (key: string) => {
      if (options.redisGetError) throw options.redisGetError;
      if (key === RedisKeys.workerStatus(session.id)) {
        return options.workerStatus ?? null;
      }
      return null;
    }),
    del: jest.fn(async (..._keys: string[]) => {
      order.push('redis.del');
    }),
    multi: jest.fn(),
  };
  const liveKit = {
    createRoom: jest.fn(),
    createAccessToken: jest.fn(),
    deleteRoom: jest.fn(async () => {
      order.push('livekit.deleteRoom');
      if (options.deleteRoomError) throw options.deleteRoomError;
    }),
  };
  const events = {
    publishSessionStarted: jest.fn(),
    publishSessionEnded: jest.fn(async () => {
      order.push('events.ended');
    }),
  };
  const config = {
    get: jest.fn((key: string) => {
      if (key === 'WORKER_STOP_TIMEOUT_SEC') return options.timeoutSec ?? 0;
      if (key === 'WORKER_STOP_POLL_INTERVAL_MS') return 1;
      if (key === 'LIVEKIT_URL') return 'ws://livekit';
      return undefined;
    }),
  };
  const courseAccess = {
    findCourseForUser: jest.fn(async () => ({
      id: 'course-1',
      professorId: 'professor-1',
    })),
    findSessionForUser: jest.fn(async () => session),
  };

  const attendances = { upsert: jest.fn(async () => undefined) };
  const service = new SessionService(
    sessions as any,
    attendances as any,
    { find: jest.fn() } as any,
    redis as any,
    liveKit as any,
    events as any,
    {} as any,
    config as any,
    courseAccess as any,
  );

  return {
    service,
    attendances,
    session,
    sessions,
    redis,
    liveKit,
    events,
    config,
    courseAccess,
    order,
  };
}

describe('SessionService.end', () => {
  it('publishes sessions.ended before deleting the LiveKit room', async () => {
    const { service, order } = makeService({
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
    });

    await service.end('session-123', ADMIN_USER);

    expect(order.indexOf('events.ended')).toBeLessThan(
      order.indexOf('livekit.deleteRoom'),
    );
  });

  it('deletes the room immediately when worker status is stopped', async () => {
    const { service, liveKit, redis } = makeService({
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
      timeoutSec: 8,
    });

    await service.end('session-123', ADMIN_USER);

    expect(redis.get).toHaveBeenCalledTimes(1);
    expect(liveKit.deleteRoom).toHaveBeenCalledWith('room-1');
  });

  it('continues ending the session when worker stopped polling times out', async () => {
    const { service, liveKit, sessions, redis } = makeService({
      workerStatus: null,
      timeoutSec: 0,
    });

    await service.end('session-123', ADMIN_USER);

    expect(liveKit.deleteRoom).toHaveBeenCalledWith('room-1');
    expect(sessions.save).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'ended' }),
    );
    expect(redis.del).toHaveBeenCalled();
  });

  it('marks Redis status as ending before publishing sessions.ended', async () => {
    const { service, order, redis } = makeService({
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
    });

    await service.end('session-123', ADMIN_USER);

    expect(redis.set).toHaveBeenCalledWith(
      RedisKeys.sessionStatus('session-123'),
      'ending',
      'EX',
      expect.any(Number),
    );
    expect(order.indexOf('redis.set:ending')).toBeLessThan(
      order.indexOf('events.ended'),
    );
  });

  it('stores endedAt when DB session is ended', async () => {
    const { service, session, sessions } = makeService({
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
    });

    await service.end('session-123', ADMIN_USER);

    expect(session.status).toBe('ended');
    expect(session.endedAt).toBeInstanceOf(Date);
    expect(sessions.save).toHaveBeenCalledWith(session);
  });

  it('cleans Redis only after room deletion and DB ended save', async () => {
    const { service, order } = makeService({
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
    });

    await service.end('session-123', ADMIN_USER);

    expect(order).toEqual([
      'redis.set:ending',
      'events.ended',
      'livekit.deleteRoom',
      'db.save',
      'redis.del',
    ]);
  });

  it('removes session config, session status, and worker status keys at the end', async () => {
    const { service, redis } = makeService({
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
    });

    await service.end('session-123', ADMIN_USER);

    expect(redis.del).toHaveBeenCalledWith(
      RedisKeys.sessionConfig('session-123'),
      RedisKeys.sessionStatus('session-123'),
      RedisKeys.workerStatus('session-123'),
    );
  });

  it('is safe to call repeatedly after the DB session is ended', async () => {
    const session = makeSession();
    const { service, liveKit, events } = makeService({
      session,
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
    });

    await service.end('session-123', ADMIN_USER);
    await service.end('session-123', ADMIN_USER);

    expect(events.publishSessionEnded).toHaveBeenCalledTimes(1);
    expect(liveKit.deleteRoom).toHaveBeenCalledTimes(1);
  });

  it('continues when room is already deleted or deleteRoom fails', async () => {
    const { service, sessions, redis } = makeService({
      workerStatus: JSON.stringify({ status: 'stopped', ts: 1 }),
      deleteRoomError: new Error('already gone'),
    });

    await service.end('session-123', ADMIN_USER);

    expect(sessions.save).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'ended' }),
    );
    expect(redis.del).toHaveBeenCalled();
  });

  it('falls back safely when Redis worker-status polling fails', async () => {
    const { service, liveKit, sessions, redis } = makeService({
      redisGetError: new Error('redis unavailable'),
      timeoutSec: 0,
    });

    await service.end('session-123', ADMIN_USER);

    expect(redis.get).toHaveBeenCalledWith(
      RedisKeys.workerStatus('session-123'),
    );
    expect(liveKit.deleteRoom).toHaveBeenCalledWith('room-1');
    expect(sessions.save).toHaveBeenCalled();
  });
});
