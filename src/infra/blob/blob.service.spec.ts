import { ConfigService } from '@nestjs/config';
import { BlobServiceClient } from '@azure/storage-blob';
import { BlobService } from './blob.service';

describe('BlobService demo public URLs', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('enables blob-only anonymous reads for an existing demo container', async () => {
    const createIfNotExists = jest.fn().mockResolvedValue({ succeeded: false });
    const setAccessPolicy = jest.fn().mockResolvedValue(undefined);
    jest.spyOn(BlobServiceClient, 'fromConnectionString').mockReturnValue({
      getContainerClient: jest.fn().mockReturnValue({
        createIfNotExists,
        setAccessPolicy,
      }),
    } as unknown as BlobServiceClient);
    const service = new BlobService(
      new ConfigService({
        AZURE_BLOB_CONNECTION_STRING: 'UseDevelopmentStorage=true',
        AZURE_BLOB_CONTAINER: 'univoice-materials',
        AZURE_BLOB_PUBLIC_ACCESS: 'true',
      }),
    );

    await service.onModuleInit();

    expect(createIfNotExists).toHaveBeenCalledWith({ access: 'blob' });
    expect(setAccessPolicy).toHaveBeenCalledWith('blob');
  });

  it('returns the configured public base URL after upload', async () => {
    const uploadData = jest.fn().mockResolvedValue(undefined);
    const service = new BlobService(new ConfigService());

    (service as unknown as { publicBaseUrl: string }).publicBaseUrl =
      'https://demo.example.ts.net:8443/devstoreaccount1/univoice-materials';
    (service as unknown as { container: unknown }).container = {
      getBlockBlobClient: jest.fn().mockReturnValue({
        url: 'http://azurite:10000/devstoreaccount1/univoice-materials/internal.pdf',
        uploadData,
      }),
    };

    const result = await service.upload({
      buffer: Buffer.from('pdf'),
      originalname: 'lecture.pdf',
      mimetype: 'application/pdf',
    });

    expect(uploadData).toHaveBeenCalled();
    expect(result.blobUrl).toMatch(
      /^https:\/\/demo\.example\.ts\.net:8443\/devstoreaccount1\/univoice-materials\/materials\/.+\.pdf$/,
    );
  });

  it('percent-encodes each public blob URL path segment', async () => {
    const service = new BlobService(new ConfigService());
    (service as unknown as { publicBaseUrl: string }).publicBaseUrl =
      'https://demo.example.ts.net:8443/devstoreaccount1/univoice-materials';
    (service as unknown as { container: unknown }).container = {
      getBlockBlobClient: jest.fn().mockReturnValue({
        url: 'http://azurite/internal.pdf',
        uploadData: jest.fn().mockResolvedValue(undefined),
      }),
    };

    const result = await service.upload(
      {
        buffer: Buffer.from('pdf'),
        originalname: 'lecture.pdf',
        mimetype: 'application/pdf',
      },
      'course #1',
    );

    expect(result.blobUrl).toContain('/course%20%231/');
    expect(new URL(result.blobUrl).hash).toBe('');
  });

  it('deletes a blob whose public URL includes the Azurite account path', async () => {
    const deleteBlob = jest.fn().mockResolvedValue(undefined);
    const service = new BlobService(new ConfigService());
    (service as unknown as { container: unknown }).container = {
      containerName: 'univoice-materials',
      deleteBlob,
    };

    await service.deleteByUrl(
      'https://demo.example.ts.net:8443/devstoreaccount1/univoice-materials/materials/file.pdf',
    );

    expect(deleteBlob).toHaveBeenCalledWith('materials/file.pdf', {
      deleteSnapshots: 'include',
    });
  });

  it('does not delete when the configured container is absent from the URL', async () => {
    const deleteBlob = jest.fn().mockResolvedValue(undefined);
    const service = new BlobService(new ConfigService());
    (service as unknown as { container: unknown }).container = {
      containerName: 'univoice-materials',
      deleteBlob,
    };

    await service.deleteByUrl(
      'https://demo.example.ts.net:8443/devstoreaccount1/other-container/materials/file.pdf',
    );

    expect(deleteBlob).not.toHaveBeenCalled();
  });
});
