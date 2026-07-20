# UniVoice AI Worker

Python worker responsible for realtime lecture processing after the Core API
starts a session. It subscribes to session events, joins the LiveKit room, and
runs the speech pipeline end to end.

## Pipeline

```text
STT final
-> Segmenter
-> SpeechSegment(segmentId, sequence)
-> segment queue
-> RAG / translation
-> caption.final
-> per-locale TTS queue
-> audio-status
-> LiveKit audio track tts.{locale}
```

## Guarantees

- TTS publishing does not overlap within the same locale.
- Sequence order is preserved per locale.
- `caption.final` is emitted as soon as translation is ready.
- TTS timeout, retry, and dedupe protections are applied.
- Professor audio tracks can detach and reattach without restarting the process.
- Active sessions can be recovered from Redis state on worker restart.
- Session shutdown drains queues before the room is deleted.

## Main Modules

| File | Responsibility |
| --- | --- |
| `main.py` | Redis Pub/Sub entry point and active-session recovery |
| `session_worker.py` | LiveKit room lifecycle and professor track handling |
| `stt.py` | Azure streaming STT adapter |
| `segmenter.py` | Splits final STT text into speech segments |
| `pipeline.py` | Segment queue, translation, caption events, and TTS enqueue |
| `tts_queue.py` | Per-locale bounded TTS queues |
| `tts.py` | Azure TTS wrapper with timeout and retry |
| `audio_publisher.py` | Publishes locale audio tracks to LiveKit |
| `dedupe.py` | Dedupe store for repeated TTS work |
| `worker_status.py` | Redis worker status contract |

## DataChannel Topics

- `stt`
- `caption`
- `audio-status`

Worker status is stored at:

```text
session:{sessionId}:worker:status
```

Supported status values:

- `starting`
- `ready`
- `stopping`
- `stopped`
- `failed`

## Environment Variables

Runtime dependencies:

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

The automated tests use fakes and do not require Azure, OpenAI, LiveKit, or a
running Redis instance.

## Developer Tools

- `tools/student_subscriber.py`: Listen as a student and capture caption/audio output
- `tools/professor_audio_publisher.py`: Publish a professor WAV track into a session
- `tools/local_pipeline_demo.py`: Exercise the pipeline without LiveKit or cloud services

## Manual E2E Checklist

1. Start Redis, the Core API, and the AI worker with real credentials.
2. Start a session from the Core API and confirm worker status becomes `ready`.
3. Join as professor and publish a 16kHz mono WAV file.
4. Join as student and confirm caption and audio events arrive.
5. Verify shared `segmentId` and `sequence` across STT, caption, and audio events.
6. Reconnect the professor client and confirm the worker attaches to the new track.
7. End the session and confirm worker status reaches `stopped` before room deletion.
