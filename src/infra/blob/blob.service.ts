import {
  Injectable,
  Logger,
  OnModuleInit,
  ServiceUnavailableException,
} from '@nestjs/common';
import { BlobServiceClient, ContainerClient } from '@azure/storage-blob';
import { ConfigService } from '@nestjs/config';
import { v4 as uuid } from 'uuid';

export interface UploadResult {
  blobName: string;
  blobUrl: string;
}

@Injectable()
export class BlobService implements OnModuleInit {
  private readonly logger = new Logger(BlobService.name);
  private container: ContainerClient | null = null;

  constructor(private readonly config: ConfigService) {}

  async onModuleInit(): Promise<void> {
    const conn = this.config.get<string>('AZURE_BLOB_CONNECTION_STRING');
    const containerName = this.config.get<string>(
      'AZURE_BLOB_CONTAINER',
      'univoice-materials',
    );

    if (!conn || conn.length === 0) {
      this.logger.warn(
        'AZURE_BLOB_CONNECTION_STRING is empty; blob uploads will fail until configured.',
      );
      return;
    }

    try {
      const client = BlobServiceClient.fromConnectionString(conn);
      this.container = client.getContainerClient(containerName);
      await this.container.createIfNotExists();
      this.logger.log(`Blob container ready: ${containerName}`);
    } catch (err) {
      this.logger.warn(
        `Blob init failed; uploads will be rejected at runtime: ${(err as Error).message}`,
      );
      this.container = null;
    }
  }

  /**
   * Uploads a file and auto-generates a blob name when needed.
   */
  async upload(
    file: { buffer: Buffer; originalname: string; mimetype: string },
    folder: string = 'materials',
  ): Promise<UploadResult> {
    if (!this.container) {
      throw new ServiceUnavailableException(
        'Azure Blob Storage is not configured',
      );
    }
    const ext = file.originalname.includes('.')
      ? file.originalname.split('.').pop()
      : 'bin';
    const blobName = `${folder}/${uuid()}.${ext}`;
    const block = this.container.getBlockBlobClient(blobName);
    await block.uploadData(file.buffer, {
      blobHTTPHeaders: { blobContentType: file.mimetype },
    });
    return { blobName, blobUrl: block.url };
  }

  async delete(blobName: string): Promise<void> {
    if (!this.container) {
      throw new ServiceUnavailableException(
        'Azure Blob Storage is not configured',
      );
    }
    await this.container.deleteBlob(blobName, {
      deleteSnapshots: 'include',
    });
  }

  /**
   * Derives the blob name from a full blob URL and deletes it.
   */
  async deleteByUrl(blobUrl: string): Promise<void> {
    if (!this.container) return;
    let blobName: string;
    try {
      const path = decodeURIComponent(new URL(blobUrl).pathname);
      const prefix = `/${this.container.containerName}/`;
      blobName = path.startsWith(prefix)
        ? path.slice(prefix.length)
        : path.replace(/^\//, '');
    } catch {
      this.logger.warn(`deleteByUrl: cannot parse blobUrl ${blobUrl}`);
      return;
    }
    await this.container.deleteBlob(blobName, { deleteSnapshots: 'include' });
  }
}
