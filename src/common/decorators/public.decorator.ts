import { SetMetadata } from '@nestjs/common';

export const IS_PUBLIC_KEY = 'isPublic';

/**
 * 글로벌 JwtAuthGuard를 건너뛰는 공개 엔드포인트 표시.
 */
export const Public = () => SetMetadata(IS_PUBLIC_KEY, true);
