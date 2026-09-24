"""STT 품질 평가 메트릭 (CER / WER).

STT 엔진 교체 후보를 비교(tools/stt_benchmark.py)할 때 쓰는 순수 함수 모음.
외부 의존성이 없어 어디서든 import 할 수 있다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_PUNCT_RE = re.compile(r"[\s.,!?;:\"'“”‘’()\[\]{}·…~\-—啊。！？、，]+")

# 실강의 전사에는 STT 출력에 없는 간투사가 섞인다 ("씁", "어", "아", "하" 등 —
# 국어학개론 실강의 전사에서 확인). 사람이 적은 정답과 STT 결과를 공정하게
# 비교하려면 양쪽 모두에서 독립 어절로 등장한 간투사를 제거한 뒤 재야 한다.
FILLER_TOKENS = frozenset(
    {"씁", "쓰읍", "음", "으음", "어", "아", "에", "엄", "흠", "하"}
)


def strip_fillers(text: str) -> str:
    """독립 어절로 등장한 간투사를 제거한다. 단어 일부('어제' 등)는 건드리지 않는다."""
    words = unicodedata.normalize("NFC", text).split()
    return " ".join(w for w in words if w not in FILLER_TOKENS)


def normalize_text(text: str) -> str:
    """비교용 정규화: 유니코드 NFC, 소문자화, 문장부호·공백 제거."""
    normalized = unicodedata.normalize("NFC", text).lower()
    return _PUNCT_RE.sub("", normalized)


def normalize_words(text: str) -> list[str]:
    """WER 용 어절 리스트: 문장부호를 공백으로 바꾼 뒤 공백 분리."""
    normalized = unicodedata.normalize("NFC", text).lower()
    return [w for w in _PUNCT_RE.split(normalized) if w]


def edit_distance(ref: list[str] | str, hyp: list[str] | str) -> int:
    """Levenshtein distance (two-row DP)."""
    if not ref:
        return len(hyp)
    if not hyp:
        return len(ref)
    previous = list(range(len(hyp) + 1))
    for i, ref_item in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, hyp_item in enumerate(hyp, start=1):
            cost = 0 if ref_item == hyp_item else 1
            current[j] = min(
                previous[j] + 1,        # deletion
                current[j - 1] + 1,     # insertion
                previous[j - 1] + cost, # substitution
            )
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str, *, drop_fillers: bool = False) -> float:
    """Character Error Rate. 한국어처럼 띄어쓰기가 흔들리는 언어의 1차 지표."""
    if drop_fillers:
        reference = strip_fillers(reference)
        hypothesis = strip_fillers(hypothesis)
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def wer(reference: str, hypothesis: str, *, drop_fillers: bool = False) -> float:
    """Word(어절) Error Rate. 엔진 간 상대 비교용 보조 지표."""
    if drop_fillers:
        reference = strip_fillers(reference)
        hypothesis = strip_fillers(hypothesis)
    ref = normalize_words(reference)
    hyp = normalize_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


@dataclass(frozen=True)
class SampleScore:
    name: str
    cer: float
    wer: float
    ref_chars: int


def aggregate_cer(scores: list[SampleScore]) -> float:
    """레퍼런스 길이로 가중한 전체 CER (샘플 길이 편차 보정)."""
    total_chars = sum(s.ref_chars for s in scores)
    if total_chars == 0:
        return 0.0
    return sum(s.cer * s.ref_chars for s in scores) / total_chars
