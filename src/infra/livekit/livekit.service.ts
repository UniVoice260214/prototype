import {
  Injectable,
  Logger,
  ServiceUnavailableException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import {
  AccessToken,
  DataPacket_Kind,
  RoomServiceClient,
} from 'livekit-server-sdk';

export interface LiveKitTokenOptions {
  identity: string;
  roomName: string;
  /** Whether the participant may publish audio/video tracks. */
  canPublish: boolean;
  /** Whether the participant may subscribe to tracks. */
  canSubscribe: boolean;
  /** Whether the participant may publish data messages. */
  canPublishData?: boolean;
  /** Optional display name. */
  name?: string;
  /** Optional JSON-serializable metadata. */
  metadata?: Record<string, unknown>;
  /** Token TTL in seconds. Defaults to 3600+. */
  ttl?: number;
}

@Injectable()
export class LiveKitService {
  private readonly logger = new Logger(LiveKitService.name);
  private readonly roomService: RoomServiceClient | null;
  private readonly apiKey: string;
  private readonly apiSecret: string;
  private readonly configured: boolean;
  private readonly defaultTokenTtlSec: number;

  constructor(config: ConfigService) {
    const url = config.get<string>('LIVEKIT_URL');
    this.apiKey = config.get<string>('LIVEKIT_API_KEY') ?? '';
    this.apiSecret = config.get<string>('LIVEKIT_API_SECRET') ?? '';
    this.defaultTokenTtlSec = Math.max(
      60,
      config.get<number>('LIVEKIT_TOKEN_TTL_SEC', 4 * 60 * 60),
    );

    if (!url || !this.apiKey || !this.apiSecret) {
      this.logger.warn(
        'LiveKit credentials are missing; room and token APIs will reject requests.',
      );
      this.roomService = null;
      this.configured = false;
      return;
    }

    const httpUrl = url
      .replace(/^wss:\/\//, 'https://')
      .replace(/^ws:\/\//, 'http://');
    this.roomService = new RoomServiceClient(
      httpUrl,
      this.apiKey,
      this.apiSecret,
    );
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
      // Ignore rooms that are already gone.
    }
  }

  /**
   * Broadcasts a JSON data message to every participant in the room via the
   * server API (no participant connection needed). Used for session-level
   * events such as material updates.
   */
  async sendData(
    roomName: string,
    payload: Record<string, unknown>,
    topic: string,
  ): Promise<void> {
    const data = new TextEncoder().encode(JSON.stringify(payload));
    await this.requireConfigured().sendData(
      roomName,
      data,
      DataPacket_Kind.RELIABLE,
      { topic },
    );
  }

  async createAccessToken(opts: LiveKitTokenOptions): Promise<string> {
    if (!this.configured) {
      throw new ServiceUnavailableException('LiveKit is not configured');
    }
    const at = new AccessToken(this.apiKey, this.apiSecret, {
      identity: opts.identity,
      name: opts.name,
      metadata: opts.metadata ? JSON.stringify(opts.metadata) : undefined,
      ttl: opts.ttl ?? this.defaultTokenTtlSec,
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
