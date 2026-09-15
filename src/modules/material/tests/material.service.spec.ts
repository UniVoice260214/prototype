import { ConflictException } from '@nestjs/common';
import { AuthUser } from '../../../common/decorators/current-user.decorator';
import { MATERIALS_DATA_TOPIC, MaterialService } from '../material.service';

const PROFESSOR: AuthUser = { sub: 'user-1', role: 'professor', type: 'user' };

function makeFile(name: string, mimetype: string) {
  return {
    buffer: Buffer.from('bytes'),
    originalname: name,
    mimetype,
    size: 5,
  };
}

function makeService(options: {
  converted?: Buffer | null;
  material?: Record<string, unknown> | null;
  materials?: Record<string, unknown>[];
  activeSessions?: Record<string, unknown>[];
}) {
  const repo = {
    create: jest.fn((entity) => entity),
    save: jest.fn(async (entity) => ({
      id: 'material-1',
      createdAt: new Date('2026-01-01T00:00:00.000Z'),
      ...entity,
    })),
    update: jest.fn(async () => ({ affected: 1 })),
    find: jest.fn(async () => options.materials ?? []),
    findOne: jest.fn(async () => options.material ?? null),
    delete: jest.fn(),
  };
  const sessions = {
    find: jest.fn(
      async () => options.activeSessions ?? [{ liveKitRoomName: 'room-1' }],
    ),
  };
  const redis = { lpush: jest.fn() };
  const blob = {
    upload: jest.fn(async (_file, folder: string) => ({
      blobName: `${folder}/x`,
      blobUrl: `http://blob/${folder}/x`,
    })),
    deleteByUrl: jest.fn(),
    download: jest.fn(async () => ({
      stream: {},
      contentType: 'application/pdf',
      contentLength: 5,
    })),
  };
  const events = { publishMaterialIndexingRequested: jest.fn() };
  const courseAccess = {
    findCourseForUser: jest.fn(),
    findSessionForUser: jest.fn(),
    findMaterialForUser: jest.fn(async () => options.material),
  };
  const studentAccess = {
    findSessionForStudent: jest.fn(async () => ({
      id: 'session-1',
      courseId: 'course-1',
    })),
  };
  const preview = {
    isPdf: jest.fn((file) => file.mimetype === 'application/pdf'),
    convertToPdf: jest.fn(async () => options.converted ?? null),
  };
  const liveKit = { sendData: jest.fn(async () => undefined) };
  const config = {
    get: jest.fn((_key: string, fallback?: unknown) => fallback),
  };

  const service = new MaterialService(
    repo as any,
    sessions as any,
    redis as any,
    blob as any,
    events as any,
    courseAccess as any,
    studentAccess as any,
    preview as any,
    liveKit as any,
    config as any,
  );
  return { service, repo, sessions, blob, preview, liveKit, studentAccess };
}

