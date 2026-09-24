import {
  Controller,
  Get,
  Inject,
  Logger,
  ServiceUnavailableException,
} from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import type Redis from 'ioredis';
import { DataSource } from 'typeorm';
import { Public } from '../../common/decorators/public.decorator';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';

@ApiTags('health')
@Controller('health')
export class HealthController {
  private readonly logger = new Logger(HealthController.name);

  constructor(
    private readonly dataSource: DataSource,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
  ) {}

  @Public()
  @Get('live')
  @ApiOperation({ summary: 'Process liveness probe' })
  live() {
    return {
      status: 'ok',
      timestamp: new Date().toISOString(),
    };
  }

  @Public()
  @Get('ready')
  @ApiOperation({ summary: 'Database and Redis readiness probe' })
  async ready() {
    try {
      await Promise.all([this.dataSource.query('SELECT 1'), this.redis.ping()]);
      return {
        status: 'ok',
        checks: {
          database: 'up',
          redis: 'up',
        },
        timestamp: new Date().toISOString(),
      };
    } catch (error) {
      this.logger.warn(
        `Readiness check failed: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      throw new ServiceUnavailableException('Dependencies are not ready');
    }
  }
}
