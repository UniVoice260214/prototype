import { SetMetadata } from '@nestjs/common';

export type AppRole = 'admin' | 'professor' | 'student';

export const ROLES_KEY = 'roles';

/**
 * Declares which roles may access an endpoint.
 *
 * Example:
 *   @Roles('admin', 'professor')
 */
export const Roles = (...roles: AppRole[]) => SetMetadata(ROLES_KEY, roles);
