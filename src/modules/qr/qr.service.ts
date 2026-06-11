import { Injectable, NotFoundException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import * as QRCode from 'qrcode';
import { AuthService } from '../auth/auth.service';
import { Session } from '../session/entities/session.entity';

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
    @InjectRepository(Session) private readonly sessions: Repository<Session>,
    private readonly auth: AuthService,
    private readonly config: ConfigService,
  ) {}

  async generateForSession(sessionId: string): Promise<QrPayload> {
    const session = await this.sessions.findOne({ where: { id: sessionId } });
    if (!session) throw new NotFoundException(`Session ${sessionId} not found`);

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
