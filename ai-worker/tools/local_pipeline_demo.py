from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

AI_WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(AI_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_WORKER_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from univoice_worker.models import AudioStatus, SpeechSegment
from univoice_worker.pipeline import TranslationPipeline
from univoice_worker.segmenter import Segmenter

try:
    from fakes import FakeAudioPublisher, FakeRagClient, FakeTranslator, FakeTts, stt_final
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1] / "tests"))
    from fakes import FakeAudioPublisher, FakeRagClient, FakeTranslator, FakeTts, stt_final


async def run(args: argparse.Namespace) -> int:
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    if not text:
        print("provide --text or --file", file=sys.stderr)
        return 2

    locales = [locale.strip() for locale in args.locales.split(",") if locale.strip()]
    if not locales:
        print("provide at least one locale", file=sys.stderr)
        return 2

    translations = {locale: f"[{locale}] {text.strip()}" for locale in locales}

    async def on_segment(segment: SpeechSegment) -> None:
        print(f"stt.final segmentId={segment.segment_id} sequence={segment.sequence} text={segment.text!r}")

    async def on_subtitle(locale: str, caption: str, segment: SpeechSegment, is_final: bool) -> None:
        print(
            f"caption.final segmentId={segment.segment_id} sequence={segment.sequence} "
            f"locale={locale} text={caption!r}"
        )

    async def on_audio_status(status: AudioStatus) -> None:
        print(
            f"{status.type} segmentId={status.segment_id} sequence={status.sequence} "
            f"locale={status.locale} durationMs={status.duration_ms} errorCode={status.error_code}"
        )

    pipeline = TranslationPipeline(
        session_id="local-demo",
        target_locales=locales,
        segmenter=Segmenter(),
        rag=FakeRagClient(),
        translator=FakeTranslator(translations),
        tts=FakeTts(b"\0" * 320),
        publisher=FakeAudioPublisher(),
        on_subtitle=on_subtitle,
        on_audio_status=on_audio_status,
        on_segment=on_segment,
    )

    for line in text.splitlines() or [text]:
        await pipeline.enqueue_stt_final(stt_final(line))
    await pipeline.flush_and_stop()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the UniVoice pipeline with fake translator/TTS.")
    parser.add_argument("--text", help="Input text")
    parser.add_argument("--file", help="UTF-8 text file")
    parser.add_argument("--locales", default="vi-VN,zh-CN,mn-MN", help="Comma-separated target locales")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
