from __future__ import annotations

import json
from pathlib import Path

from ingest import Chunk, _split_key_terms_into_chunks


def _write_sidecar(tmp_path: Path, chapters: dict) -> Path:
    textbook_path = tmp_path / "교재.pdf"
    meta_path = textbook_path.with_name(textbook_path.stem + "_메타.json")
    meta_path.write_text(
        json.dumps({"book_title": "테스트", "source_pdf": textbook_path.name, "chapters": chapters}),
        encoding="utf-8",
    )
    return textbook_path


def _blob_chunk(chunk_id: str = "tb_ch01_terms") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source="교재.pdf",
        doc_type="bme_textbook",
        text="[제1장 제목] 핵심 용어\n세포 원핵세포 진핵세포",
        metadata={"chapter": "제1장 제목", "section_title": "핵심 용어", "field": "세포생물학", "field_en": "cell biology"},
    )


def test_splits_blob_terms_chunk_into_one_chunk_per_term(tmp_path: Path) -> None:
    textbook_path = _write_sidecar(
        tmp_path,
        {
            "1": {
                "title": "제목",
                "field": "세포생물학",
                "field_en": "cell biology",
                "key_terms": [
                    {"term": "세포(cell)", "desc": "기본 단위."},
                    {"term": "원핵세포(prokaryotic cell)", "desc": "핵막이 없는 세포."},
                ],
            }
        },
    )
    result = _split_key_terms_into_chunks([_blob_chunk()], textbook_path)

    assert [c.chunk_id for c in result] == ["tb_ch01_term01", "tb_ch01_term02"]
    assert result[0].text == "[제1장 제목] 핵심 용어: 세포(cell)\n정의: 기본 단위."
    assert result[0].metadata["term"] == "세포(cell)"
    # field/field_en 태그가 원래 blob chunk에서 이어져 붙는다.
    assert result[0].metadata["field"] == "세포생물학"
    assert result[0].metadata["field_en"] == "cell biology"
    assert result[0].doc_type == "bme_textbook"
    assert result[0].source == "교재.pdf"


def test_overlap_continuation_chunks_are_replaced_exactly_once(tmp_path: Path) -> None:
    # 긴 핵심 용어 절은 _split_with_overlap으로 _terms, _terms_1, _terms_2로 쪼개져 있었다.
    textbook_path = _write_sidecar(
        tmp_path,
        {
            "1": {
                "title": "제목",
                "key_terms": [{"term": "세포(cell)", "desc": "기본 단위."}],
            }
        },
    )
    chunks = [
        _blob_chunk("tb_ch01_terms"),
        _blob_chunk("tb_ch01_terms_1"),
        _blob_chunk("tb_ch01_terms_2"),
    ]

    result = _split_key_terms_into_chunks(chunks, textbook_path)

    assert [c.chunk_id for c in result] == ["tb_ch01_term01"]


def test_chapter_without_key_terms_keeps_original_blob_chunk(tmp_path: Path) -> None:
    textbook_path = _write_sidecar(tmp_path, {"1": {"title": "제목", "key_terms": []}})
    blob = _blob_chunk()

    result = _split_key_terms_into_chunks([blob], textbook_path)

    assert result == [blob]


def test_missing_sidecar_returns_chunks_unchanged(tmp_path: Path) -> None:
    textbook_path = tmp_path / "없는교재.pdf"  # _메타.json을 쓰지 않음
    blob = _blob_chunk()

    result = _split_key_terms_into_chunks([blob], textbook_path)

    assert result == [blob]


def test_non_terms_chunks_pass_through_untouched(tmp_path: Path) -> None:
    textbook_path = _write_sidecar(
        tmp_path,
        {"1": {"title": "제목", "key_terms": [{"term": "세포(cell)", "desc": "기본 단위."}]}},
    )
    intro = Chunk(
        chunk_id="tb_ch01_intro",
        source="교재.pdf",
        doc_type="bme_textbook",
        text="[제1장 제목] 개요\n...",
        metadata={"chapter": "제1장 제목", "section_title": "개요"},
    )
    section = Chunk(
        chunk_id="tb_ch01_s1",
        source="교재.pdf",
        doc_type="bme_textbook",
        text="[제1장 제목] 1.1 절\n...",
        metadata={"chapter": "제1장 제목", "section_title": "1.1 절"},
    )

    result = _split_key_terms_into_chunks([intro, section, _blob_chunk()], textbook_path)

    assert result[0] is intro
    assert result[1] is section
    assert result[2].chunk_id == "tb_ch01_term01"