/** 응답 뒤에 이어지는 비동기 변환(void promise)이 끝날 때까지 돌린다. */
async function flush(times = 5) {
  for (let i = 0; i < times; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

describe('MaterialService preview pipeline', () => {
  const dto = { courseId: 'course-1', sourceType: 'lecture' as const };

  it('marks PDF uploads as ready immediately and notifies active rooms', async () => {
    const { service, blob, preview, liveKit } = makeService({});
    const material = await service.upload(
      makeFile('week1.pdf', 'application/pdf'),
      dto,
      PROFESSOR,
    );

    expect(material.previewStatus).toBe('ready');
    expect(material.previewBlobUrl).toBe(material.blobUrl);
    expect(preview.convertToPdf).not.toHaveBeenCalled();
    expect(blob.upload).toHaveBeenCalledTimes(1);
    expect(liveKit.sendData).toHaveBeenCalledWith(
      'room-1',
      expect.objectContaining({
        type: 'material.uploaded',
        material: expect.objectContaining({
          id: 'material-1',
          previewStatus: 'ready',
        }),
      }),
      MATERIALS_DATA_TOPIC,
    );
    // 학생 뷰에는 blobUrl 을 노출하지 않는다.
    const [, payload] = (liveKit.sendData.mock.calls as unknown[][])[0];
    expect((payload as { material: object }).material).not.toHaveProperty(
      'blobUrl',
    );
  });

  it('converts PPT to PDF after responding and announces the ready preview', async () => {
    const { service, repo, blob, liveKit } = makeService({
      converted: Buffer.from('%PDF'),
    });
    const material = await service.upload(
      makeFile(
        'week2.pptx',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      ),
      dto,
      PROFESSOR,
    );
    expect(material.previewStatus).toBe('pending');
    expect(material.previewBlobUrl).toBeNull();

    await flush();

    expect(blob.upload).toHaveBeenLastCalledWith(
      expect.objectContaining({
        originalname: 'week2.pdf',
        mimetype: 'application/pdf',
      }),
      'previews',
    );
    expect(repo.update).toHaveBeenCalledWith('material-1', {
      previewBlobUrl: 'http://blob/previews/x',
      previewStatus: 'ready',
    });
    expect(liveKit.sendData).toHaveBeenLastCalledWith(
      'room-1',
      expect.objectContaining({
        type: 'material.updated',
        material: expect.objectContaining({ previewStatus: 'ready' }),
      }),
      MATERIALS_DATA_TOPIC,
    );
  });

  it('marks the preview failed when no converter produced a PDF', async () => {
    const { service, repo, blob } = makeService({ converted: null });
    await service.upload(
      makeFile('week3.ppt', 'application/vnd.ms-powerpoint'),
      dto,
      PROFESSOR,
    );
    await flush();

    expect(blob.upload).toHaveBeenCalledTimes(1);
    expect(repo.update).toHaveBeenCalledWith('material-1', {
      previewBlobUrl: null,
      previewStatus: 'failed',
    });
  });

  it('discards the converted preview when the material was deleted meanwhile', async () => {
    const { service, repo, blob, liveKit } = makeService({
      converted: Buffer.from('%PDF'),
    });
    repo.update.mockResolvedValueOnce({ affected: 0 });
    await service.upload(
      makeFile('gone.pptx', 'application/vnd.ms-powerpoint'),
      dto,
      PROFESSOR,
    );
    await flush();

    expect(blob.deleteByUrl).toHaveBeenCalledWith('http://blob/previews/x');
    expect(liveKit.sendData).toHaveBeenCalledTimes(1); // uploaded 만, updated 없음
  });

  it('does not fail the upload when the room broadcast throws', async () => {
    const { service, liveKit } = makeService({});
    liveKit.sendData.mockRejectedValueOnce(new Error('livekit down'));
    await expect(
      service.upload(makeFile('a.pdf', 'application/pdf'), dto, PROFESSOR),
    ).resolves.toMatchObject({ previewStatus: 'ready' });
  });
});

describe('MaterialService student access', () => {
  it('lists course materials as student views', async () => {
    const { service, repo, studentAccess } = makeService({
      materials: [
        {
          id: 'm-1',
          courseId: 'course-1',
          blobUrl: 'http://blob/materials/x',
          originalFilename: 'a.pdf',
          sourceType: 'lecture',
          week: 1,
          previewStatus: 'ready',
          previewBlobUrl: 'http://blob/materials/x',
          createdAt: new Date('2026-01-01T00:00:00.000Z'),
        },
      ],
    });
    const rows = await service.listForStudent(
      'session-1',
      { joinToken: 'jt' },
      null,
    );

    expect(studentAccess.findSessionForStudent).toHaveBeenCalledWith(
      'session-1',
      'jt',
      null,
    );
    // 강의안만, 이 세션에 올린 것 + 세션 미지정(사전 업로드). 전공 자료는 제외.
    expect(repo.find).toHaveBeenCalledWith({
      where: [
        { courseId: 'course-1', sourceType: 'lecture', sessionId: 'session-1' },
        {
          courseId: 'course-1',
          sourceType: 'lecture',
          sessionId: expect.objectContaining({ _type: 'isNull' }),
        },
      ],
      order: { createdAt: 'ASC' },
    });
    expect(rows).toEqual([
      expect.objectContaining({
        id: 'm-1',
        originalFilename: 'a.pdf',
        previewStatus: 'ready',
      }),
    ]);
    expect(rows[0]).not.toHaveProperty('blobUrl');
  });

  it('refuses to stream a material whose preview is not ready', async () => {
    const { service } = makeService({
      material: { id: 'm-1', previewStatus: 'pending', previewBlobUrl: null },
    });
    await expect(
      service.streamForStudent('session-1', 'm-1', { joinToken: 'jt' }, null),
    ).rejects.toBeInstanceOf(ConflictException);
  });

  it('streams the preview PDF with a .pdf filename', async () => {
    const { service, blob } = makeService({
      material: {
        id: 'm-1',
        originalFilename: '3주차 강의.pptx',
        previewStatus: 'ready',
        previewBlobUrl: 'http://blob/previews/x',
      },
    });
    const result = await service.streamForStudent(
      'session-1',
      'm-1',
      {},
      'student-1',
    );

    expect(blob.download).toHaveBeenCalledWith('http://blob/previews/x');
    expect(result.filename).toBe('3주차 강의.pdf');
    expect(result.contentType).toBe('application/pdf');
  });
});
