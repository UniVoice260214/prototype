"""원본 자료 → data/chunks/chunks.jsonl 청킹.

원본은 전공 단위로 분리되어 있다 (data/raw/{ai,Humanities_Social_Sciences}/).
전공별 RAG가 섞이지 않도록 doc_type과 chunk_id prefix를 전공마다 다르게 부여한다.

자료별 규칙:
- I2A_*.pdf (강의 슬라이드): 같은 제목의 연속 슬라이드 병합, 50자 미만 제외
- *_개념_지식자료.pdf (문서형): 소제목 단위, 500토큰 초과 시만 overlap 분할
- *_입문_교재.pdf (교재형): '제N장'+'N.M 절' 단위 청킹, 요약/핵심용어 별도 chunk
- ai_glossary*.json: 용어당 1 chunk, 필드명 포함 텍스트로 변환

전공별 doc_type / chunk_id prefix:
| 전공 | 자료 | doc_type | prefix |
| AI | 개념 지식자료 | concept_doc | concept_ |
| AI | 입문 교재 | textbook | tb_ |
| AI | 용어사전 | glossary | glossary_ |
| 인문사회 | 개념 지식자료 | hss_concept_doc | hssconcept_ |
| 인문사회 | 입문 교재 | hss_textbook | hsstb_ |
| 인문사회 | 국어학개론 강의자료 | korling_lecture_slide | korlec_ |
| 인문사회 | 종교사회학 강의자료 | relsoc_lecture_slide | rellec_ |
| 바이오 | 입문 교재 | bme_textbook | bmetb_ |
| 바이오 | 분자생물학 강의자료 | molbio_lecture_slide | biolec_ |

전공 RAG는 전공 단위, 강의 RAG는 **과목 단위**로 인덱스를 나눈다
(config.INDEX_SUBSETS의 lecture_* 항목).

실행: python src/ingest.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    CHUNKS_PATH,
    DATA_RAW_AI_DIR,
    DATA_RAW_BME_DIR,
    DATA_RAW_DISTRACTOR_DIR,
    DATA_RAW_HSS_DIR,
)

# ── 공통 ──────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    chunk_id: str
    source: str
    doc_type: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """한국어 위주 텍스트의 대략적 토큰 수 (문자 수 / 2)."""
    return max(1, len(text) // 2)


# ── (1) 강의 슬라이드 PDF ─────────────────────────────────────────────

WEEK_RE = re.compile(r"^Week\s*(\d+)", re.IGNORECASE)
MIN_SLIDE_CHARS = 50


def ingest_lecture_pdf(
    path: Path, *, doc_type: str = "lecture_slide", id_prefix: str | None = None
) -> list[Chunk]:
    """페이지 상단 'WeekN' 마커 다음 줄이 슬라이드 제목.

    같은 제목의 연속 슬라이드는 병합, 텍스트가 빈약한 페이지는 조용히 스킵.
    """
    # 페이지별 (page_no, week, title, body) 수집
    slides: list[tuple[int, str, str, str]] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                continue  # 추출 실패 페이지는 스킵
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if len(lines) < 2:
                continue
            week_match = WEEK_RE.match(lines[0])
            if not week_match:
                continue  # 표지 등 Week 마커 없는 페이지
            week = f"Week{week_match.group(1)}"
            title = lines[1]
            body = "\n".join(lines[2:])
            slides.append((page_no, week, title, body))

    # 같은 제목의 연속 슬라이드 병합
    doc_short = id_prefix or _lecture_short_name(path.name)
    chunks: list[Chunk] = []
    i = 0
    while i < len(slides):
        page_no, week, title, body = slides[i]
        pages = [page_no]
        bodies = [body] if body else []
        j = i + 1
        while j < len(slides) and slides[j][2] == title and slides[j][0] == pages[-1] + 1:
            pages.append(slides[j][0])
            if slides[j][3]:
                bodies.append(slides[j][3])
            j += 1
        i = j

        merged = f"[{week}] {title}\n" + "\n".join(bodies)
        if len(merged) < MIN_SLIDE_CHARS:
            continue  # 제목+그림만 있는 슬라이드
        chunks.append(
            Chunk(
                chunk_id=f"{doc_short}_p{pages[0]:02d}_{pages[-1]:02d}",
                source=path.name,
                doc_type=doc_type,
                text=merged,
                metadata={
                    "week": week,
                    "slide_title": title,
                    "page_range": [pages[0], pages[-1]],
                },
            )
        )
    return chunks


def _lecture_short_name(filename: str) -> str:
    match = re.search(r"Lecture(\d+)", filename)
    return f"lec{match.group(1)}" if match else Path(filename).stem


# ── (1b) 일반 강의 슬라이드 PDF (Week 마커 없는 실제 강의자료) ─────────
# KOCW에서 받은 실제 강의자료는 덱마다 머리글 규칙이 달라 I2A용 'WeekN' 규칙이
# 통하지 않는다. 페이지=슬라이드로 보고 첫 줄을 제목으로 삼는 공용 파서를 두고,
# 덱별 차이는 header_fn / drop_res / section_re로 주입한다.

# 문장부호만 남은 줄 — 괄호·따옴표가 본문과 다른 baseline에 그려져 별도 줄로
# 추출되는 PDF가 있다(종교사회학 덱). 정보가 없으므로 버린다.
PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$")


def _clean_slide_lines(
    text: str, drop_res: tuple[re.Pattern[str], ...], drop_single_char: bool
) -> list[str]:
    """페이지 텍스트에서 잡음 줄을 걷어낸다.

    drop_single_char는 세로쓰기 사이드바('L','e','c',...가 한 줄씩 추출되는
    분자생물학 덱)를 위한 것이라 덱별로 켠다 — 국어학 덱의 한 자리 숫자는
    대단원 번호라서 지우면 안 된다.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if drop_single_char and len(line) <= 1:
            continue
        if PUNCT_ONLY_RE.match(line):
            continue
        if any(pattern.search(line) for pattern in drop_res):
            continue
        lines.append(line)
    return lines


