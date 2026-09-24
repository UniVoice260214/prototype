from __future__ import annotations

import argparse
import asyncio
import sys
import time
import wave
from pathlib import Path
from typing import Any

try:
    from livekit import rtc
except ImportError:  # pragma: no cover - runtime dependency
    rtc = None  # type: ignore[assignment]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_RATE = 16000
NUM_CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
FRAME_DURATION_SEC = 0.01
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_SEC)
FRAME_BYTES = FRAME_SAMPLES * NUM_CHANNELS * SAMPLE_WIDTH_BYTES


def validate_wav(path: Path) -> tuple[bytes, int]:
    if not path.exists():
        raise ValueError(f"WAV file does not exist: {path}")
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.getnframes()
        if channels != NUM_CHANNELS or sample_width != SAMPLE_WIDTH_BYTES or sample_rate != SAMPLE_RATE:
            raise ValueError(
                "unsupported WAV format; expected 16kHz, 16-bit, mono PCM "
                f"(got {sample_rate}Hz, {sample_width * 8}-bit, {channels} channel(s))"
            )
        return wav.readframes(frames), frames


async def publish_pcm(source: Any, pcm: bytes, *, realtime: bool) -> None:
    start = time.monotonic()
    frame_index = 0
    for offset in range(0, len(pcm), FRAME_BYTES):
        chunk = pcm[offset : offset + FRAME_BYTES]
        if len(chunk) < FRAME_BYTES:
            chunk += bytes(FRAME_BYTES - len(chunk))
        frame = rtc.AudioFrame(
            data=chunk,
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            samples_per_channel=FRAME_SAMPLES,
        )
        await source.capture_frame(frame)
        frame_index += 1
        if realtime:
            target = start + frame_index * FRAME_DURATION_SEC
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)


async def run(args: argparse.Namespace) -> int:
    if rtc is None:
        print("LiveKit SDK is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 2
    try:
        pcm, sample_count = validate_wav(Path(args.wav))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    room = rtc.Room()
    source = rtc.AudioSource(SAMPLE_RATE, NUM_CHANNELS)
    track = rtc.LocalAudioTrack.create_audio_track("professor.mic", source)
    publication = None
    try:
        await room.connect(args.url, args.token)
        publication = await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        print(f"published professor.mic ({sample_count / SAMPLE_RATE:.2f}s)")
        while True:
            await publish_pcm(source, pcm, realtime=args.realtime)
            if not args.loop:
                break
    except KeyboardInterrupt:
        print("interrupted")
    except Exception as exc:  # noqa: BLE001
        print(f"failed to publish professor audio: {exc}", file=sys.stderr)
        return 1
    finally:
        unpublish = getattr(room.local_participant, "unpublish_track", None)
        if unpublish is not None and publication is not None:
            sid = getattr(publication, "sid", None) or getattr(publication, "track_sid", None)
            if sid:
                result = unpublish(sid)
                if asyncio.iscoroutine(result):
                    await result
        await source.aclose()
        await room.disconnect()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish a professor WAV file into LiveKit.")
    parser.add_argument("--url", required=True, help="LiveKit websocket URL")
    parser.add_argument("--token", required=True, help="Professor LiveKit token")
    parser.add_argument("--wav", required=True, help="16kHz/16-bit/mono PCM WAV path")
    parser.add_argument("--loop", action="store_true", help="Loop the WAV until interrupted")
    parser.add_argument(
        "--realtime",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Send frames in real time (default true)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
