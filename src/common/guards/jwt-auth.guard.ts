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
import { AuthUser } from '../decorators/current-user.decorator';
import { IS_PUBLIC_KEY } from '../decorators/public.decorator';

/**
 * Synthetic user injected only when AUTH_DISABLED=true for local development.
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
    if (this.config.get<string>('AUTH_DISABLED') === 'true') {
      if (!this.warned) {
        this.logger.warn(
          'AUTH_DISABLED=true: authentication is bypassed for development.',
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
    return user;
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