def _default_slide_header(lines: list[str]) -> tuple[str, list[str]]:
    return lines[0], lines[1:]


def ingest_slide_deck_pdf(
    path: Path,
    *,
    doc_type: str,
    id_prefix: str,
    deck_label: str = "",
    drop_res: tuple[re.Pattern[str], ...] = (),
    drop_single_char: bool = False,
    header_fn: Any = None,
) -> list[Chunk]:
    """페이지 첫 줄=제목, 나머지=본문. 같은 제목의 연속 슬라이드는 병합.

    deck_label(과목·차시)을 chunk 본문 머리에 붙여, 슬라이드 제목만으로는
    어느 수업인지 알 수 없는 조각도 맥락을 갖게 한다. AI 슬라이드의 '[Week3]'
    접두와 같은 역할이다. 덱 안의 대단원은 제목 규칙이 덱마다 제각각이라
    추적하지 않는다 — 잘못된 단원명이 본문에 섞이면 임베딩까지 오염된다.
    """
    header = header_fn or _default_slide_header
    slides: list[tuple[int, str, str]] = []  # (page_no, title, body)
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            lines = _clean_slide_lines(text, drop_res, drop_single_char)
            if not lines:
                continue
            title, body_lines = header(lines)
            slides.append((page_no, title, "\n".join(body_lines)))

    chunks: list[Chunk] = []
    i = 0
    while i < len(slides):
        page_no, title, body = slides[i]
        pages = [page_no]
        bodies = [body] if body else []
        j = i + 1
        while j < len(slides) and slides[j][1] == title and slides[j][0] == pages[-1] + 1:
            pages.append(slides[j][0])
            if slides[j][2]:
                bodies.append(slides[j][2])
            j += 1
        i = j

        head = f"[{deck_label}] {title}" if deck_label else title
        merged = f"{head}\n" + "\n".join(bodies)
        if len(merged) < MIN_SLIDE_CHARS:
            continue  # 제목·그림만 있는 슬라이드
        base_id = f"{id_prefix}_p{pages[0]:02d}_{pages[-1]:02d}"
        for part_no, part_text in enumerate(
            _split_with_overlap(merged, MAX_SECTION_TOKENS, OVERLAP_TOKENS)
        ):
            suffix = f"_{part_no + 1}" if part_no > 0 else ""
            chunks.append(
                Chunk(
                    chunk_id=f"{base_id}{suffix}",
                    source=path.name,
                    doc_type=doc_type,
                    text=part_text,
                    metadata={
                        "lecture": deck_label,
                        "slide_title": title,
                        "page_range": [pages[0], pages[-1]],
                    },
                )
            )
    return chunks


