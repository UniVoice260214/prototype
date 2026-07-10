"""RAG 교체 지점(seam).

아키텍처 가이드의 파이프라인에서 RAG 는 "번역 직전에 강의자료 문맥을 붙이는" 단계다.
지금은 RAG 를 빼고 전체가 동작해야 하므로, 파이프라인은 아래 인터페이스에만 의존하고
기본 구현으로 NoOpRagClient(항상 None) 를 주입한다.

실제 RAG 를 붙일 때는 RagClient 를 구현한 클래스(예: AzureSearchRagClient) 를 만들어
pipeline 에 주입하기만 하면 된다. 파이프라인·번역·TTS 코드는 건드리지 않는다.
  → 구체적 구현 절차는 ai-worker/README.md 의 "RAG 붙이기" 절 참고.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class RagClient(Protocol):
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        """문장(+감지된 glossary 용어)에 대한 강의자료 문맥을 반환.

        검색이 불필요하거나(=RAG Trigger 미발동) 결과가 없으면 None 을 반환한다.
        반환된 문자열은 번역 프롬프트에 'context' 로 그대로 주입된다.
        """
        ...


class NoOpRagClient:
    """RAG 미적용 기본 구현 — 항상 None (문맥 주입 없이 번역)."""

    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        return None
