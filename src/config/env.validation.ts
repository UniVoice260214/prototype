import { plainToInstance } from 'class-transformer';
import {
  IsEnum,
  IsInt,
  IsOptional,
  IsString,
  validateSync,
} from 'class-validator';

export enum NodeEnv {
  Development = 'development',
  Test = 'test',
  Production = 'production',
}

export class EnvVars {
  @IsInt()
  PORT: number = 3000;

  @IsEnum(NodeEnv)
  NODE_ENV: NodeEnv = NodeEnv.Development;

  @IsString()
  DATABASE_URL!: string;

  @IsString()
  REDIS_URL!: string;

  @IsString()
  JWT_SECRET!: string;

  @IsString()
  @IsOptional()
  JWT_EXPIRES_IN: string = '1d';

  @IsString()
  @IsOptional()
  JWT_JOIN_TOKEN_EXPIRES_IN: string = '24h';

  @IsString()
  @IsOptional()
  LIVEKIT_URL?: string;

  @IsString()
  @IsOptional()
  LIVEKIT_API_KEY?: string;

  @IsString()
  @IsOptional()
  LIVEKIT_API_SECRET?: string;

  @IsString()
  @IsOptional()
  AZURE_BLOB_CONNECTION_STRING?: string;

  @IsString()
  @IsOptional()
  AZURE_BLOB_CONTAINER: string = 'univoice-materials';

  @IsString()
  @IsOptional()
  QR_BASE_URL: string = 'https://app.univoice.example.com/join';

  /** RAG 인덱싱 작업 큐(Redis List) 이름. RAG 워커가 BRPOP으로 소비. */
  @IsString()
  @IsOptional()
  RAG_INDEX_QUEUE: string = 'rag:index:queue';

  @IsInt()
  @IsOptional()
  WORKER_STOP_TIMEOUT_SEC: number = 8;

  @IsInt()
  @IsOptional()
  WORKER_STOP_POLL_INTERVAL_MS: number = 200;

  /**
   * ⚠️ 개발 전용 인증 우회 스위치. 문자열 'true'일 때만 활성화.
   * 활성화 시 JwtAuthGuard/RolesGuard를 건너뛰고 합성 admin 사용자를 주입한다.
   * → 토큰 없이 모든 엔드포인트 호출 가능.
   * 운영(production)에서는 절대 'true'로 두지 말 것.
   * (boolean 대신 string으로 둠: env의 "false"가 Boolean 변환 시 true가 되는 함정 회피)
   */
  @IsOptional()
  @IsString()
  AUTH_DISABLED?: string;
}

export function validateEnv(config: Record<string, unknown>): EnvVars {
  const validated = plainToInstance(EnvVars, config, {
    enableImplicitConversion: true,
  });
  const errors = validateSync(validated, { skipMissingProperties: false });
  if (errors.length > 0) {
    throw new Error(
      `Invalid environment variables:\n${errors
        .map((e) => `  - ${e.property}: ${Object.values(e.constraints ?? {}).join(', ')}`)
        .join('\n')}`,
    );
  }
  return validated;
}
