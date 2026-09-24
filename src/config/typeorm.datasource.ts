import 'reflect-metadata';
import { config as loadEnv } from 'dotenv';
import { DataSource } from 'typeorm';
import { join } from 'path';

loadEnv();

const isCompiled = __filename.endsWith('.js');
const ext = isCompiled ? 'js' : 'ts';
const rootDir = isCompiled ? 'dist' : 'src';

/**
 * Used by:
 *  - typeorm CLI for generating/running migrations
 *  - TypeOrmModule.forRoot (via shared options)
 */
export const dataSource = new DataSource({
  type: 'postgres',
  url: process.env.DATABASE_URL,
  entities: [join(process.cwd(), rootDir, `**/*.entity.${ext}`)],
  migrations: [join(process.cwd(), rootDir, `migrations/*.${ext}`)],
  synchronize: false,
  logging:
    process.env.NODE_ENV === 'development' ? ['error', 'warn'] : ['error'],
});
