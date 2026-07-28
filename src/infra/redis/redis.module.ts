import { Global, Inject, Module, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';

export const REDIS_CLIENT = 'REDIS_CLIENT';
export const REDIS_SUBSCRIBER = 'REDIS_SUBSCRIBER';

@Global()
@Module({
  providers: [
    {
      provide: REDIS_CLIENT,
      useFactory: (config: ConfigService) => {
        return new Redis(config.getOrThrow<string>('REDIS_URL'), {
          maxRetriesPerRequest: 3,
          lazyConnect: false,
        });
      },
      inject: [ConfigService],
    },
    {
      provide: REDIS_SUBSCRIBER,
      useFactory: (config: ConfigService) => {
        return new Redis(config.getOrThrow<string>('REDIS_URL'), {
          maxRetriesPerRequest: null, // required for subscriber mode
          lazyConnect: false,
        });
      },
      inject: [ConfigService],
    },
  ],
  exports: [REDIS_CLIENT, REDIS_SUBSCRIBER],
})
export class RedisModule implements OnModuleDestroy {
  constructor(
    @Inject(REDIS_CLIENT) private readonly client: Redis,
    @Inject(REDIS_SUBSCRIBER) private readonly subscriber: Redis,
  ) {}

  async onModuleDestroy() {
    await Promise.allSettled([this.subscriber.quit(), this.client.quit()]);
  }
}
