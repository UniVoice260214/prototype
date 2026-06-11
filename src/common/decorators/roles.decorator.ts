import { SetMetadata } from '@nestjs/common';

export type AppRole = 'admin' | 'professor' | 'student';

export const ROLES_KEY = 'roles';

/**
 * 엔드포인트에 허용된 역할 지정. RolesGuard와 함께 사용.
 *
 * 예: @Roles('admin', 'professor')
 */
export const Roles = (...roles: AppRole[]) => SetMetadata(ROLES_KEY, roles);