# 국어학개론 덱: '1 음운론의 주요 개념' / '2'(대단원 번호) / '1) 음절이란...'
# 3단 머리글. 첫 줄 앞의 숫자는 장식이고 실제 번호는 둘째 줄에 홀로 온다.
KOR_HEAD_RE = re.compile(r"^\d+\s+(\S.*)$")
KOR_NUM_RE = re.compile(r"^\d+$")


def _korling_slide_header(lines: list[str]) -> tuple[str, list[str]]:
    if len(lines) >= 3 and KOR_NUM_RE.match(lines[1]):
        head_match = KOR_HEAD_RE.match(lines[0])
        if head_match:
            unit = f"{lines[1]}. {head_match.group(1)}"
            return f"{unit} — {lines[2]}", lines[3:]
    return _default_slide_header(lines)


# 분자생물학 덱: 매 페이지 하단 기관명 푸터 + 세로쓰기 사이드바가 섞인다.
MOLBIO_FOOTER_RE = re.compile(r"^Konyang Univ\./|Lecture materials for Molecular Biology")


# ── (2) 문서형 PDF ────────────────────────────────────────────────────

CHAPTER_RE = re.compile(r"^(\d+)장\.\s*(.+)$")
FOOTER_RE = re.compile(r"^인공지능 개념 지식자료\s*\d*$")
# 인문사회 개념 지식자료는 머리글이 '제목 · 쪽번호' 형태
HSS_FOOTER_RE = re.compile(r"^인문사회 개념 지식자료\s*·?\s*\d*$")
MAX_SECTION_TOKENS = 500
OVERLAP_TOKENS = 50


def ingest_concept_pdf(
    path: Path,
    *,
    doc_type: str = "concept_doc",
    id_prefix: str = "concept",
    footer_re: re.Pattern[str] = FOOTER_RE,
) -> list[Chunk]:
    """'N장. 제목' 헤더 아래 소제목-본문 구조를 소제목 단위로 청킹."""
    with pdfplumber.open(path) as pdf:
        raw_lines: list[str] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            raw_lines.extend(ln.strip() for ln in text.splitlines())
    lines = [ln for ln in raw_lines if ln and not footer_re.match(ln)]

    # 장 헤더 / 소제목 / 본문 분리
    sections: list[tuple[str, str, list[str]]] = []  # (chapter, section_title, body_lines)
    chapter = "개요"
    current_title: str | None = None
    current_body: list[str] = []
    prev_line_closed = True  # 직전 줄이 문장 종결('.')로 끝났는지

    def flush() -> None:
        nonlocal current_title, current_body
        if current_title and current_body:
            sections.append((chapter, current_title, current_body))
        current_title, current_body = None, []

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        ch_match = CHAPTER_RE.match(line)
        if ch_match:
            flush()
            title = line
            # 헤더가 줄바꿈으로 잘린 경우 다음 줄 이어붙임 (예: "...경사하강법," / "학습률")
            while title.rstrip().endswith((",", ":", "·")) and idx + 1 < len(lines):
                idx += 1
                title += " " + lines[idx]
            chapter = title
            prev_line_closed = True
            idx += 1
            continue
        # 소제목 판정: 직전 줄이 문장 종결 후 + 짧고 + 마침표로 끝나지 않는 줄
        is_title = prev_line_closed and len(line) <= 45 and not line.endswith(".")
        if is_title:
            flush()
            current_title = line
        else:
            current_body.append(line)
        prev_line_closed = line.endswith(".")
        idx += 1
    flush()

    # 문서 첫머리(제목/개요 이전) 잡음 정리: 소제목 없이 시작한 본문은 flush에서 이미 제외됨
    chunks: list[Chunk] = []
    for chapter_title, section_title, body_lines in sections:
        body = " ".join(body_lines)
        full_text = f"{section_title}\n{body}"
        ch_num_match = CHAPTER_RE.match(chapter_title)
        ch_no = int(ch_num_match.group(1)) if ch_num_match else 0
        base_id = f"{id_prefix}_ch{ch_no}"
        for part_no, part_text in enumerate(
            _split_with_overlap(full_text, MAX_SECTION_TOKENS, OVERLAP_TOKENS)
        ):
            suffix = f"_{part_no + 1}" if part_no > 0 else ""
            chunks.append(
                Chunk(
                    chunk_id=f"{base_id}_s{_section_index(chunks, base_id)}{suffix}",
                    source=path.name,
                    doc_type=doc_type,
                    text=part_text,
                    metadata={"chapter": chapter_title, "section_title": section_title},
                )
            )
    return chunks


