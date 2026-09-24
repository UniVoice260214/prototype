"""Translator — OpenAI(또는 Azure OpenAI) 다국어 동시 번역.

아키텍처 가이드:
  - 한 번의 호출로 여러 언어를 동시에 번역 (호출 단위 = 세션 × 언어, 학생 수 무관)
  - Structured Output(JSON Schema)으로 파싱 실패 없이 안정적 결과
  - 프롬프트에 glossary + (있으면) RAG context 를 포함

target_locales 는 세션마다 다르므로, 그 세션의 locale 들을 required 키로 갖는
JSON Schema 를 동적으로 만들어 strict 모드로 강제한다.
"""

import bisect
import itertools
import json
import logging
from dataclasses import dataclass

from .config import WorkerConfig
from .glossary import GlossaryEntry
from .lexicon import MajorLexicon
from .rag import RagClient

logger = logging.getLogger(__name__)

# 직전 발화 문맥을 몇 개까지 넘길지. 너무 길면 모델이 이전 문장을 다시 번역한다.
HISTORY_SIZE = 3
# 병렬 번역 중에는 뒤 세그먼트가 먼저 기록될 수 있어, 프롬프트에 넣는 개수보다
# 넉넉히 보관한다. 앞 세그먼트가 늦게 끼어들어도 직전 문맥이 잘려 나가지 않게.
HISTORY_KEEP = HISTORY_SIZE * 3


@dataclass
class HistoryEntry:
    """(원문, 번역) 한 쌍. 번역 호출 시작 시 번역을 비운 채 자리를 잡는다."""

    order: int
    source: str
    translation: str = ""


