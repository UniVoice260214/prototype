import { createParamDecorator, ExecutionContext } from '@nestjs/common';

/**
 * JWT payload attached by JwtStrategy.validate().
 */
export interface AuthUser {
  sub: string;
  role?: 'admin' | 'professor' | 'student';
  type: 'user' | 'student' | 'session-join';
  sessionId?: string;
}

export const CurrentUser = createParamDecorator(
  (
    data: keyof AuthUser | undefined,
    ctx: ExecutionContext,
  ): AuthUser | unknown => {
    const request = ctx.switchToHttp().getRequest();
    const user = request.user as AuthUser | undefined;
    if (!user) return undefined;
    return data ? user[data] : user;
  },
);