# ── (2b) 교재형 PDF (인공지능_입문_교재.pdf) ──────────────────────────

TB_CHAPTER_RE = re.compile(r"^제(\d+)장$")
TB_PART_RE = re.compile(r"^제\d+부\s")
TB_SECTION_RE = re.compile(r"^(\d+)\.(\d+)\s+(\S.*)$")
TB_FOOTER_RE = re.compile(r"^인공지능 입문\s*\d+$")
HSS_TB_FOOTER_RE = re.compile(r"^인문사회 입문\s*\d+$")
BME_TB_FOOTER_RE = re.compile(r"^바이오의생명공학 입문\s*\d+$")
TB_SUMMARY_HEADER = "이 장의 요약"
TB_TERMS_HEADER = "핵심 용어"


def ingest_textbook_pdf(
    path: Path,
    *,
    doc_type: str = "textbook",
    id_prefix: str = "tb",
    footer_re: re.Pattern[str] = TB_FOOTER_RE,
) -> list[Chunk]:
    """'제N장' + 'N.M 절' 구조의 교재를 절 단위로 청킹.

    장별로 개요(intro)/절/'이 장의 요약'/'핵심 용어'를 각각 chunk로 만들고,
    500토큰 초과 시에만 overlap 분할한다. 표지·목차·부(部) 표지는 제외.
    """
    with pdfplumber.open(path) as pdf:
        lines: list[str] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                ln = raw.strip()
                if ln and not footer_re.match(ln):
                    lines.append(ln)

    # 첫 '제N장' 이전(표지/목차)은 버림
    start = next((i for i, ln in enumerate(lines) if TB_CHAPTER_RE.match(ln)), None)
    if start is None:
        return []
    lines = lines[start:]

    # 장 단위 상태기계: intro → (절 본문)* → 요약 → 핵심 용어
    chapters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    block = "intro"
    i = 0
    while i < len(lines):
        line = lines[i]
        ch_match = TB_CHAPTER_RE.match(line)
        if ch_match and i + 1 < len(lines):
            current = {
                "no": int(ch_match.group(1)),
                "title": lines[i + 1],
                "intro": [],
                "sections": [],  # [sec_no, sec_title, body_lines]
                "summary": [],
                "terms": [],
            }
            chapters.append(current)
            block = "intro"
            i += 2
            continue
        if current is None or TB_PART_RE.match(line):
            i += 1  # 부(部) 표지 라인 스킵
            continue
        sec_match = TB_SECTION_RE.match(line)
        if sec_match and int(sec_match.group(1)) == current["no"]:
            current["sections"].append(
                [int(sec_match.group(2)), sec_match.group(3), []]
            )
            block = "section"
        elif line == TB_SUMMARY_HEADER:
            block = "summary"
        elif line == TB_TERMS_HEADER:
            block = "terms"
        elif block == "summary":
            current["summary"].append(line)
        elif block == "terms":
            current["terms"].append(line)
        elif block == "section" and current["sections"]:
            current["sections"][-1][2].append(line)
        else:
            current["intro"].append(line)
        i += 1

    # 장별 chunk 생성
    chunks: list[Chunk] = []
    for ch in chapters:
        ch_no: int = ch["no"]
        base = f"{id_prefix}_ch{ch_no:02d}"
        header = f"[제{ch_no}장 {ch['title']}]"
        meta_base = {"chapter": f"제{ch_no}장 {ch['title']}"}

        if ch["intro"]:
            chunks.append(
                Chunk(
                    chunk_id=f"{base}_intro",
                    source=path.name,
                    doc_type=doc_type,
                    text=f"{header} 개요\n" + " ".join(ch["intro"]),
                    metadata={**meta_base, "section_title": "개요"},
                )
            )
        for sec_no, sec_title, body_lines in ch["sections"]:
            full_text = f"{header} {sec_title}\n" + " ".join(body_lines)
            for part_no, part_text in enumerate(
                _split_with_overlap(full_text, MAX_SECTION_TOKENS, OVERLAP_TOKENS)
            ):
                suffix = f"_{part_no + 1}" if part_no > 0 else ""
                chunks.append(
                    Chunk(
                        chunk_id=f"{base}_s{sec_no}{suffix}",
                        source=path.name,
                        doc_type=doc_type,
                        text=part_text,
                        metadata={**meta_base, "section_title": sec_title},
                    )
                )
        if ch["summary"]:
            chunks.append(
                Chunk(
                    chunk_id=f"{base}_summary",
                    source=path.name,
                    doc_type=doc_type,
                    text=f"{header} 이 장의 요약\n" + "\n".join(ch["summary"]),
                    metadata={**meta_base, "section_title": TB_SUMMARY_HEADER},
                )
            )
        if ch["terms"]:
            full_text = f"{header} 핵심 용어\n" + " ".join(ch["terms"])
            for part_no, part_text in enumerate(
                _split_with_overlap(full_text, MAX_SECTION_TOKENS, OVERLAP_TOKENS)
            ):
                suffix = f"_{part_no + 1}" if part_no > 0 else ""
                chunks.append(
                    Chunk(
                        chunk_id=f"{base}_terms{suffix}",
                        source=path.name,
                        doc_type=doc_type,
                        text=part_text,
                        metadata={**meta_base, "section_title": TB_TERMS_HEADER},
                    )
                )
    return chunks


