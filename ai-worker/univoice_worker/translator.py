"""Translator — OpenAI(또는 Azure OpenAI) 다국어 동시 번역.

아키텍처 가이드:
  - 한 번의 호출로 여러 언어를 동시에 번역 (호출 단위 = 세션 × 언어, 학생 수 무관)
  - Structured Output(JSON Schema)으로 파싱 실패 없이 안정적 결과
  - 프롬프트에 glossary + (있으면) RAG context 를 포함

target_locales 는 세션마다 다르므로, 그 세션의 locale 들을 required 키로 갖는
JSON Schema 를 동적으로 만들어 strict 모드로 강제한다.
"""

import json
import logging

from .config import WorkerConfig
from .glossary import GlossaryEntry
from .rag import RagClient

logger = logging.getLogger(__name__)


class Translator:
    def __init__(self, config: WorkerConfig, target_locales: list[str], glossary: list[GlossaryEntry]) -> None:
        self._config = config
        self._locales = target_locales
        self._glossary = glossary
        self._glossary_terms = [g.term for g in glossary]
        self._schema = self._build_schema(target_locales)
        self._client = self._build_client(config)
        self._model = (
            config.azure_openai_deployment
            if config.translate_provider == "azure"
            else config.openai_model
        )

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
        lines = [
            "당신은 한국 대학 강의를 실시간 통역하는 번역기다.",
            "입력은 교수의 한국어 발화 한 문장이다.",
            f"이를 다음 언어들로 각각 번역하라: {', '.join(self._locales)}.",
            "구어체 강의 톤을 유지하고, 의미를 왜곡하지 말 것.",
        ]
        if self._glossary:
            lines.append("\n[전공 용어집] 아래 용어는 반드시 지정된 번역을 사용하라:")
            for g in self._glossary:
                if g.translations:
                    pairs = ", ".join(f"{loc}={t}" for loc, t in g.translations.items())
                    hint = f"- {g.term}"
                    if g.definition:
                        hint += f" ({g.definition})"
                    hint += f" → {pairs}"
                    lines.append(hint)
        return "\n".join(lines)

    def detect_glossary_hits(self, sentence: str) -> list[str]:
        """문장에 등장한 glossary 용어 목록 (RAG Trigger 판단 및 context 힌트용)."""
        return [term for term in self._glossary_terms if term and term in sentence]

    async def translate(self, sentence: str, rag_context: str | None) -> dict[str, str]:
        user_content = sentence
        if rag_context:
            user_content = (
                f"[강의자료 문맥 — 번역 정확도 보정용, 그대로 출력하지 말 것]\n{rag_context}\n\n"
                f"[번역할 문장]\n{sentence}"
            )

        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_schema", "json_schema": self._schema},
            temperature=0.2,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.error("번역 JSON 파싱 실패: %r", content)
            return {}
        # 스키마상 모든 locale 이 채워지지만, 방어적으로 문자열만 남긴다
        return {loc: str(data.get(loc, "")) for loc in self._locales}
