import { TypeOrmModuleAsyncOptions } from '@nestjs/typeorm';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { join } from 'path';

export const typeOrmAsyncConfig: TypeOrmModuleAsyncOptions = {
  imports: [ConfigModule],
  inject: [ConfigService],
  useFactory: (config: ConfigService) => {
    const isCompiled = __filename.endsWith('.js');
    const ext = isCompiled ? 'js' : 'ts';
    const rootDir = isCompiled ? 'dist' : 'src';

    return {
      type: 'postgres',
      url: config.getOrThrow<string>('DATABASE_URL'),
      entities: [join(process.cwd(), rootDir, `**/*.entity.${ext}`)],
      migrations: [join(process.cwd(), rootDir, `migrations/*.${ext}`)],
      synchronize: false,
      autoLoadEntities: false,
      migrationsRun: false,
      logging:
        config.get<string>('NODE_ENV') === 'development'
          ? ['error', 'warn']
          : ['error'],
    };
  },
};