# ── (4) 방해물 코퍼스 (data/raw_distractor/*.pdf) ─────────────────────


def ingest_distractor_pdfs(directory: Path) -> list[Chunk]:
    """방해물 PDF를 같은 규칙으로 청킹 (doc_type='distractor', 정답 불가).

    'WeekN' 마커가 있으면 슬라이드 규칙, 없으면 문서형 규칙을 적용한다.
    """
    if not directory.exists() or not any(directory.glob("*.pdf")):
        print(f"⚠️  방해물 PDF 없음: {directory} — distractor 없이 진행")
        return []

    chunks: list[Chunk] = []
    for pdf_path in sorted(directory.glob("*.pdf")):
        prefix = f"distr_{_slug(pdf_path.stem)}"
        doc_chunks = ingest_lecture_pdf(
            pdf_path, doc_type="distractor", id_prefix=prefix
        )
        rule = "slide"
        if not doc_chunks:  # Week 마커 없음 → 문서형 규칙
            doc_chunks = ingest_concept_pdf(
                pdf_path, doc_type="distractor", id_prefix=prefix
            )
            rule = "doc"
        print(f"[ingest] distractor {pdf_path.name}: {len(doc_chunks)}개 ({rule} 규칙)")
        chunks.extend(doc_chunks)
    return chunks


def _slug(stem: str) -> str:
    return re.sub(r"\W+", "_", stem).strip("_")[:24]


def _section_index(existing: list[Chunk], base_id: str) -> int:
    return sum(1 for c in existing if c.chunk_id.startswith(base_id + "_s")) + 1


