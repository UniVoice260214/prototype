"""전공 lexicon — STT 오인식 교정과 PhraseList 후보 생성.

`rag-experiment/src/router.py` 의 정규화·매칭 로직을 워커로 이식한 것이다.
router.py 를 import 하지 않고 `RagRouter.export_lexicon()` 이 떨군 JSON만 읽으므로
torch/faiss 같은 무거운 의존성이 필요 없다 (router.py 상단 주석의 원래 의도).

자산 위치: ``ai-worker/rag_assets/lexicon_{ai,hss,bme}.json``
재생성:    ``cd rag-experiment && python src/router.py --major ai \
              --export ../ai-worker/rag_assets/lexicon_ai.json``

교정과 질의 정규화는 반드시 분리한다:
  - :meth:`MajorLexicon.correct_for_display` — 음차 치환만. 자막/번역 입력용.
  - :meth:`MajorLexicon.normalize_for_query`  — 음차 치환 + 필러 제거. RAG 질의 전용.

필러 제거를 자막에 쓰면 교수가 실제로 말한 단어("그러니까", "그거")가 자막에서
사라져 "자막이 강의와 다르다"는 문제를 오히려 키운다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# PhraseList 후보 우선순위 (낮을수록 먼저 채택).
# 1 은 과목 glossary(교수 직접 입력) 몫으로 비워 둔다 — build_phrase_list() 참조.
PRIORITY_COURSE_GLOSSARY = 1
PRIORITY_TRANSLITERATION = 2
PRIORITY_GLOSSARY_TERM = 3
PRIORITY_LECTURE_CONCEPT = 4

# Azure PhraseList 상한: "A phrase list shouldn't have more than 500 phrases."
# https://learn.microsoft.com/azure/ai-services/speech-service/improve-accuracy-phrase-list
DEFAULT_PHRASE_LIST_MAX_ITEMS = 500
# 총 문자 수 상한은 공식 문서에 수치가 없다. 안전 마진으로만 둔 값이다.
DEFAULT_PHRASE_LIST_MAX_CHARS = 8000

_PHRASE_MIN_LEN = 2
_PHRASE_MAX_LEN = 30

# 교정 결과가 원문 대비 이 배수를 넘으면 치환이 폭주한 것으로 보고 원문을 유지한다.
_CORRECTION_MAX_GROWTH = 3


# 받침 유무에 따라 형태가 갈리는 조사. (받침 있음 형태, 받침 없음 형태)
# 음차 치환은 앞말의 받침을 바꾸므로("백프로파게이션으로" → "역전파으로")
# 치환 직후 조사를 함께 맞춰 주지 않으면 자막에 비문이 그대로 나간다.
_PARTICLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("으로", "로"),
    ("이랑", "랑"),
    ("이라", "라"),
    ("이며", "며"),
    ("은", "는"),
    ("이", "가"),
    ("을", "를"),
    ("과", "와"),
)

_HANGUL_START = 0xAC00
_HANGUL_END = 0xD7A3
_JONGSEONG_COUNT = 28
_JONGSEONG_RIEUL = 8


def _final_consonant(ch: str) -> int | None:
    """한글 음절의 종성 인덱스. 한글이 아니면 None (판단 불가)."""
    code = ord(ch)
    if not (_HANGUL_START <= code <= _HANGUL_END):
        return None
    return (code - _HANGUL_START) % _JONGSEONG_COUNT


def fix_particles_after(text: str, term: str) -> str:
    """`term` 바로 뒤에 붙은 조사를 term 의 받침에 맞춘다.

    한글로 끝나는 용어만 다룬다. 라틴 약어(LSTM, RAG 등)는 발음 기준이라
    규칙이 불확실하므로 건드리지 않는다 — 틀리게 고치느니 두는 편이 낫다.
    """
    if not term or not text:
        return text
    jong = _final_consonant(term[-1])
    if jong is None:
        return text
    has_final = jong != 0
    is_rieul = jong == _JONGSEONG_RIEUL

    for with_final, without_final in _PARTICLE_PAIRS:
        if with_final == "으로":
            # ㄹ 받침은 '로'를 쓴다: 실로, 물로
            wanted = with_final if (has_final and not is_rieul) else without_final
        else:
            wanted = with_final if has_final else without_final
        other = without_final if wanted == with_final else with_final
        if wanted == other:
            continue
        # term 바로 뒤 + 조사, 그리고 그 뒤는 어절 경계여야 한다.
        pattern = re.compile(
            re.escape(term) + re.escape(other) + r"(?=[\s.,!?…\"')\]]|$)"
        )
        text = pattern.sub(term + wanted, text)
    return text


def _spaced_pattern(src: str) -> re.Pattern[str]:
    """음차 문자열을 글자 사이 공백에 관대한 정규식으로 바꾼다.

    STT 는 약어를 '지 디 피', '케이 디 씨'처럼 글자 단위로 띄어 쓰는 일이 많다.
    (router.py `_spaced_pattern` 이식)
    """
    chars = [c for c in src if not c.isspace()]
    return re.compile(r"\s*".join(re.escape(c) for c in chars))


@dataclass(frozen=True)
class MajorLexicon:
    """전공 하나의 lexicon (rag-experiment export_lexicon() 산출물)."""

    major: str
    label: str
    index_name: str
    score_threshold: float
    # 패턴(소문자) → (정식 용어, reason)
    lexicon: dict[str, tuple[str, str]] = field(default_factory=dict)
    # 음차 치환 (긴 패턴 먼저 적용)
    translit: list[tuple[re.Pattern[str], str]] = field(default_factory=list)
    # ASCII 패턴은 단어 경계 필요 ("AI" 가 "said" 에 걸리지 않도록)
    ascii_res: dict[str, re.Pattern[str]] = field(default_factory=dict)
    # 짧은 한글 패턴의 낱말 내부 오탐 예외 ('음소' ⊂ '음소거')
    exclusions: dict[str, re.Pattern[str]] = field(default_factory=dict)
    # 담화 필러 — normalize_for_query 에서만 제거한다
    fillers: list[re.Pattern[str]] = field(default_factory=list)

    # ── 로드 ──────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> "MajorLexicon":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: dict) -> "MajorLexicon":
        lexicon: dict[str, tuple[str, str]] = {}
        for entry in payload.get("lexicon", []):
            pattern = str(entry.get("pattern", "")).strip().lower()
            canonical = str(entry.get("canonical", "")).strip()
            if not pattern or not canonical:
                continue
            reason = str(entry.get("reason", "")) or "LECTURE_CONCEPT"
            # export 는 이미 glossary 우선으로 정리되어 있으므로 첫 항목만 취한다.
            lexicon.setdefault(pattern, (canonical, reason))

        translit = [
            (_spaced_pattern(src), dst)
            for src, dst in sorted(
                (payload.get("transliterations") or {}).items(),
                key=lambda kv: len(kv[0]),
                reverse=True,
            )
            if src and dst
        ]

        ascii_res = {
            key: re.compile(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])")
            for key in lexicon
            if key.isascii()
        }

        raw_exclusions = payload.get("pattern_exclusions")
        if raw_exclusions is None:
            raw_exclusions = _FALLBACK_PATTERN_EXCLUSIONS
        exclusions = {
            key: re.compile(value)
            for key, value in raw_exclusions.items()
            if key in lexicon
        }

        raw_fillers = payload.get("filler_patterns")
        if raw_fillers is None:
            raw_fillers = _FALLBACK_FILLER_PATTERNS
        fillers = [re.compile(p) for p in raw_fillers]

        return cls(
            major=str(payload.get("major", "")),
            label=str(payload.get("label", "")),
            index_name=str(payload.get("index", "")),
            score_threshold=float(payload.get("score_threshold", 0.5)),
            lexicon=lexicon,
            translit=translit,
            ascii_res=ascii_res,
            exclusions=exclusions,
            fillers=fillers,
        )

    # ── 교정 / 정규화 ─────────────────────────────────────────────────

    def correct_for_display(self, text: str) -> tuple[str, int]:
        """음차 치환만 적용한다. 필러는 절대 지우지 않는다.

        자막(sourceKo)과 번역 입력에 쓰이므로, 교수가 실제로 말한 단어를
        임의로 없애면 안 된다. 반환값은 (교정문, 치환 건수).
        """
        original = text or ""
        stripped = original.strip()
        if not stripped:
            return original, 0

        result = stripped
        fixed = 0
        replaced: list[str] = []
        for pattern, dst in self.translit:
            result, count = pattern.subn(dst, result)
            if count:
                fixed += count
                replaced.append(dst)

        if not fixed:
            return original, 0

        # 치환으로 앞말의 받침이 바뀌므로 뒤따르는 조사를 맞춘다.
        for dst in replaced:
            result = fix_particles_after(result, dst)

        result = re.sub(r"[ \t]+", " ", result).strip()
        if not result or len(result) > max(1, len(stripped)) * _CORRECTION_MAX_GROWTH:
            logger.warning(
                "lexicon 교정 결과가 비정상이라 원문을 유지한다: %r → %r", stripped, result
            )
            return original, 0
        return result, fixed

    def normalize_for_query(self, text: str) -> str:
        """음차 치환 + 담화 필러 제거. RAG 임베딩 질의 전용.

        router.py `RagRouter.normalize` 와 동일한 동작이다.
        """
        result = (text or "").strip()
        for pattern, dst in self.translit:
            result = pattern.sub(dst, result)
        for pattern in self.fillers:
            result = pattern.sub(" ", result)
        return re.sub(r"\s+", " ", result).strip()

    # ── 매칭 ──────────────────────────────────────────────────────────

    def match(self, text: str) -> list[str]:
        """문장에 등장한 정식 용어 목록. (router.py `route()` 매칭부 이식)"""
        lowered = (text or "").lower()
        if not lowered:
            return []

        matched: dict[str, str] = {}
        for pattern, (canonical, reason) in self.lexicon.items():
            ascii_re = self.ascii_res.get(pattern)
            if ascii_re is not None:
                hit = bool(ascii_re.search(lowered))
            else:
                hit = pattern in lowered
                exclusion = self.exclusions.get(pattern)
                if hit and exclusion is not None:
                    # 예외 문맥을 지운 뒤에도 남아 있어야 진짜 언급으로 본다
                    hit = pattern in exclusion.sub(" ", lowered)
            if not hit:
                continue
            if canonical not in matched or reason == "GLOSSARY_TERM":
                matched[canonical] = reason
        return sorted(matched)

    # ── PhraseList 후보 ───────────────────────────────────────────────

    def phrase_candidates(self) -> list[tuple[int, str]]:
        """(우선순위, 구문) 목록. 낮은 우선순위가 먼저 채택된다.

        음차 치환의 **결과값**(정식 표기)을 최우선으로 둔다. 이건 실제로 오인식이
        관측된 용어라 PhraseList 가중의 효과가 가장 확실하다.
        """
        candidates: list[tuple[int, str]] = []
        for _, dst in self.translit:
            candidates.append((PRIORITY_TRANSLITERATION, dst))
        for canonical, reason in self.lexicon.values():
            priority = (
                PRIORITY_GLOSSARY_TERM
                if reason == "GLOSSARY_TERM"
                else PRIORITY_LECTURE_CONCEPT
            )
            candidates.append((priority, canonical))
        return candidates


class LexiconRegistry:
    """전공별 lexicon 보관소. 워커 기동 시 1회 로드한다."""

    def __init__(self, by_major: dict[str, MajorLexicon]) -> None:
        self._by_major = by_major

    @classmethod
    def load_dir(cls, directory: Path) -> "LexiconRegistry":
        by_major: dict[str, MajorLexicon] = {}
        base = Path(directory)
        if not base.is_dir():
            logger.warning("lexicon 디렉터리 없음: %s — STT 전공 용어 교정 비활성", base)
            return cls(by_major)
        for path in sorted(base.glob("lexicon_*.json")):
            try:
                lex = MajorLexicon.load(path)
            except Exception:  # noqa: BLE001 - 자산 하나가 깨져도 워커는 떠야 한다.
                logger.exception("lexicon 로드 실패: %s", path)
                continue
            if not lex.major:
                logger.warning("lexicon 에 major 없음: %s", path)
                continue
            by_major[lex.major] = lex
            logger.info(
                "[lexicon] %s(%s): 패턴 %d개, 음차 %d개, 임계값 %.2f",
                lex.major,
                lex.label,
                len(lex.lexicon),
                len(lex.translit),
                lex.score_threshold,
            )
        if not by_major:
            logger.warning("lexicon 자산 0개: %s — STT 전공 용어 교정 비활성", base)
        return cls(by_major)

    def get(self, major: str) -> MajorLexicon | None:
        return self._by_major.get((major or "").lower())

    @property
    def majors(self) -> list[str]:
        return sorted(self._by_major)

    def __len__(self) -> int:
        return len(self._by_major)


def build_phrase_list(
    *,
    glossary_terms: list[str] | None = None,
    lexicon: MajorLexicon | None = None,
    max_items: int = DEFAULT_PHRASE_LIST_MAX_ITEMS,
    max_chars: int = DEFAULT_PHRASE_LIST_MAX_CHARS,
) -> tuple[list[str], dict[str, int]]:
    """과목 glossary + 전공 lexicon 을 Azure PhraseList 용 목록으로 합친다.

    반환값은 (구문 목록, 통계). 통계는 관측성 로그에 그대로 쓴다.
    """
    candidates: list[tuple[int, str]] = [
        (PRIORITY_COURSE_GLOSSARY, term) for term in (glossary_terms or [])
    ]
    if lexicon is not None:
        candidates.extend(lexicon.phrase_candidates())

    seen: set[str] = set()
    normalized: list[tuple[int, str]] = []
    for priority, raw in candidates:
        phrase = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not (_PHRASE_MIN_LEN <= len(phrase) <= _PHRASE_MAX_LEN):
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append((priority, phrase))

    # 우선순위 안정 정렬 — 같은 순위 안에서는 원래 순서를 지킨다.
    normalized.sort(key=lambda item: item[0])

    phrases: list[str] = []
    total_chars = 0
    for _, phrase in normalized:
        if len(phrases) >= max_items or total_chars + len(phrase) > max_chars:
            break
        phrases.append(phrase)
        total_chars += len(phrase)

    stats = {
        "glossary": len(glossary_terms or []),
        "lexicon": len(lexicon.lexicon) if lexicon is not None else 0,
        "candidates": len(candidates),
        "merged": len(phrases),
        "dropped": len(normalized) - len(phrases),
        "chars": total_chars,
    }
    return phrases, stats


# ── export 가 오래된 자산(pattern_exclusions/filler_patterns 없음)일 때의 안전망 ──
# rag-experiment/src/router.py 의 PATTERN_EXCLUSIONS / FILLER_PATTERNS 사본.
_FALLBACK_PATTERN_EXCLUSIONS: dict[str, str] = {
    "음소": r"음소거",
    "모음": r"(사진|자료|영상|링크)\s*모음|모음집|모음전",
    "수요": r"수요일",
    "번역": r"(자막|통역|실시간|기계|자동)\s*번역|번역\s*(자막|기능|앱|기)",
    "성조": r"성조기",
    "이두": r"이두박근",
}

_FALLBACK_FILLER_PATTERNS: list[str] = [
    r"^(어|음|자|그|저)\s+",
    r"그러니까\s*",
    r"뭐시기\s*",
    r"인가\s+그\s+",
    r"\s+그거\s+",
    r"\s+그게\s+",
]
