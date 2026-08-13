"""실시간 지연 실측 하네스.

WAV 강의 녹음을 **실시간 속도로** 실제 Azure STT 에 흘려넣고, 실제 번역 API 와
실제 Azure TTS 를 태워 세그먼트별 구간 지연을 JSONL 로 남긴다.

LiveKit / NestJS / Postgres 없이 워커 파이프라인만 돌린다. 따라서 측정에서
빠지는 것은 **LiveKit 전송 홉 하나뿐**이고, 나머지(STT 확정, 세그먼트 대기,
RAG, 번역, TTS 합성)는 운영과 동일한 실제 호출이다.

    python tools/latency_probe.py --wav bench_data/synthetic_ai_intro.wav \
        --locales vi-VN --out latency.jsonl

주의: 실제 Azure Speech / 번역 API 를 호출하므로 비용이 발생한다.
`--no-tts` 로 TTS 합성을 빼면 자막 경로만 더 싸게 측정할 수 있다.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import wave
from pathlib import Path
from typing import Any

AI_WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(AI_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_WORKER_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_RATE = 16000
FRAME_SEC = 0.02
FRAME_BYTES = int(SAMPLE_RATE * FRAME_SEC) * 2  # 16-bit mono


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != SAMPLE_RATE:
            raise SystemExit(
                "16kHz/16-bit/mono PCM WAV 만 지원한다 "
                f"(현재 {wav.getframerate()}Hz, {wav.getsampwidth() * 8}-bit, {wav.getnchannels()}ch)"
            )
        return wav.readframes(wav.getnframes())


class NullAudioPublisher:
    """LiveKit 오디오 트랙 대신. 발행 지연을 0에 가깝게 유지해 상류 구간을 왜곡하지 않는다."""

    def __init__(self) -> None:
        self.frames = 0

    async def push_pcm(self, locale: str, pcm: bytes) -> int:
        self.frames += 1
        return int(len(pcm) // 2 * 1000 / SAMPLE_RATE)

    async def aclose(self) -> None:
        return None


class SilentTts:
    """--no-tts 용. 합성 대신 무음을 즉시 반환한다."""

    async def synthesize_job(self, job: Any) -> bytes:
        return b"\0" * 320


async def main_async(args: argparse.Namespace) -> int:
    # 계측을 켠 뒤에 워커 모듈을 임포트해야 default_log() 가 경로를 잡는다.
    os.environ["LATENCY_LOG_PATH"] = str(args.out)

    from univoice_worker.config import load_config
    from univoice_worker.latency import reset_default_log
    from univoice_worker.lexicon import LexiconRegistry, build_phrase_list
    from univoice_worker.models import SpeechSegment
    from univoice_worker.pipeline import TranslationPipeline
    from univoice_worker.rag import HttpRagClient, NoOpRagClient
    from univoice_worker.segmenter import Segmenter
    from univoice_worker.stt import AzureStreamingStt, SttTuning
    from univoice_worker.translator import Translator
    from univoice_worker.tts import TtsSynthesizer

    reset_default_log()
    config = load_config()
    locales = [loc.strip() for loc in args.locales.split(",") if loc.strip()]
    if not locales:
        raise SystemExit("--locales 가 비었다")

    pcm = read_wav(Path(args.wav))
    audio_sec = len(pcm) / (SAMPLE_RATE * 2)
    print(
        f"오디오 {audio_sec:.1f}초 / STT={config.stt_provider} / 번역={config.openai_model} "
        f"/ locales={','.join(locales)} / TTS={'off' if args.no_tts else 'on'}",
        file=sys.stderr,
    )

    # RAG 는 번역 크리티컬 패스에 동기로 걸린다. 껐으면 껐다고 결과에 남겨야지,
    # 0ms 로 남겨 "오버헤드 없음"으로 오독되게 두면 안 된다.
    rag_on = config.rag_enabled or args.rag
    if rag_on:
        rag: Any = HttpRagClient(
            args.rag_url or config.rag_url,
            major=args.major or config.rag_default_major,
            timeout_sec=config.rag_timeout_sec,
        )
        print(
            f"RAG on: {args.rag_url or config.rag_url} "
            f"(major={args.major or config.rag_default_major}, "
            f"timeout={config.rag_timeout_sec}s)",
            file=sys.stderr,
        )
    else:
        rag = NoOpRagClient()
        print("RAG off — 결과에서 RAG 구간은 '미측정'으로 빠진다", file=sys.stderr)

    lexicon: Any = None
    if args.major:
        registry = LexiconRegistry.load_dir(Path(config.rag_assets_dir))
        lexicon = registry.get(args.major)
        if lexicon is None:
            print(
                f"lexicon 없음: major={args.major} (사용 가능: {registry.majors()}); 없이 진행",
                file=sys.stderr,
            )

    translator = Translator(config, locales, [], lexicon)
    tts = (
        SilentTts()
        if args.no_tts
        else TtsSynthesizer(
            config.azure_speech_key,
            config.azure_speech_region,
            config.voice_map,
            timeout_sec=config.tts_timeout_sec,
            max_retries=config.tts_max_retries,
            retry_base_delay_ms=config.tts_retry_base_delay_ms,
            max_concurrency=config.tts_max_concurrency,
        )
    )

    captions: list[str] = []

    async def on_subtitle(
        locale: str, text: str, segment: SpeechSegment, is_final: bool, *, is_fallback: bool = False
    ) -> None:
        if locale == locales[0]:
            captions.append(text)
            print(f"  [{segment.sequence:>3}] {segment.text} → {text}", file=sys.stderr)

    pipeline = TranslationPipeline(
        session_id="latency-probe",
        target_locales=locales,
        segmenter=Segmenter(
            max_chars=config.segment_max_chars,
            idle_flush_ms=config.segment_idle_flush_ms,
            min_chars=config.segment_min_chars,
            split_korean_endings=config.segment_split_korean_endings,
        ),
        rag=rag,
        translator=translator,
        tts=tts,
        publisher=NullAudioPublisher(),
        on_subtitle=on_subtitle,
        corrector=lexicon.correct_for_display if lexicon is not None else None,
        queue_max_size=config.segment_queue_max_size,
        enqueue_timeout_ms=config.segment_enqueue_timeout_ms,
        tts_queue_max_size=config.tts_queue_max_size,
    )
    await pipeline.start()

    loop = asyncio.get_running_loop()
    phrases, _stats = build_phrase_list(
        glossary_terms=[],
        lexicon=lexicon,
        max_items=config.stt_phrase_list_max_items,
        max_chars=config.stt_phrase_list_max_chars,
    )

    stt = AzureStreamingStt(
        key=config.azure_speech_key,
        region=config.azure_speech_region,
        language=config.stt_language,
        phrases=phrases,
        on_partial=lambda _result: None,
        on_final=lambda result: asyncio.run_coroutine_threadsafe(
            pipeline.enqueue_stt_final(result), loop
        ),
        on_error=lambda error: print(f"STT 오류: {error.message}", file=sys.stderr),
        tuning=SttTuning(
            segmentation_silence_ms=config.stt_segmentation_silence_ms,
            segmentation_max_time_ms=config.stt_segmentation_max_time_ms,
            initial_silence_ms=config.stt_initial_silence_ms,
            end_silence_ms=config.stt_end_silence_ms,
            true_text=config.stt_true_text,
            profanity_raw=config.stt_profanity_raw,
            endpoint_id=config.stt_endpoint_id,
            phrase_list_weight=config.stt_phrase_list_weight,
        ),
    )
    stt.start()

    # 한 번에 이어붙여 **끊김 없이** 실시간으로 흘려보낸다.
    #
    # 중요: Azure 의 offset 은 "밀어 넣은 오디오 샘플" 기준이지 벽시계가 아니다.
    # 발화 사이를 sleep 으로 비우면 오디오 타임라인만 멈춰 speech_end_at 이
    # 그만큼 과거로 밀리고, STT 확정 지연이 누적 드리프트만큼 부풀어 오른다.
    # 따라서 공백도 반드시 "무음 프레임"으로 채워 타임라인과 벽시계를 일치시킨다.
    tail_silence = bytes(int(args.tail_sec * SAMPLE_RATE) * 2)
    stream = (pcm + tail_silence) * args.repeat
    total_frames = (len(stream) + FRAME_BYTES - 1) // FRAME_BYTES
    print(
        f"스트리밍 {len(stream) / (SAMPLE_RATE * 2):.1f}초 "
        f"(본문 {audio_sec:.1f}초 + 무음 {args.tail_sec:.1f}초) x {args.repeat}회, 연속 전송",
        file=sys.stderr,
    )

    try:
        start = time.monotonic()
        for i in range(total_frames):
            chunk = stream[i * FRAME_BYTES : (i + 1) * FRAME_BYTES]
            if len(chunk) < FRAME_BYTES:
                chunk += bytes(FRAME_BYTES - len(chunk))
            stt.write(chunk)
            # 실시간 속도 유지 — 이걸 어기면 STT 침묵 대기 측정이 무의미해진다.
            target = start + (i + 1) * FRAME_SEC
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
        drift = (time.monotonic() - start) - total_frames * FRAME_SEC
        print(f"전송 완료 (벽시계 드리프트 {drift * 1000:+.0f}ms)", file=sys.stderr)
        if abs(drift) > 0.5:
            print(
                "경고: 드리프트가 500ms 를 넘는다 — STT 확정 구간 수치를 신뢰하지 말 것.",
                file=sys.stderr,
            )
    finally:
        stt.stop()
        await asyncio.sleep(1.0)
        await pipeline.flush_and_stop()

    print(f"\n자막 {len(captions)}건 기록 → {args.out}", file=sys.stderr)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", required=True, help="16kHz/16-bit/mono PCM WAV")
    parser.add_argument("--locales", default="vi-VN", help="쉼표 구분 대상 로케일")
    parser.add_argument("--out", default="latency.jsonl", help="지연 JSONL 출력 경로")
    parser.add_argument("--major", default="", help="lexicon 전공 키 (ai/hss/bme). 비우면 미사용")
    parser.add_argument("--repeat", type=int, default=1, help="같은 오디오 반복 횟수 (표본 확보)")
    parser.add_argument("--tail-sec", type=float, default=3.0, help="마지막 발화 확정 대기")
    parser.add_argument("--no-tts", action="store_true", help="TTS 합성을 건너뛴다 (자막만 측정)")
    parser.add_argument(
        "--rag", action="store_true", help="RAG_ENABLED 가 꺼져 있어도 RAG 를 태운다"
    )
    parser.add_argument("--rag-url", default="", help="RAG 서비스 URL 오버라이드")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
