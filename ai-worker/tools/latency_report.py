"""LATENCY_LOG_PATH 로 쌓인 JSONL 을 구간별 p50/p95 표로 집계한다.

사용법:
    python tools/latency_report.py --input latency.jsonl
    python tools/latency_report.py --input latency.jsonl -o docs/latency.md

`--min-samples` 미만인 구간은 표에서 뺀다. 표본이 적은 수치를 발표에 그대로
싣는 것을 막기 위한 것이다 (기본 5).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (JSON 키, 표에 쓸 이름, 설명)
CAPTION_STAGES = [
    ("sttMs", "STT 확정", "발화 종료 → STT final 수신 (침묵 대기 + 인식 + 왕복)"),
    ("segmentMs", "세그먼트 대기", "STT final → 번역 단위 확정 (문장 경계/idle flush)"),
    ("queueMs", "큐 대기", "세그먼트 큐에서 대기"),
    ("glossaryMs", "용어 탐지", "glossary 히트 검사"),
    ("ragMs", "RAG 검색", "전공 문맥 검색 (타임아웃 시 잘림)"),
    ("translateMs", "번역", "번역 LLM 호출"),
    ("emitMs", "자막 발행", "LiveKit data 발행 + TTS 큐 적재"),
]
CAPTION_TOTALS = [
    ("workerMs", "워커 내부 합", "STT final 수신 → 자막 발행"),
    ("e2eCaptionMs", "E2E 자막", "발화 종료 → 자막 발행"),
]
AUDIO_STAGES = [
    ("ttsQueueMs", "TTS 큐 대기", "TTS 큐 적재 → 합성 시작"),
    ("ttsSynthMs", "TTS 합성", "Azure Neural TTS 합성"),
    ("ttsPublishMs", "오디오 발행", "LiveKit 오디오 트랙 push"),
]
AUDIO_TOTALS = [
    ("e2eAudioMs", "E2E 음성", "발화 종료 → 음성 발행"),
]


def percentile(values: list[float], q: float) -> float:
    """선형 보간 분위수. numpy 의존 없이 계산한다."""
    if not values:
        raise ValueError("empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def load(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(record, dict):
            records.append(record)
    if bad:
        print(f"경고: 파싱 실패한 줄 {bad}개를 건너뜀", file=sys.stderr)
    return records


def collect(records: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for record in records:
        raw = record.get(key)
        if isinstance(raw, (int, float)):
            values.append(float(raw))
    return values


def render_rows(
    records: list[dict[str, Any]],
    stages: list[tuple[str, str, str]],
    min_samples: int,
) -> tuple[list[str], list[str]]:
    """표 행과, 표본 부족으로 뺀 구간 목록을 돌려준다.

    표본이 0인 구간은 행을 지우지 않고 **미측정으로 표시한다.** 조용히 사라지면
    "그 단계가 없다"로 읽히고, 0ms 로 적으면 "공짜"로 읽힌다. 둘 다 틀렸다.
    """
    rows: list[str] = []
    skipped: list[str] = []
    for key, label, note in stages:
        values = collect(records, key)
        if not values:
            rows.append(f"| {label} | — | — | — | 0 | **미측정** — {note} |")
            continue
        if len(values) < min_samples:
            skipped.append(f"{label} (표본 {len(values)}개)")
            continue
        rows.append(
            f"| {label} | {percentile(values, 0.5):,.0f} | {percentile(values, 0.95):,.0f} "
            f"| {max(values):,.0f} | {len(values)} | {note} |"
        )
    return rows, skipped


def section(
    title: str,
    records: list[dict[str, Any]],
    stages: list[tuple[str, str, str]],
    totals: list[tuple[str, str, str]],
    min_samples: int,
) -> list[str]:
    lines = [f"## {title}", ""]
    if not records:
        lines += ["측정 레코드가 없다.", ""]
        return lines

    header = [
        "| 구간 | p50 (ms) | p95 (ms) | max (ms) | 표본 | 설명 |",
        "|------|--------:|--------:|--------:|-----:|------|",
    ]
    stage_rows, stage_skipped = render_rows(records, stages, min_samples)
    total_rows, total_skipped = render_rows(records, totals, min_samples)

    lines += header + stage_rows
    if total_rows:
        lines.append("| | | | | | |")
        lines += total_rows
    lines.append("")

    skipped = stage_skipped + total_skipped
    if skipped:
        lines += [f"표본 부족으로 제외: {', '.join(skipped)}", ""]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="LATENCY_LOG_PATH 로 쌓인 JSONL")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--min-samples", type=int, default=5)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"입력 파일이 없다: {args.input}", file=sys.stderr)
        return 2

    records = load(args.input)
    captions = [r for r in records if r.get("kind") == "caption"]
    audios = [r for r in records if r.get("kind") == "audio"]

    if not captions and not audios:
        print("집계할 레코드가 없다. LATENCY_LOG_PATH 를 켜고 세션을 돌렸는지 확인할 것.", file=sys.stderr)
        return 1

    lines = [
        "# UniVoice 실시간 지연 실측",
        "",
        f"- 입력: `{args.input}`",
        f"- 자막 세그먼트 {len(captions)}건 / 음성 잡 {len(audios)}건",
        "- 시간 기준: `time.monotonic()`, 워커 프로세스 내부 계측",
        "- \"발화 종료\"는 STT 오디오 타임라인(offset+duration)으로 역산한 시각이다.",
        "  학생 단말의 렌더링·재생 지연은 포함하지 않는다.",
        "",
    ]
    lines += section("자막 경로", captions, CAPTION_STAGES, CAPTION_TOTALS, args.min_samples)
    lines += section("음성 경로", audios, AUDIO_STAGES, AUDIO_TOTALS, args.min_samples)

    report = "\n".join(lines)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {args.output}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
