import {
  ExecutionContext,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Reflector } from '@nestjs/core';
import { AuthGuard } from '@nestjs/passport';
import { Request } from 'express';
import { IS_PUBLIC_KEY } from '../decorators/public.decorator';
import { AuthUser } from '../decorators/current-user.decorator';

/**
 * 개발용 인증 우회 시 주입되는 합성 사용자.
 * role=admin 이므로 RolesGuard와 무관하게 모든 엔드포인트 접근 가능.
 */
const DEV_USER: AuthUser = {
  sub: 'dev-admin',
  role: 'admin',
  type: 'user',
};

@Injectable()
export class JwtAuthGuard extends AuthGuard('jwt') {
  private readonly logger = new Logger(JwtAuthGuard.name);
  private warned = false;

  constructor(
    private readonly reflector: Reflector,
    private readonly config: ConfigService,
  ) {
    super();
  }

  canActivate(context: ExecutionContext) {
    // 개발 전용: AUTH_DISABLED=true 면 인증을 건너뛰고 합성 admin 주입
    if (this.config.get<string>('AUTH_DISABLED') === 'true') {
      if (!this.warned) {
        this.logger.warn(
          '⚠️  AUTH_DISABLED=true — 인증이 비활성화되어 있습니다. (개발 전용)',
        );
        this.warned = true;
      }
      const req = context.switchToHttp().getRequest();
      if (!req.user) req.user = DEV_USER;
      return true;
    }

    const isPublic = this.isPublic(context);
    if (isPublic && !this.hasBearerToken(context)) return true;
    return super.canActivate(context);
  }

  handleRequest<TUser = AuthUser>(
    err: unknown,
    user: TUser | false | null | undefined,
    _info: unknown,
    context: ExecutionContext,
    _status?: unknown,
  ): TUser {
    if (this.isPublic(context)) {
      return (user || undefined) as TUser;
    }
    if (err || !user) {
      throw err instanceof Error ? err : new UnauthorizedException();
    }
    return user as TUser;
  }

  private isPublic(context: ExecutionContext): boolean {
    return (
      this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
        context.getHandler(),
        context.getClass(),
      ]) ?? false
    );
  }

  private hasBearerToken(context: ExecutionContext): boolean {
    const req = context.switchToHttp().getRequest<Request>();
    const authorization = req.headers.authorization;
    return (
      typeof authorization === 'string' && /^bearer\s+\S+/i.test(authorization)
    );
  }
}
