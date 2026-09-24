import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Reflector } from '@nestjs/core';
import { AuthUser } from '../decorators/current-user.decorator';
import { AppRole, ROLES_KEY } from '../decorators/roles.decorator';

@Injectable()
export class RolesGuard implements CanActivate {
  constructor(
    private readonly reflector: Reflector,
    private readonly config: ConfigService,
  ) {}

  canActivate(context: ExecutionContext): boolean {
    if (this.config.get<string>('AUTH_DISABLED') === 'true') return true;

    const required = this.reflector.getAllAndOverride<AppRole[] | undefined>(
      ROLES_KEY,
      [context.getHandler(), context.getClass()],
    );
    if (!required || required.length === 0) return true;

    const user = context.switchToHttp().getRequest().user as
      | AuthUser
      | undefined;
    if (!user?.role) throw new ForbiddenException('Role not present in token');

    if (!required.includes(user.role)) {
      throw new ForbiddenException(
        `Required role: ${required.join(', ')}. Got: ${user.role}`,
      );
    }
    return true;
  }
}
