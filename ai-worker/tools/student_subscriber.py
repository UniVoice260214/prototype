from __future__ import annotations

import argparse
import asyncio
import json
import sys
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


def _payload_to_text(payload: Any) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    if hasattr(payload, "data"):
        data = getattr(payload, "data")
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
    return str(payload)


def _topic_from_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if "topic" in kwargs:
        return str(kwargs["topic"])
    for arg in args:
        topic = getattr(arg, "topic", None)
        if topic:
            return str(topic)
    if len(args) >= 4 and isinstance(args[3], str):
        return args[3]
    return ""


def _payload_from_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if "payload" in kwargs:
        return kwargs["payload"]
    if args:
        packet_data = getattr(args[0], "data", None)
        if packet_data is not None:
            return packet_data
        return args[0]
    return b""


def _print_event(prefix: str, data: dict[str, Any]) -> None:
    segment_id = data.get("segmentId", "-")
    sequence = data.get("sequence", "-")
    locale = data.get("locale") or data.get("lang") or "-"
    text = data.get("text")
    error_code = data.get("errorCode")
    extra = f" text={text!r}" if text is not None else ""
    if error_code:
        extra += f" error={error_code}"
    print(f"{prefix} segment={segment_id} sequence={sequence} locale={locale}{extra}")


class AudioRecorder:
    def __init__(self, output_dir: Path | None, locale: str) -> None:
        self._output_dir = output_dir
        self._locale = locale
        self._counter = 0

    async def consume(self, track: Any) -> None:
        stream = rtc.AudioStream(track)
        writer: wave.Wave_write | None = None
        try:
            async for event in stream:
                frame = event.frame
                data = frame.data.tobytes() if hasattr(frame.data, "tobytes") else bytes(frame.data)
                if writer is None and self._output_dir is not None:
                    self._counter += 1
                    self._output_dir.mkdir(parents=True, exist_ok=True)
                    path = self._output_dir / f"tts-{self._locale}-{self._counter:03d}.wav"
                    writer = wave.open(str(path), "wb")
                    writer.setnchannels(int(getattr(frame, "num_channels", 1)))
                    writer.setsampwidth(2)
                    writer.setframerate(int(getattr(frame, "sample_rate", 16000)))
                    print(f"recording audio to {path}")
                if writer is not None:
                    writer.writeframes(data)
        except asyncio.CancelledError:
            raise
        finally:
            if writer is not None:
                writer.close()
            await stream.aclose()


async def run(args: argparse.Namespace) -> int:
    if rtc is None:
        print("LiveKit SDK is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 2
    if not args.locale:
        print("--locale is required", file=sys.stderr)
        return 2

    room = rtc.Room()
    recorder = AudioRecorder(Path(args.output_dir) if args.output_dir else None, args.locale)
    audio_tasks: set[asyncio.Task[None]] = set()
    done = asyncio.Event()

    def on_track_subscribed(track: Any, publication: Any, participant: Any) -> None:
        name = getattr(publication, "name", None) or getattr(track, "name", "")
        if name != f"tts.{args.locale}":
            return
        print(f"subscribed audio track {name}")
        task = asyncio.create_task(recorder.consume(track))
        audio_tasks.add(task)
        task.add_done_callback(audio_tasks.discard)

    def on_data_received(*event_args: Any, **kwargs: Any) -> None:
        topic = _topic_from_args(event_args, kwargs)
        text = _payload_to_text(_payload_from_args(event_args, kwargs))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print(f"data topic={topic} payload={text!r}")
            return
        if topic == "caption" and data.get("locale") == args.locale:
            _print_event("caption", data)
        elif topic == "audio-status" and data.get("locale") == args.locale:
            _print_event("audio", data)

    room.on("track_subscribed", on_track_subscribed)
    room.on("data_received", on_data_received)
    room.on("disconnected", lambda *_: done.set())

    try:
        await room.connect(args.url, args.token)
    except Exception as exc:  # noqa: BLE001
        print(f"failed to connect to LiveKit room: {exc}", file=sys.stderr)
        return 1

    print(f"connected; filtering locale={args.locale}")
    try:
        if args.duration is None:
            await done.wait()
        else:
            await asyncio.wait_for(done.wait(), timeout=max(0.1, args.duration))
    except TimeoutError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        for task in audio_tasks:
            task.cancel()
        await asyncio.gather(*audio_tasks, return_exceptions=True)
        await room.disconnect()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Subscribe to UniVoice student caption/audio delivery.")
    parser.add_argument("--url", required=True, help="LiveKit websocket URL")
    parser.add_argument("--token", required=True, help="LiveKit student token")
    parser.add_argument("--locale", required=True, help="Target locale, e.g. vi-VN")
    parser.add_argument("--output-dir", help="Optional directory for received WAV files")
    parser.add_argument("--duration", type=float, help="Optional listen duration in seconds")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
