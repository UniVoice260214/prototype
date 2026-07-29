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

  @IsString()
  @IsOptional()
  HOST: string = '0.0.0.0';

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

  @IsInt()
  @IsOptional()
  LIVEKIT_TOKEN_TTL_SEC: number = 4 * 60 * 60;

  @IsString()
  @IsOptional()
  AZURE_BLOB_CONNECTION_STRING?: string;

  @IsString()
  @IsOptional()
  AZURE_BLOB_CONTAINER: string = 'univoice-materials';

  @IsString()
  @IsOptional()
  QR_BASE_URL: string = 'https://app.univoice.example.com/join';

  /** Redis list name consumed by the RAG worker via BRPOP. */
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
   * Development-only auth bypass.
   * Enabled only when the literal string value is 'true'.
   */
  @IsOptional()
  @IsString()
  AUTH_DISABLED?: string;

  /** Comma-separated browser origins allowed to call the API. */
  @IsOptional()
  @IsString()
  CORS_ORIGINS?: string;

  /** Enable Express proxy awareness when TLS is terminated by Caddy. */
  @IsOptional()
  @IsString()
  TRUST_PROXY?: string;

  /** Swagger is enabled by default outside production. */
  @IsOptional()
  @IsString()
  SWAGGER_ENABLED?: string;
}

export function validateEnv(config: Record<string, unknown>): EnvVars {
  const validated = plainToInstance(EnvVars, config, {
    enableImplicitConversion: true,
  });
  const errors = validateSync(validated, { skipMissingProperties: false });
  if (errors.length > 0) {
    throw new Error(
      `Invalid environment variables:\n${errors
        .map(
          (e) =>
            `  - ${e.property}: ${Object.values(e.constraints ?? {}).join(', ')}`,
        )
        .join('\n')}`,
    );
  }
  if (
    validated.NODE_ENV === NodeEnv.Production &&
    validated.AUTH_DISABLED === 'true'
  ) {
    throw new Error('AUTH_DISABLED=true is not allowed in production');
  }
  if (
    validated.NODE_ENV === NodeEnv.Production &&
    validated.JWT_SECRET.length < 32
  ) {
    throw new Error('JWT_SECRET must be at least 32 characters in production');
  }
  if (
    validated.NODE_ENV === NodeEnv.Production &&
    !validated.QR_BASE_URL.startsWith('https://')
  ) {
    throw new Error('QR_BASE_URL must use https:// in production');
  }
  return validated;
}
