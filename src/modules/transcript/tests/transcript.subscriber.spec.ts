jest.mock('bcrypt', () => ({
  compare: jest.fn(),
  hash: jest.fn(),
}));

import { EVENT_CHANNELS } from '../../events/events.types';
import { TranscriptSubscriber } from '../transcript.subscriber';

function makeSubscriber() {
  let onMessage: ((channel: string, raw: string) => void) | undefined;
  const redis = {
    subscribe: jest.fn(() => Promise.resolve(undefined)),
    on: jest.fn((event: string, handler: (c: string, r: string) => void) => {
      if (event === 'message') onMessage = handler;
    }),
  };
  const service = {
    upsertFromEvent: jest.fn(() => Promise.resolve(undefined)),
  };
  const subscriber = new TranscriptSubscriber(redis as never, service as never);
  return {
    subscriber,
    redis,
    service,
    emit: (channel: string, raw: string) => onMessage?.(channel, raw),
  };
}

const VALID = JSON.stringify({
  type: 'transcript.segment',
  sessionId: 'session-1',
  segmentId: 'session-1-seg-000001',
  sequence: 1,
  textKo: '안녕하세요.',
  translations: { 'vi-VN': { text: 'xin chao', isFallback: false } },
  ts: 1700000000,
});

async function flushAsync() {
  await new Promise((resolve) => setImmediate(resolve));
}

describe('TranscriptSubscriber', () => {
  it('subscribes to the transcripts channel on init', async () => {
    const { subscriber, redis } = makeSubscriber();

    await subscriber.onModuleInit();

    expect(redis.subscribe).toHaveBeenCalledWith(
      EVENT_CHANNELS.TRANSCRIPTS_SEGMENT,
    );
  });

  it('persists valid events', async () => {
    const { subscriber, service, emit } = makeSubscriber();
    await subscriber.onModuleInit();

    emit(EVENT_CHANNELS.TRANSCRIPTS_SEGMENT, VALID);
    await flushAsync();

    expect(service.upsertFromEvent).toHaveBeenCalledWith(
      expect.objectContaining({ segmentId: 'session-1-seg-000001' }),
    );
  });

  it('ignores messages from other channels', async () => {
    const { subscriber, service, emit } = makeSubscriber();
    await subscriber.onModuleInit();

    emit('sessions.started', VALID);
    await flushAsync();

    expect(service.upsertFromEvent).not.toHaveBeenCalled();
  });

  it('ignores malformed JSON and incomplete events', async () => {
    const { subscriber, service, emit } = makeSubscriber();
    await subscriber.onModuleInit();

    emit(EVENT_CHANNELS.TRANSCRIPTS_SEGMENT, 'not-json');
    emit(
      EVENT_CHANNELS.TRANSCRIPTS_SEGMENT,
      JSON.stringify({ sessionId: 'session-1' }),
    );
    await flushAsync();

    expect(service.upsertFromEvent).not.toHaveBeenCalled();
  });

  it('survives persistence failures', async () => {
    const { subscriber, service, emit } = makeSubscriber();
    service.upsertFromEvent.mockRejectedValueOnce(new Error('db down'));
    await subscriber.onModuleInit();

    emit(EVENT_CHANNELS.TRANSCRIPTS_SEGMENT, VALID);
    await flushAsync();
    emit(EVENT_CHANNELS.TRANSCRIPTS_SEGMENT, VALID);
    await flushAsync();

    expect(service.upsertFromEvent).toHaveBeenCalledTimes(2);
  });
});
