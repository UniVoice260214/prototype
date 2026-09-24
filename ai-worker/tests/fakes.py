from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from univoice_worker.models import SttFinalResult, TtsJob


def stt_final(text: str, confidence: float | None = None) -> SttFinalResult:
    return SttFinalResult(
        text=text,
        confidence=confidence,
        offset_ms=None,
        duration_ms=None,
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeRagClient:
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        return None


class FakeTranslator:
    def __init__(
        self,
        translations: dict[str, str] | None = None,
        *,
        fail_texts: set[str] | None = None,
    ) -> None:
        self.translations = translations or {"vi-VN": "xin chao"}
        self.fail_texts = fail_texts or set()
        self.seen: list[str] = []

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        return []

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        self.seen.append(sentence)
        if sentence in self.fail_texts:
            raise RuntimeError(f"translation failed for {sentence}")
        return dict(self.translations)


class FakeTts:
    def __init__(self, pcm: bytes = b"ok") -> None:
        self.pcm = pcm
        self.calls: list[TtsJob] = []

    async def synthesize_job(self, job: TtsJob) -> bytes:
        self.calls.append(job)
        return self.pcm

    def synthesize(self, locale: str, text: str) -> bytes:
        return f"{locale}:{text}".encode()


class FakeAudioPublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []
        self.closed = False

    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        self.published.append((locale, pcm))
        return 10

    async def aclose(self) -> None:
        self.closed = True


class FakeStt:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.writes: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def write(self, pcm: bytes) -> None:
        self.writes.append(pcm)


class FakeLiveKitRoom:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.local_participant = FakeLocalParticipant()
        self.connected = False
        self.disconnected = False

    def on(self, event: str, callback: Any) -> None:
        self.handlers[event] = callback

    async def connect(self, url: str, token: str) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.data_messages: list[tuple[bytes, bool, str]] = []
        self.tracks: list[Any] = []

    async def publish_data(self, payload: bytes, *, reliable: bool, topic: str) -> None:
        self.data_messages.append((payload, reliable, topic))

    async def publish_track(self, track: Any, options: Any = None) -> Any:
        self.tracks.append(track)
        return object()


class FakeRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.sets: list[tuple[str, str, int | None]] = []
        self.deleted: list[str] = []

    async def scan_iter(self, *, match: str, count: int):
        for key in self.values:
            if key.startswith("session:") and key.endswith(":status"):
                yield key

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.values[key] = value
        self.sets.append((key, value, ex))

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.deleted.append(key)


class FakeJsonRedis(FakeRedis):
    def set_json(self, key: str, value: dict[str, Any]) -> None:
        self.values[key] = json.dumps(value)


@dataclass
class FakeTrack:
    kind: str = "audio"
    sid: str = "track-1"


@dataclass
class FakeParticipant:
    identity: str = "professor-1"


class NeverEndingStream:
    def __init__(self, track: Any) -> None:
        self.closed = False

    def __aiter__(self) -> "NeverEndingStream":
        return self

    async def __anext__(self) -> object:
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True
