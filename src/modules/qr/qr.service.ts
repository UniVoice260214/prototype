import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import * as QRCode from 'qrcode';
import { CourseAccessService } from '../../common/access/course-access.service';
import { AuthUser } from '../../common/decorators/current-user.decorator';
import { AuthService } from '../auth/auth.service';

export interface QrPayload {
  /** Data URL (image/png base64) */
  qrImage: string;
  /** 클라이언트에서 직접 사용할 수 있도록 함께 반환 */
  joinUrl: string;
  joinToken: string;
  sessionId: string;
  expiresIn: string;
}

@Injectable()
export class QrService {
  constructor(
    private readonly auth: AuthService,
    private readonly config: ConfigService,
    private readonly courseAccess: CourseAccessService,
  ) {}

  async generateForSession(
    sessionId: string,
    user: AuthUser,
  ): Promise<QrPayload> {
    const session = await this.courseAccess.findSessionForUser(sessionId, user);

    const joinToken = await this.auth.signJoinToken(session.id, 'guest');
    const base = this.config.getOrThrow<string>('QR_BASE_URL');
    const joinUrl = `${base}?token=${encodeURIComponent(joinToken)}`;
    const qrImage = await QRCode.toDataURL(joinUrl, {
      errorCorrectionLevel: 'M',
      margin: 1,
      width: 512,
    });
    return {
      qrImage,
      joinUrl,
      joinToken,
      sessionId: session.id,
      expiresIn: this.config.get<string>('JWT_JOIN_TOKEN_EXPIRES_IN', '24h'),
    };
  }
}
