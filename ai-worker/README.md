# UniVoice AI Worker

Python AI Worker는 교수 음성을 받아 STT, segmentation, translation, TTS, LiveKit delivery를 처리한다. Core API는 세션 제어와 Redis 이벤트를 담당하고, 실제 음성 파이프라인은 이 워커가 담당한다.

## Architecture

```text
STT final
-> Segmenter
-> SpeechSegment(segmentId, sequence)
-> segment queue
-> RAG/Translator
-> caption.final
-> locale별 TTS queue
-> audio-status
-> LiveKit audio track tts.{locale}
```

주요 보장:

- 같은 locale의 TTS publish는 겹치지 않는다.
- locale별 sequence 순서가 유지된다.
- caption.final은 TTS 완료를 기다리지 않고 번역 직후 전송된다.
- TTS timeout/retry/dedupe가 적용된다.
- 교수 track detach 후 새 track attach가 가능하다.
- AI Worker 재시작 시 Redis active session을 SCAN으로 복구한다.
- session end 시 room 삭제 전에 queue drain 기회를 가진다.

## Modules

| File | Role |
| --- | --- |
| `main.py` | Redis Pub/Sub 구독, active session 복구, session worker registry |
| `session_worker.py` | LiveKit room lifecycle, professor track attach/detach, STT reconnect |
| `stt.py` | Azure streaming STT adapter, typed STT error classification |
| `segmenter.py` | STT final text -> SpeechSegment draft |
| `pipeline.py` | segment queue, RAG/translation, caption/TTS queue enqueue |
| `tts_queue.py` | per-locale bounded TTS queues and audio-status events |
| `tts.py` | Azure TTS timeout/retry/concurrency wrapper |
| `audio_publisher.py` | locale audio tracks, per-locale publish lock, PCM frame padding |
| `dedupe.py` | in-memory/Redis TTS dedupe stores |
| `worker_status.py` | Redis worker status payload contract |

## Event Contract

DataChannel topics:

- `stt`
- `caption`
- `audio-status`

Payload examples:

```json
{
  "type": "stt.final",
  "sessionId": "session-123",
  "segmentId": "session-123-seg-000001",
  "sequence": 1,
  "lang": "ko-KR",
  "text": "안녕하세요.",
  "ts": 0
}
```

```json
{
  "type": "caption.final",
  "sessionId": "session-123",
  "segmentId": "session-123-seg-000001",
  "sequence": 1,
  "locale": "vi-VN",
  "text": "Xin chào.",
  "sourceKo": "안녕하세요.",
  "ts": 0
}
```

```json
{
  "type": "audio.completed",
  "sessionId": "session-123",
  "segmentId": "session-123-seg-000001",
  "sequence": 1,
  "locale": "vi-VN",
  "durationMs": 2300,
  "errorCode": null,
  "ts": 0
}
```

Required identity fields:

- `sessionId`
- `segmentId` and `sequence` for final STT, caption, and audio-status events
- `locale` for translated caption/audio events or `lang` for Korean STT events
- `text` for text events
- `ts`

Audio status types:

- `audio.started`
- `audio.completed`
- `audio.failed`

## Worker Status

Redis key:

```text
session:{sessionId}:worker:status
```

Payload:

```json
{ "status": "ready", "ts": 0, "error": "optional message" }
```

States:

- `starting`
- `ready`
- `stopping`
- `stopped`
- `failed`

The key uses `WORKER_STATUS_TTL_SEC`.

## Graceful Shutdown

Core API session end order:

1. Set Redis `session:{id}:status` to `ending`
2. Publish `sessions.ended`
3. Python worker sets worker status `stopping`
4. Stop STT and block reconnect
5. Flush Segmenter
6. Drain segment queue
7. Drain locale TTS queues
8. Close audio publisher
9. Set worker status `stopped`
10. Core API polls worker status
11. Delete LiveKit room
12. Save DB session as `ended` with `endedAt`
13. Clean Redis session config/status/worker status

Timeout still proceeds with room deletion and DB end.

## Active Session Recovery

On startup, `main.py` scans Redis with `SCAN` over `session:*:status`, reads `active` sessions, validates `session:{id}:config`, and reuses the normal `start_session` path. Invalid JSON, missing fields, empty locales, and unknown locale configs are skipped per session without stopping the worker loop.

