"""원본 자료 4개 → data/chunks/chunks.jsonl 청킹.

자료별 규칙:
- I2A_*.pdf (강의 슬라이드): 같은 제목의 연속 슬라이드 병합, 50자 미만 제외
- 인공지능_개념_지식자료.pdf (문서형): 소제목 단위, 500토큰 초과 시만 overlap 분할
- ai_glossary*.json: 용어당 1 chunk, 필드명 포함 텍스트로 변환

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
from config import CHUNKS_PATH, DATA_RAW_DIR, DATA_RAW_DISTRACTOR_DIR

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


# ── (2) 문서형 PDF ────────────────────────────────────────────────────

CHAPTER_RE = re.compile(r"^(\d+)장\.\s*(.+)$")
FOOTER_RE = re.compile(r"^인공지능 개념 지식자료\s*\d*$")
MAX_SECTION_TOKENS = 500
OVERLAP_TOKENS = 50


def ingest_concept_pdf(
    path: Path, *, doc_type: str = "concept_doc", id_prefix: str = "concept"
) -> list[Chunk]:
    """'N장. 제목' 헤더 아래 소제목-본문 구조를 소제목 단위로 청킹."""
    with pdfplumber.open(path) as pdf:
        raw_lines: list[str] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            raw_lines.extend(ln.strip() for ln in text.splitlines())
    lines = [ln for ln in raw_lines if ln and not FOOTER_RE.match(ln)]

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
    for pdf_path in sorted(DATA_RAW_DIR.glob("I2A_*.pdf")):
        all_chunks.extend(ingest_lecture_pdf(pdf_path))
    concept_path = DATA_RAW_DIR / "인공지능_개념_지식자료.pdf"
    if concept_path.exists():
        all_chunks.extend(ingest_concept_pdf(concept_path))
    glossary_paths = sorted(DATA_RAW_DIR.glob("ai_glossary*.json"))
    if glossary_paths:
        all_chunks.extend(ingest_glossary(glossary_paths[0]))
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
