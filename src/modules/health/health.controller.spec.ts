import { ServiceUnavailableException } from '@nestjs/common';
import { HealthController } from './health.controller';

describe('HealthController', () => {
  it('reports process liveness without checking dependencies', () => {
    const dataSource = { query: jest.fn() };
    const redis = { ping: jest.fn() };
    const controller = new HealthController(dataSource as any, redis as any);

    expect(controller.live()).toEqual({
      status: 'ok',
      timestamp: expect.any(String),
    });
    expect(dataSource.query).not.toHaveBeenCalled();
    expect(redis.ping).not.toHaveBeenCalled();
  });

  it('reports readiness when PostgreSQL and Redis respond', async () => {
    const dataSource = {
      query: jest.fn().mockResolvedValue([{ '?column?': 1 }]),
    };
    const redis = { ping: jest.fn().mockResolvedValue('PONG') };
    const controller = new HealthController(dataSource as any, redis as any);

    await expect(controller.ready()).resolves.toEqual({
      status: 'ok',
      checks: {
        database: 'up',
        redis: 'up',
      },
      timestamp: expect.any(String),
    });
    expect(dataSource.query).toHaveBeenCalledWith('SELECT 1');
    expect(redis.ping).toHaveBeenCalled();
  });

  it('returns 503 when a dependency is unavailable', async () => {
    const dataSource = {
      query: jest.fn().mockRejectedValue(new Error('database unavailable')),
    };
    const redis = { ping: jest.fn().mockResolvedValue('PONG') };
    const controller = new HealthController(dataSource as any, redis as any);

    await expect(controller.ready()).rejects.toBeInstanceOf(
      ServiceUnavailableException,
    );
  });
});
