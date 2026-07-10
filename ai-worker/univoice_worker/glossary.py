"""Glossary 공유 타입.

Core API 의 prewarmRedis() 가 `glossary:{courseId}` 에 적재하는 JSON 배열 항목:
  { "term", "pronunciation", "definition", "translations": { locale: 번역어 } }
이 모양을 워커 전역에서 재사용하기 위해 dataclass 로 감싼다.
STT(phrase list) · Translator(용어 일관성) · TTS(lexicon) 가 공통으로 참조한다.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    pronunciation: str | None = None
    definition: str | None = None
    translations: dict[str, str] = field(default_factory=dict)


def parse_glossary(entries: list[dict]) -> list[GlossaryEntry]:
    result: list[GlossaryEntry] = []
    for e in entries:
        term = (e.get("term") or "").strip()
        if not term:
            continue
        result.append(
            GlossaryEntry(
                term=term,
                pronunciation=e.get("pronunciation"),
                definition=e.get("definition"),
                translations=e.get("translations") or {},
            )
        )
    return result