def _split_with_overlap(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """max_tokens 초과 시에만 문장 경계 기준으로 overlap 분할."""
    if estimate_tokens(text) <= max_tokens:
        return [text]
    sentences = re.split(r"(?<=\.)\s+", text)
    parts: list[str] = []
    current = ""
    for sent in sentences:
        if current and estimate_tokens(current + " " + sent) > max_tokens:
            parts.append(current)
            # 마지막 overlap_tokens(문자 기준 2배)만큼 앞부분에 이어붙임
            current = current[-(overlap_tokens * 2):] + " " + sent
        else:
            current = f"{current} {sent}".strip()
    if current:
        parts.append(current)
    return parts


# ── (3) 용어사전 JSON ─────────────────────────────────────────────────


def ingest_glossary(path: Path) -> list[Chunk]:
    """용어당 정확히 1 chunk. 필드명을 포함한 서술형 텍스트로 변환."""
    data = json.loads(path.read_text(encoding="utf-8"))
    terms: list[dict[str, Any]] = data["terms"]
    id_to_ko = {t["id"]: t["term_ko"] for t in terms}

    chunks: list[Chunk] = []
    for term in terms:
        lines = [f"용어: {term['term_ko']}"]
        abbr = term.get("abbr") or ""
        en = term.get("term_en") or ""
        lines.append(f"영문명: {en} ({abbr})" if abbr else f"영문명: {en}")
        lines.append(f"분야: {term.get('category', '')}")
        lines.append(f"정의: {term.get('short_definition_ko', '')}")
        lines.append(f"상세 설명: {term.get('detailed_explanation_ko', '')}")
        if term.get("how_it_works_ko"):
            lines.append(f"작동 원리: {term['how_it_works_ko']}")
        if term.get("purpose_ko"):
            lines.append(f"사용 목적: {term['purpose_ko']}")
        if term.get("key_points"):
            lines.append(f"핵심 사항: {' '.join(term['key_points'])}")
        if term.get("disambiguation_ko"):
            lines.append(f"구분: {term['disambiguation_ko']}")
        related = [id_to_ko.get(rid, rid) for rid in term.get("related_terms", [])]
        if related:
            lines.append(f"관련 용어: {', '.join(related)}")

        chunks.append(
            Chunk(
                chunk_id=f"glossary_{term['id']}",
                source=path.name,
                doc_type="glossary",
                text="\n".join(lines),
                metadata={
                    "term_ko": term["term_ko"],
                    "term_en": term.get("term_en", ""),
                    "aliases": term.get("aliases", []),
                },
            )
        )
    return chunks


# ── 전공별 수집 ───────────────────────────────────────────────────────


def ingest_ai_major() -> list[Chunk]:
    """data/raw/ai/ — 강의 슬라이드 + 개념 지식자료 + 입문 교재 + 용어사전."""
    chunks: list[Chunk] = []
    for pdf_path in sorted(DATA_RAW_AI_DIR.glob("I2A_*.pdf")):
        chunks.extend(ingest_lecture_pdf(pdf_path))
    concept_path = DATA_RAW_AI_DIR / "인공지능_개념_지식자료.pdf"
    if concept_path.exists():
        chunks.extend(ingest_concept_pdf(concept_path))
    textbook_path = DATA_RAW_AI_DIR / "인공지능_입문_교재.pdf"
    if textbook_path.exists():
        chunks.extend(ingest_textbook_pdf(textbook_path))
    glossary_paths = sorted(DATA_RAW_AI_DIR.glob("ai_glossary*.json"))
    if glossary_paths:
        chunks.extend(ingest_glossary(glossary_paths[0]))
    return chunks


def ingest_hss_major() -> list[Chunk]:
    """data/raw/Humanities_Social_Sciences/ — 개념 지식자료 + 입문 교재.

    AI 전공과 인덱스가 섞이지 않도록 doc_type(hss_*)과 chunk_id prefix(hss*)를
    따로 쓴다. 용어사전은 아직 없다.
    """
    chunks: list[Chunk] = []
    if not DATA_RAW_HSS_DIR.exists():
        print(f"⚠️  인문사회 자료 없음: {DATA_RAW_HSS_DIR}")
        return chunks
    concept_path = DATA_RAW_HSS_DIR / "인문사회_개념_지식자료.pdf"
    if concept_path.exists():
        chunks.extend(
            ingest_concept_pdf(
                concept_path,
                doc_type="hss_concept_doc",
                id_prefix="hssconcept",
                footer_re=HSS_FOOTER_RE,
            )
        )
    textbook_path = DATA_RAW_HSS_DIR / "인문사회_입문_교재.pdf"
    if textbook_path.exists():
        chunks.extend(
            ingest_textbook_pdf(
                textbook_path,
                doc_type="hss_textbook",
                id_prefix="hsstb",
                footer_re=HSS_TB_FOOTER_RE,
            )
        )
    chunks.extend(ingest_hss_lectures())
    return chunks


def ingest_hss_lectures() -> list[Chunk]:
    """인문사회 강의자료 — 과목이 둘이라 doc_type/인덱스를 과목별로 나눈다.

    Korean_lecture07.pdf : 국어학개론(허용) 4주차 '한국어 말소리의 체계(1)'
    hss_lecture3.pdf     : 종교사회학(남은경) 2강 '종교사회학의 이해'
    """
    chunks: list[Chunk] = []
    korling_path = DATA_RAW_HSS_DIR / "Korean_lecture07.pdf"
    if korling_path.exists():
        chunks.extend(
            ingest_slide_deck_pdf(
                korling_path,
                doc_type="korling_lecture_slide",
                id_prefix="korlec",
                deck_label="국어학개론 4주차 · 한국어 말소리의 체계(1)",
                header_fn=_korling_slide_header,
            )
        )
    relsoc_path = DATA_RAW_HSS_DIR / "hss_lecture3.pdf"
    if relsoc_path.exists():
        chunks.extend(
            ingest_slide_deck_pdf(
                relsoc_path,
                doc_type="relsoc_lecture_slide",
                id_prefix="rellec",
                deck_label="종교사회학 2강 · 종교사회학의 이해",
            )
        )
    return chunks


def ingest_bme_major() -> list[Chunk]:
    """data/raw/Biomedical_Bioengineering/ — 입문 교재.

    교재 옆의 `*_메타.json`(build_bme_textbook.py가 생성)에서 장별 분야 태그를
    읽어 chunk metadata의 field/field_en에 채운다. 파일이 없으면 태그 없이 진행.
    """
    chunks: list[Chunk] = []
    if not DATA_RAW_BME_DIR.exists():
        print(f"⚠️  바이오의생명공학 자료 없음: {DATA_RAW_BME_DIR}")
        return chunks

    concept_path = DATA_RAW_BME_DIR / "바이오의생명공학_개념_지식자료.pdf"
    if concept_path.exists():
        chunks.extend(
            ingest_concept_pdf(
                concept_path,
                doc_type="bme_concept_doc",
                id_prefix="bmeconcept",
                footer_re=re.compile(r"^바이오의생명공학 개념 지식자료\s*·?\s*\d*$"),
            )
        )
    textbook_path = DATA_RAW_BME_DIR / "바이오의생명공학_입문_교재.pdf"
    if textbook_path.exists():
        chunks.extend(
            ingest_textbook_pdf(
                textbook_path,
                doc_type="bme_textbook",
                id_prefix="bmetb",
                footer_re=BME_TB_FOOTER_RE,
            )
        )
        _attach_field_metadata(chunks, textbook_path)
        chunks = _split_key_terms_into_chunks(chunks, textbook_path)

    # 강의자료: bio_lecture9.pdf — 분자생물학(이우일) 9차시 'Molecular Cloning'.
    # 교재 chunk에만 분야 태그를 붙이도록 _attach_field_metadata 뒤에서 합친다.
    molbio_path = DATA_RAW_BME_DIR / "bio_lecture9.pdf"
    if molbio_path.exists():
        chunks.extend(
            ingest_slide_deck_pdf(
                molbio_path,
                doc_type="molbio_lecture_slide",
                id_prefix="biolec",
                deck_label="분자생물학 9차시 · Molecular Cloning",
                drop_res=(MOLBIO_FOOTER_RE,),
                drop_single_char=True,
            )
        )
    return chunks


CH_NO_RE = re.compile(r"_ch(\d+)")
TERMS_CHUNK_RE = re.compile(r"^(.+)_ch(\d+)_terms(?:_\d+)?$")


def _attach_field_metadata(chunks: list[Chunk], textbook_path: Path) -> None:
    """사이드카 JSON의 장별 분야 태그를 chunk metadata에 붙인다."""
    meta_path = textbook_path.with_name(textbook_path.stem + "_메타.json")
    if not meta_path.exists():
        print(f"⚠️  분야 메타데이터 없음: {meta_path.name} — field 태그 없이 진행")
        return
    by_chapter = json.loads(meta_path.read_text(encoding="utf-8"))["chapters"]
    tagged = 0
    for chunk in chunks:
        match = CH_NO_RE.search(chunk.chunk_id)
        if not match:
            continue
        info = by_chapter.get(str(int(match.group(1))))
        if not info:
            continue
        chunk.metadata["field"] = info.get("field", "")
        chunk.metadata["field_en"] = info.get("field_en", "")
        tagged += 1
    print(f"[ingest] 분야 태그 부착: {tagged}/{len(chunks)}개 chunk")


def _split_key_terms_into_chunks(chunks: list[Chunk], textbook_path: Path) -> list[Chunk]:
    """장별 "핵심 용어" 통짜 chunk를 용어당 1 chunk로 쪼갠다.

    ingest_textbook_pdf()는 PDF에서 추출한 텍스트만으로 "핵심 용어" 절 전체를
    통짜 chunk 1~3개로 만든다 — 장별 정의형 질의(예: "PCR이 뭐예요?")에서 상관없는
    용어 11개가 함께 딸려 들어와 노이즈가 된다. PDF 렌더링에서는 용어 텍스트 자체가
    줄바꿈될 수 있어(예: 표 셀에서 "인지질 이중층(phospholipid" / "bilayer)"로 잘림)
    추출된 PDF 텍스트만으로는 용어 경계를 안정적으로 복원할 수 없으므로, 대신 교재를
    만든 원본 데이터(장별 key_terms 리스트, term/desc 필드 — 새로 짓지 않고 이미 있는
    내용을 그대로 씀)를 사이드카 JSON(_attach_field_metadata와 같은 파일)에서 읽어
    정확한 용어/정의로 대체한다.

    사이드카가 없거나 특정 장에 key_terms가 없으면 그 장은 기존 통짜 chunk를 그대로
    둔다 — 사이드카 없이 업로드되는 임의의 교재 PDF에서도 안전하게 동작한다.
    """
    meta_path = textbook_path.with_name(textbook_path.stem + "_메타.json")
    if not meta_path.exists():
        return chunks
    by_chapter = json.loads(meta_path.read_text(encoding="utf-8"))["chapters"]

    result: list[Chunk] = []
    already_split: set[str] = set()
    split_chapters = 0
    split_terms = 0
    for chunk in chunks:
        match = TERMS_CHUNK_RE.match(chunk.chunk_id)
        if not match:
            result.append(chunk)
            continue
        base, ch_no_str = match.group(1), match.group(2)
        info = by_chapter.get(str(int(ch_no_str)))
        key_terms = info.get("key_terms") if info else None
        if not key_terms:
            result.append(chunk)  # 사이드카에 이 장의 key_terms가 없으면 그대로 유지
            continue
        if ch_no_str in already_split:
            continue  # 같은 장의 overlap 연속 조각(_terms_1, _terms_2, ...) — 이미 대체함
        already_split.add(ch_no_str)
        split_chapters += 1

        title = info.get("title", "")
        header = f"[제{int(ch_no_str)}장 {title}]"
        meta_base = {
            "chapter": f"제{int(ch_no_str)}장 {title}",
            "section_title": TB_TERMS_HEADER,
            "field": chunk.metadata.get("field", ""),
            "field_en": chunk.metadata.get("field_en", ""),
        }
        for term_no, term in enumerate(key_terms, start=1):
            term_text = term.get("term", "")
            if not term_text:
                continue
            desc_text = term.get("desc", "")
            result.append(
                Chunk(
                    chunk_id=f"{base}_ch{ch_no_str}_term{term_no:02d}",
                    source=chunk.source,
                    doc_type=chunk.doc_type,
                    text=f"{header} 핵심 용어: {term_text}\n정의: {desc_text}".rstrip(),
                    metadata={**meta_base, "term": term_text},
                )
            )
            split_terms += 1
    print(f"[ingest] 핵심 용어 chunk 분해: {split_chapters}개 장 → {split_terms}개 용어별 chunk")
    return result


# ── main ──────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="원본 자료 청킹")
    parser.add_argument(
        "--with-distractors",
        action="store_true",
        help="data/raw_distractor/의 PDF를 doc_type='distractor'로 추가",
    )
    args = parser.parse_args()

    all_chunks: list[Chunk] = []
    all_chunks.extend(ingest_ai_major())
    all_chunks.extend(ingest_hss_major())
    all_chunks.extend(ingest_bme_major())
    if args.with_distractors:
        all_chunks.extend(ingest_distractor_pdfs(DATA_RAW_DISTRACTOR_DIR))

    # chunk_id 중복 방지
    seen: set[str] = set()
    for chunk in all_chunks:
        if chunk.chunk_id in seen:
            raise ValueError(f"chunk_id 중복: {chunk.chunk_id}")
        seen.add(chunk.chunk_id)

    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    # 통계 출력
    print(f"총 {len(all_chunks)}개 chunk → {CHUNKS_PATH}")
    by_type: dict[str, list[int]] = {}
    for chunk in all_chunks:
        by_type.setdefault(chunk.doc_type, []).append(len(chunk.text))
    for doc_type, lengths in by_type.items():
        print(
            f"  {doc_type:15s} {len(lengths):3d}개  "
            f"평균 {sum(lengths) / len(lengths):6.0f}자  "
            f"(min {min(lengths)} / max {max(lengths)})"
        )


if __name__ == "__main__":
    main()