class Translator:
    def __init__(
        self,
        config: WorkerConfig,
        target_locales: list[str],
        glossary: list[GlossaryEntry],
        lexicon: MajorLexicon | None = None,
    ) -> None:
        self._config = config
        self._locales = target_locales
        self._glossary = glossary
        self._glossary_terms = [g.term for g in glossary]
        self._glossary_by_term = {g.term: g for g in glossary if g.term}
        self._lexicon = lexicon
        self._schema = self._build_schema(target_locales)
        self._client = self._build_client(config)
        self._model = (
            config.azure_openai_deployment
            if config.translate_provider == "azure"
            else config.openai_model
        )
        # (한국어 원문, 대표 locale 번역) — order(=세그먼트 sequence) 오름차순.
        # 파이프라인이 번역을 병렬로 돌리므로 "완료 순서"로 append 하면 순서가 꼬인다.
        # 호출 시작 시점에 order 위치로 끼워 넣고, 완료 후 번역을 채운다.
        self._history: list[HistoryEntry] = []
        # sequence 를 넘기지 않는 호출자용 순번
        self._order_counter = itertools.count(1)

    @staticmethod
    def _build_client(config: WorkerConfig):
        # openai>=1.0 : OpenAI / Azure 모두 async 클라이언트 제공
        if config.translate_provider == "azure":
            from openai import AsyncAzureOpenAI

            return AsyncAzureOpenAI(
                api_key=config.azure_openai_api_key,
                azure_endpoint=config.azure_openai_endpoint,
                api_version=config.azure_openai_api_version,
            )
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=config.openai_api_key)

    @staticmethod
    def _build_schema(locales: list[str]) -> dict:
        properties = {loc: {"type": "string"} for loc in locales}
        return {
            "name": "translations",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(locales),
                "additionalProperties": False,
            },
        }

    def _system_prompt(self) -> str:
        """세션 내내 고정인 정적 프롬프트.

        예전에는 여기에 코스 glossary 를 **전량** 나열했는데, 용어가 수백 개로
        늘면 매 요청 프롬프트가 수천 토큰으로 불어난다. 이제 이번 발화에 실제로
        등장한 용어만 user 메시지에 붙인다.
        """
        return "\n".join(
            [
                "당신은 한국 대학 강의를 실시간 통역하는 번역기다.",
                # 실제 입력은 완결 문장이 아니다. segmenter 가 글자 수/무음 기준으로
                # 문장 도중에 자르므로, '한 문장'이라고 단언하면 모델이 없는 내용을
                # 지어내 문장을 완성하려 든다.
                "입력은 실시간 STT 가 만든 발화 조각이다. 문장이 도중에 끊겨 있을 수 있다.",
                f"이를 다음 언어들로 각각 번역하라: {', '.join(self._locales)}.",
                "끊긴 채로 자연스럽게 번역하고, 없는 내용을 임의로 보충하거나 문장을 완성하지 말 것.",
                "구어체 강의 톤을 유지하고, 의미를 왜곡하지 말 것.",
                "직전 문맥이 주어지면 대명사·생략된 주어를 해석하는 데만 쓰고, 다시 번역하지 말 것.",
            ]
        )

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        """문장에 등장한 전공 용어 목록 (RAG Trigger 판단 및 번역 힌트용).

        코스 glossary 와 전공 lexicon 을 모두 본다.
        """
        hits = [term for term in self._glossary_terms if term and term in sentence]
        if self._lexicon is not None:
            seen = set(hits)
            for term in self._lexicon.match(sentence):
                if term not in seen:
                    seen.add(term)
                    hits.append(term)
        return hits

    def _glossary_hint(self, hits: list[str]) -> str:
        """이번 발화에 등장한 용어의 지정 번역만 뽑는다."""
        lines: list[str] = []
        for term in hits:
            entry = self._glossary_by_term.get(term)
            if entry is None or not entry.translations:
                continue
            pairs = ", ".join(f"{loc}={t}" for loc, t in entry.translations.items())
            hint = f"- {entry.term}"
            if entry.definition:
                hint += f" ({entry.definition})"
            lines.append(f"{hint} → {pairs}")
        if not lines:
            return ""
        return "[이번 발화의 전공 용어 — 지정된 번역을 사용하라]\n" + "\n".join(lines)

    @property
    def history(self) -> list[tuple[str, str]]:
        """(원문, 번역) 목록, sequence 순서. 진행 중인 항목은 번역이 빈 문자열이다."""
        return [(entry.source, entry.translation) for entry in self._history]

    def _reserve_history(self, sentence: str, order: int) -> HistoryEntry:
        entry = HistoryEntry(order=order, source=sentence)
        orders = [e.order for e in self._history]
        self._history.insert(bisect.bisect_right(orders, order), entry)
        if len(self._history) > HISTORY_KEEP:
            del self._history[: len(self._history) - HISTORY_KEEP]
        return entry

    def _release_history(self, entry: HistoryEntry) -> None:
        # 값 비교(remove)는 같은 문장이 반복될 때 엉뚱한 항목을 지운다 — identity 로.
        for index, existing in enumerate(self._history):
            if existing is entry:
                del self._history[index]
                return

    def _history_hint(self, before: int | None = None) -> str:
        entries = [
            e for e in self._history if before is None or e.order < before
        ][-HISTORY_SIZE:]
        if not entries:
            return ""
        lines = [f"{i}) {e.source}" for i, e in enumerate(entries, start=1)]
        return "[직전 문맥 — 참고만 하고 다시 번역하지 말 것]\n" + "\n".join(lines)

    def _build_user_content(
        self,
        sentence: str,
        rag_context: str | None,
        hits: list[str],
        *,
        order: int | None = None,
    ) -> str:
        blocks: list[str] = []
        history = self._history_hint(before=order)
        if history:
            blocks.append(history)
        glossary_hint = self._glossary_hint(hits)
        if glossary_hint:
            blocks.append(glossary_hint)
        if rag_context:
            blocks.append(
                f"[강의자료 문맥 — 번역 정확도 보정용, 그대로 출력하지 말 것]\n{rag_context}"
            )
        if not blocks:
            return sentence
        blocks.append(f"[번역할 발화]\n{sentence}")
        return "\n\n".join(blocks)

    async def translate(
        self,
        sentence: str,
        rag_context: str | None,
        glossary_hits: list[str] | None = None,
        *,
        sequence: int | None = None,
    ) -> dict[str, str]:
        hits = glossary_hits if glossary_hits is not None else self.detect_glossary_hits(sentence)
        order = sequence if sequence is not None else next(self._order_counter)
        # 프롬프트는 자기 자리를 잡기 "전"의 history 로 만든다 (자기 문장 제외).
        user_content = self._build_user_content(sentence, rag_context, hits, order=order)
        entry = self._reserve_history(sentence, order)
        try:
            result = await self._request(user_content)
        except BaseException:
            self._release_history(entry)
            raise

        primary = next((result[loc] for loc in self._locales if result.get(loc)), "")
        if primary:
            entry.translation = primary
        else:
            # 예전 동작과 같다: 번역이 비면 문맥으로 남기지 않는다.
            self._release_history(entry)
        return result

    async def _request(self, user_content: str) -> dict[str, str]:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_schema", "json_schema": self._schema},
            temperature=0.2,
            # 기본값은 600초다. 자막은 sequence 순서로 나가므로 한 번 늘어지면
            # 뒤따르는 자막이 전부 그 뒤에 줄을 선다.
            timeout=self._config.translate_timeout_sec,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.error("번역 JSON 파싱 실패: %r", content)
            return {}
        # 스키마상 모든 locale 이 채워지지만, 방어적으로 문자열만 남긴다
        return {loc: str(data.get(loc, "")) for loc in self._locales}