## Environment Variables

Core/runtime:

- `REDIS_URL`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `AZURE_SPEECH_KEY`
- `AZURE_SPEECH_REGION`
- `STT_LANGUAGE`
- `TRANSLATE_PROVIDER`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION`

Pipeline tuning:

- `SEGMENT_MAX_CHARS`
- `SEGMENT_IDLE_FLUSH_MS`
- `SEGMENT_MIN_CHARS`
- `SEGMENT_QUEUE_MAX_SIZE`
- `SEGMENT_ENQUEUE_TIMEOUT_MS`
- `TTS_TIMEOUT_SEC`
- `TTS_MAX_RETRIES`
- `TTS_RETRY_BASE_DELAY_MS`
- `TTS_MAX_CONCURRENCY`
- `TTS_QUEUE_MAX_SIZE`
- `TTS_DEDUPE_TTL_SEC`
- `TTS_FAILED_DEDUPE_TTL_SEC`
- `STT_MAX_RECONNECTS`
- `STT_RECONNECT_BASE_DELAY_MS`
- `WORKER_STATUS_TTL_SEC`

Core API shutdown tuning:

- `WORKER_STOP_TIMEOUT_SEC`
- `WORKER_STOP_POLL_INTERVAL_MS`

## Install And Test

```bash
cd ai-worker
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m compileall univoice_worker
python -m pytest -q
```

The automated Python tests use fakes and do not require Azure, OpenAI, LiveKit, or a Redis server.

Core API:

```bash
cd ..
npm install
npm run build
npm test -- --runInBand
```

## Developer Tools

### Student Subscriber

Subscribe as a student, print selected locale captions/audio status, and optionally save received audio.

```bash
cd ai-worker
python tools/student_subscriber.py \
  --url wss://your-livekit.example \
  --token STUDENT_TOKEN \
  --locale vi-VN \
  --output-dir ./captures \
  --duration 60
```

It listens for:

- audio track `tts.{locale}`
- `caption` topic for the selected locale
- `audio-status` topic for the selected locale

### Professor WAV Publisher

Publish a professor audio track from a WAV file.

```bash
cd ai-worker
python tools/professor_audio_publisher.py \
  --url wss://your-livekit.example \
  --token PROFESSOR_TOKEN \
  --wav ./samples/professor.wav
```

WAV requirements:

- 16000 Hz
- 16-bit PCM
- mono

Unsupported formats are rejected clearly. No audio conversion library is added; keeping this tool dependency-free makes failures explicit.

### Local Pipeline Demo

Run the pipeline without LiveKit/Azure/OpenAI:

```bash
cd ai-worker
python tools/local_pipeline_demo.py --text "안녕하세요." --locales vi-VN,zh-CN
```

This uses fake translator/TTS and prints STT, caption, and audio-status events.

## Fake Tests vs Real E2E

Mock unit/integration tests verify:

- Segmenter splitting/flush/confidence behavior
- segment ordering and queue drain
- caption-before-TTS delivery
- TTS queue ordering/concurrency/retry/dedupe
- audio publisher frame padding/locking/errors
- professor track reconnect and STT reconnect policy
- active session recovery and malformed Pub/Sub isolation
- Core API graceful end ordering

They do not prove:

- Real Azure STT recognition quality
- Real Azure TTS voice availability and cancellation detail mapping
- Real LiveKit publish/subscribe timing
- Browser microphone permission or refresh behavior

## Manual E2E Checklist

1. Start Redis/Core API/AI worker with real credentials.
2. Start a session from Core API and confirm worker status `ready`.
3. Join as professor and publish a 16kHz mono WAV with `professor_audio_publisher.py`.
4. Join as student with `student_subscriber.py`.
5. Confirm `stt.final`, `caption.final`, `audio.started`, `audio.completed` share `segmentId`/`sequence`.
6. Refresh or reconnect professor client and confirm a new audio track attaches.
7. End the session and confirm worker status reaches `stopped` before room deletion.

## Known Limitations

- The professor WAV publisher rejects non-16kHz/16-bit/mono files instead of converting.
- Real Azure/LiveKit E2E requires valid credentials and tokens from the Core API.
- Distributed worker locking is intentionally out of scope for this phase.
