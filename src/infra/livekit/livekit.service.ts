import {
  Injectable,
  Logger,
  ServiceUnavailableException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { AccessToken, RoomServiceClient } from 'livekit-server-sdk';

export interface LiveKitTokenOptions {
  identity: string;
  roomName: string;
  /** 발화/track publish 가능 여부 */
  canPublish: boolean;
  /** track subscribe 가능 여부 */
  canSubscribe: boolean;
  /** DataChannel publish 가능 여부 */
  canPublishData?: boolean;
  /** 표시 이름 */
  name?: string;
  /** 추가 metadata (JSON 직렬화 가능) */
  metadata?: Record<string, unknown>;
  /** access token TTL (초). 기본 3600. */
  ttl?: number;
}

@Injectable()
export class LiveKitService {
  private readonly logger = new Logger(LiveKitService.name);
  private readonly roomService: RoomServiceClient | null;
  private readonly apiKey: string;
  private readonly apiSecret: string;
  private readonly configured: boolean;

  constructor(config: ConfigService) {
    const url = config.get<string>('LIVEKIT_URL');
    this.apiKey = config.get<string>('LIVEKIT_API_KEY') ?? '';
    this.apiSecret = config.get<string>('LIVEKIT_API_SECRET') ?? '';

    if (!url || !this.apiKey || !this.apiSecret) {
      this.logger.warn(
        'LiveKit credentials missing — session token/room APIs will be rejected at runtime.',
      );
      this.roomService = null;
      this.configured = false;
      return;
    }

    const httpUrl = url
      .replace(/^wss:\/\//, 'https://')
      .replace(/^ws:\/\//, 'http://');
    this.roomService = new RoomServiceClient(httpUrl, this.apiKey, this.apiSecret);
    this.configured = true;
  }

  private requireConfigured(): RoomServiceClient {
    if (!this.configured || !this.roomService) {
      throw new ServiceUnavailableException('LiveKit is not configured');
    }
    return this.roomService;
  }

  async createRoom(roomName: string): Promise<void> {
    await this.requireConfigured().createRoom({ name: roomName });
  }

  async deleteRoom(roomName: string): Promise<void> {
    if (!this.configured || !this.roomService) return;
    try {
      await this.roomService.deleteRoom(roomName);
    } catch {
      // already gone — ignore
    }
  }

  async createAccessToken(opts: LiveKitTokenOptions): Promise<string> {
    if (!this.configured) {
      throw new ServiceUnavailableException('LiveKit is not configured');
    }
    const at = new AccessToken(this.apiKey, this.apiSecret, {
      identity: opts.identity,
      name: opts.name,
      metadata: opts.metadata ? JSON.stringify(opts.metadata) : undefined,
      ttl: opts.ttl ?? 3600,
    });
    at.addGrant({
      room: opts.roomName,
      roomJoin: true,
      canPublish: opts.canPublish,
      canSubscribe: opts.canSubscribe,
      canPublishData: opts.canPublishData ?? false,
    });
    return at.toJwt();
  }
}
