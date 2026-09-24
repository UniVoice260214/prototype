"""지연 계측의 정확성 검증.

발표 자료에 들어갈 숫자를 만드는 코드이므로, 부호가 뒤집히거나 구간이 어긋나면
그럴듯한 거짓 수치가 나온다. 알려진 지연을 주입하고 기록된 값이 그 지연과
일치하는지 확인한다.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from univoice_worker.latency import LatencyLog, elapsed_ms
from univoice_worker.models import SttFinalResult
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter
from univoice_worker.stt import AzureStreamingStt
from univoice_worker.tts_queue import LocaleTtsQueue

from fakes import FakeAudioPublisher, FakeRagClient, FakeTranslator, FakeTts


class RecordingLog(LatencyLog):
    """파일 대신 메모리에 모으는 기록기."""

    def __init__(self) -> None:
        super().__init__(path=None)
        self.records: list[dict] = []

    @property
    def enabled(self) -> bool:
        return True

    def record(self, kind: str, **fields) -> None:
        # 실제 기록기와 동일하게 None 필드를 버린다.
        self.records.append({"kind": kind, **{k: v for k, v in fields.items() if v is not None}})

    def of(self, kind: str) -> list[dict]:
        return [r for r in self.records if r["kind"] == kind]


def test_elapsed_ms_handles_missing_anchors() -> None:
    assert elapsed_ms(None, 1.0) is None
    assert elapsed_ms(1.0, None) is None
    assert elapsed_ms(1.0, 1.25) == 250.0


def test_latency_log_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LATENCY_LOG_PATH", raising=False)
    assert LatencyLog().enabled is False


def test_latency_log_writes_jsonl(tmp_path) -> None:
    target = tmp_path / "nested" / "latency.jsonl"
    log = LatencyLog(path=str(target))
    log.record("caption", segmentId="s-1", e2eCaptionMs=1234.5, dropped=None)
    log.record("audio", segmentId="s-1", e2eAudioMs=2000.0)

    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {"kind": "caption", "segmentId": "s-1", "e2eCaptionMs": 1234.5}
    # None 필드는 기록에서 빠져야 한다 — 집계 시 0으로 오해되면 안 된다.
    assert "dropped" not in first


class SlowRag(FakeRagClient):
    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        await asyncio.sleep(self.delay)
        return None


class SlowTranslator(FakeTranslator):
    def __init__(self, delay: float, translations: dict[str, str]) -> None:
        super().__init__(translations)
        self.delay = delay

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        await asyncio.sleep(self.delay)
        return await super().translate(sentence, rag_context)


class SlowTts(FakeTts):
    def __init__(self, delay: float) -> None:
        super().__init__(b"\0" * 320)
        self.delay = delay

    async def synthesize_job(self, job) -> bytes:
        await asyncio.sleep(self.delay)
        return await super().synthesize_job(job)


def _pipeline(log: RecordingLog, *, rag_delay: float, translate_delay: float, tts_delay: float):
    publisher = FakeAudioPublisher()
    tts = SlowTts(tts_delay)
    queue = LocaleTtsQueue(
        locales=["vi-VN"],
        tts=tts,
        publisher=publisher,
        latency_log=log,
    )
    return TranslationPipeline(
        session_id="sess-1",
        target_locales=["vi-VN"],
        segmenter=Segmenter(),
        rag=SlowRag(rag_delay),
        translator=SlowTranslator(translate_delay, {"vi-VN": "xin chao"}),
        tts=tts,
        publisher=publisher,
        on_subtitle=_noop_subtitle,
        tts_queue=queue,
        latency_log=log,
    )


async def _noop_subtitle(locale, text, segment, is_final, *, is_fallback=False) -> None:
    return None


@pytest.mark.asyncio
async def test_pipeline_records_injected_stage_delays() -> None:
    log = RecordingLog()
    pipeline = _pipeline(log, rag_delay=0.05, translate_delay=0.12, tts_delay=0.08)

    speech_end = time.monotonic()
    # STT 가 발화 종료 0.30초 뒤에 final 을 준 상황. 한 문장이어야 세그먼트가 하나다.
    await asyncio.sleep(0.30)
    await pipeline.enqueue_stt_final(
        SttFinalResult(
            text="오늘 수업을 시작하겠습니다.",
            confidence=0.9,
            offset_ms=0,
            duration_ms=0,
            received_at=time.monotonic(),
            speech_end_at=speech_end,
        )
    )
    await pipeline.flush_and_stop()

    captions = log.of("caption")
    assert len(captions) == 1, captions
    caption = captions[0]

    # 주입한 지연이 해당 구간에만 잡혀야 한다 (스케줄러 오차 여유 포함).
    assert caption["sttMs"] == pytest.approx(300, abs=60)
    assert caption["ragMs"] == pytest.approx(50, abs=40)
    assert caption["translateMs"] == pytest.approx(120, abs=40)
    # E2E 는 발화 종료 기준이므로 STT 확정 + 이후 처리를 모두 포함한다.
    assert caption["e2eCaptionMs"] > caption["workerMs"]
    assert caption["e2eCaptionMs"] == pytest.approx(
        caption["sttMs"] + caption["workerMs"], abs=15
    )
    assert caption["workerMs"] >= caption["ragMs"] + caption["translateMs"]

    audios = log.of("audio")
    assert len(audios) == 1, audios
    audio = audios[0]
    assert audio["ttsSynthMs"] == pytest.approx(80, abs=40)
    # 음성은 자막보다 뒤에 나온다.
    assert audio["e2eAudioMs"] > caption["e2eCaptionMs"]


@pytest.mark.asyncio
async def test_pipeline_omits_e2e_when_stt_gives_no_audio_offset() -> None:
    """OpenAI STT 처럼 오디오 오프셋이 없으면 E2E 를 지어내지 않고 생략한다."""
    log = RecordingLog()
    pipeline = _pipeline(log, rag_delay=0.0, translate_delay=0.0, tts_delay=0.0)

    await pipeline.enqueue_stt_final(
        SttFinalResult(
            text="문장 하나입니다.",
            confidence=0.9,
            offset_ms=None,
            duration_ms=None,
            received_at=time.monotonic(),
            speech_end_at=None,
        )
    )
    await pipeline.flush_and_stop()

    caption = log.of("caption")[0]
    assert "e2eCaptionMs" not in caption
    assert "sttMs" not in caption
    # 워커 내부 구간은 여전히 측정된다.
    assert caption["workerMs"] >= 0


def test_speech_end_at_uses_first_write_as_audio_anchor() -> None:
    """Azure offset 의 기준점은 start() 가 아니라 첫 오디오 write 다."""
    stt = AzureStreamingStt.__new__(AzureStreamingStt)
    stt._stream_started_at = None

    assert stt._speech_end_at(1000, 500) is None, "앵커 전에는 복원할 수 없다"

    stt._stream_started_at = 100.0
    # 스트림 시작 1.0초 지점에서 시작해 0.5초 동안 말했다면 종료는 1.5초 지점.
    assert stt._speech_end_at(1000, 500) == pytest.approx(101.5)
    assert stt._speech_end_at(None, 500) is None
