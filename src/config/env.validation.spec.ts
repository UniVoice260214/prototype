import 'reflect-metadata';
import { NodeEnv, validateEnv } from './env.validation';

const baseEnv = {
  PORT: 3000,
  NODE_ENV: NodeEnv.Production,
  DATABASE_URL: 'postgresql://user:password@postgres:5432/univoice',
  REDIS_URL: 'redis://redis:6379',
  JWT_SECRET: 'abcdefghijklmnopqrstuvwxyz123456',
  QR_BASE_URL: 'https://staging.test.dev/join',
};

describe('validateEnv production safety', () => {
  it('accepts a production-safe configuration', () => {
    expect(validateEnv(baseEnv)).toEqual(
      expect.objectContaining({
        NODE_ENV: NodeEnv.Production,
        JWT_SECRET: baseEnv.JWT_SECRET,
      }),
    );
  });

  it('rejects a short production JWT secret', () => {
    expect(() =>
      validateEnv({
        ...baseEnv,
        JWT_SECRET: 'too-short',
      }),
    ).toThrow('JWT_SECRET must be at least 32 characters in production');
  });

  it('rejects an insecure production QR URL', () => {
    expect(() =>
      validateEnv({
        ...baseEnv,
        QR_BASE_URL: 'http://staging.test.dev/join',
      }),
    ).toThrow('QR_BASE_URL must use https:// in production');
  });

  it('rejects the development auth bypass in production', () => {
    expect(() =>
      validateEnv({
        ...baseEnv,
        AUTH_DISABLED: 'true',
      }),
    ).toThrow('AUTH_DISABLED=true is not allowed in production');
  });
});
