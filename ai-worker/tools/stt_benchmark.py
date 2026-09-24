"""STT 엔진 교체 후보 비교 벤치마크.

동일한 강의 녹음(wav) + 정답 전사(txt) 세트를 여러 STT 공급자로 돌려
CER/WER 를 비교한 마크다운 리포트를 만든다.

사용법:
    python tools/stt_benchmark.py --data-dir bench_data --providers azure
    python tools/stt_benchmark.py --data-dir bench_data --providers azure,whisper -o report.md

데이터 폴더 규칙:
    bench_data/
      sample1.wav   # 16kHz mono PCM 권장
      sample1.txt   # 사람이 검수한 정답 전사
      sample2.wav
      sample2.txt

공급자:
    azure    Azure Speech (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION, STT_LANGUAGE)
    whisper  OpenAI Whisper API (OPENAI_API_KEY, 모델 whisper-1)

새 후보 엔진은 SttProvider 프로토콜(transcribe(wav_path) -> str)만 구현해
PROVIDERS 에 등록하면 된다.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable, Protocol

# tools/ 에서 바로 실행해도 univoice_worker 패키지를 찾도록 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from univoice_worker.evaluation import (
    SampleScore,
    aggregate_cer,
    cer,
    normalize_text,
    strip_fillers,
    wer,
)


class SttProvider(Protocol):
    name: str

    def transcribe(self, wav_path: Path) -> str:
        """Return the full transcript for one audio file."""


class AzureProvider:
    """현재 프로덕션 엔진. 비교의 기준선(baseline)."""

    name = "azure"

    def __init__(self) -> None:
        import azure.cognitiveservices.speech as speechsdk  # lazy import

        self._speechsdk = speechsdk
        key = os.environ.get("AZURE_SPEECH_KEY", "")
        region = os.environ.get("AZURE_SPEECH_REGION", "")
        if not key or not region:
            raise SystemExit("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION 이 필요합니다.")
        self._config = speechsdk.SpeechConfig(subscription=key, region=region)
        self._config.speech_recognition_language = os.environ.get("STT_LANGUAGE", "ko-KR")

    def transcribe(self, wav_path: Path) -> str:
        speechsdk = self._speechsdk
        audio = speechsdk.audio.AudioConfig(filename=str(wav_path))
        recognizer = speechsdk.SpeechRecognizer(speech_config=self._config, audio_config=audio)

        finals: list[str] = []
        done = False

        def on_final(evt) -> None:  # noqa: ANN001
            if evt.result.text:
                finals.append(evt.result.text)

        def on_stop(_evt) -> None:  # noqa: ANN001
            nonlocal done
            done = True

        recognizer.recognized.connect(on_final)
        recognizer.session_stopped.connect(on_stop)
        recognizer.canceled.connect(on_stop)
        recognizer.start_continuous_recognition()
        while not done:
            time.sleep(0.1)
        recognizer.stop_continuous_recognition()
        return " ".join(finals)


class WhisperApiProvider:
    """교체 후보 예시: OpenAI Whisper API."""

    name = "whisper"

    def __init__(self) -> None:
        from openai import OpenAI  # lazy import

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY 가 필요합니다.")
        self._client = OpenAI(api_key=api_key)
        self._language = os.environ.get("STT_LANGUAGE", "ko-KR").split("-")[0]

    def transcribe(self, wav_path: Path) -> str:
        with wav_path.open("rb") as f:
            result = self._client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=self._language,
            )
        return result.text


PROVIDERS: dict[str, Callable[[], SttProvider]] = {
    "azure": AzureProvider,
    "whisper": WhisperApiProvider,
}


def collect_samples(data_dir: Path) -> list[tuple[str, Path, str]]:
    samples: list[tuple[str, Path, str]] = []
    for wav in sorted(data_dir.glob("*.wav")):
        ref_path = wav.with_suffix(".txt")
        if not ref_path.exists():
            print(f"skip {wav.name}: 정답 전사({ref_path.name})가 없습니다", file=sys.stderr)
            continue
        samples.append((wav.stem, wav, ref_path.read_text(encoding="utf-8").strip()))
    return samples


def run_provider(
    provider: SttProvider,
    samples: list[tuple[str, Path, str]],
    *,
    drop_fillers: bool = False,
) -> tuple[list[SampleScore], dict[str, str]]:
    scores: list[SampleScore] = []
    transcripts: dict[str, str] = {}
    for name, wav, reference in samples:
        started = time.monotonic()
        try:
            hypothesis = provider.transcribe(wav)
        except Exception as exc:  # noqa: BLE001
            print(f"[{provider.name}] {name}: 실패 — {exc}", file=sys.stderr)
            hypothesis = ""
        elapsed = time.monotonic() - started
        transcripts[name] = hypothesis
        scored_reference = strip_fillers(reference) if drop_fillers else reference
        scores.append(
            SampleScore(
                name=name,
                cer=cer(reference, hypothesis, drop_fillers=drop_fillers),
                wer=wer(reference, hypothesis, drop_fillers=drop_fillers),
                ref_chars=len(normalize_text(scored_reference)),
            )
        )
        print(
            f"[{provider.name}] {name}: CER {scores[-1].cer:.3f} / WER {scores[-1].wer:.3f} "
            f"({elapsed:.1f}s)",
            file=sys.stderr,
        )
    return scores, transcripts


def render_report(
    results: dict[str, list[SampleScore]],
    transcripts: dict[str, dict[str, str]],
    samples: list[tuple[str, Path, str]],
) -> str:
    lines = ["# STT 엔진 비교 리포트", ""]
    lines.append("| 엔진 | 전체 CER(가중) | 평균 WER | 샘플 수 |")
    lines.append("|------|---------------|---------|--------|")
    for engine, scores in results.items():
        mean_wer = sum(s.wer for s in scores) / len(scores) if scores else 0.0
        lines.append(
            f"| {engine} | {aggregate_cer(scores):.3f} | {mean_wer:.3f} | {len(scores)} |"
        )
    lines.append("")
    lines.append("## 샘플별 CER")
    lines.append("")
    engines = list(results.keys())
    lines.append("| 샘플 | " + " | ".join(engines) + " |")
    lines.append("|------|" + "|".join(["------"] * len(engines)) + "|")
    for name, _wav, _ref in samples:
        row = [name]
        for engine in engines:
            score = next((s for s in results[engine] if s.name == name), None)
            row.append(f"{score.cer:.3f}" if score else "-")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## 전사 결과 (검수용)")
    for name, _wav, reference in samples:
        lines.append("")
        lines.append(f"### {name}")
        lines.append(f"- 정답: {reference}")
        for engine in engines:
            lines.append(f"- {engine}: {transcripts[engine].get(name, '')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument(
        "--providers",
        default="azure",
        help=f"쉼표 구분 목록 (지원: {', '.join(PROVIDERS)})",
    )
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument(
        "--drop-fillers",
        action="store_true",
        help="사람 전사에만 있는 간투사(씁/어/아 등)를 양쪽에서 제거하고 채점",
    )
    args = parser.parse_args()

    samples = collect_samples(args.data_dir)
    if not samples:
        raise SystemExit(f"{args.data_dir} 에 wav+txt 쌍이 없습니다.")

    results: dict[str, list[SampleScore]] = {}
    transcripts: dict[str, dict[str, str]] = {}
    for key in [p.strip() for p in args.providers.split(",") if p.strip()]:
        factory = PROVIDERS.get(key)
        if factory is None:
            raise SystemExit(f"알 수 없는 provider: {key} (지원: {', '.join(PROVIDERS)})")
        provider = factory()
        results[key], transcripts[key] = run_provider(
            provider, samples, drop_fillers=args.drop_fillers
        )

    report = render_report(results, transcripts, samples)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
