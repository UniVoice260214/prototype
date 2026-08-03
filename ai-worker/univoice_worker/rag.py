"""RAG 교체 지점(seam)과 데모용 HTTP RAG 클라이언트.

아키텍처 가이드의 파이프라인에서 RAG 는 "번역 직전에 강의자료 문맥을 붙이는" 단계다.
파이프라인은 아래 인터페이스에만 의존하므로 구현체를 바꿔도 번역·TTS 코드는
수정하지 않는다.
"""

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class RagClient(Protocol):
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        """문장과 감지된 glossary 용어에 대한 강의자료 문맥을 반환한다."""
        ...


class NoOpRagClient:
    """RAG 미적용 기본 구현 — 항상 None (문맥 주입 없이 번역)."""

    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        return None


class HttpRagClient:
    """별도 RAG 서비스에서 Router + FAISS 검색 문맥을 가져온다.

    RAG 장애가 실시간 번역 전체를 막지 않도록 네트워크/응답 오류 시에는
    로그를 남기고 None으로 fail-open 한다. 데모 Compose에서는 서비스
    healthcheck가 통과한 뒤 AI worker가 시작되므로 정상 시에는 항상 RAG를 쓴다.
    """

    def __init__(
        self,
        base_url: str,
        *,
        major: str = "auto",
        course_id: str = "",
        timeout_sec: float = 5.0,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/retrieve"
        self._major = major
        self._course_id = course_id
        self._timeout_sec = timeout_sec

    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                response = await client.post(
                    self._url,
                    json={
                        "sentence": sentence,
                        "glossaryHits": glossary_hits,
                        "major": self._major,
                        "courseId": self._course_id,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:  # noqa: BLE001 - RAG는 번역을 막지 않는 보조 단계다.
            logger.exception("RAG service request failed; continuing without context")
            return None

        if not payload.get("useRag"):
            logger.info(
                "RAG OFF major=%s reason=%s latencyMs=%s",
                payload.get("major"),
                payload.get("reason"),
                payload.get("latencyMs"),
            )
            return None

        context = payload.get("context")
        if not isinstance(context, str) or not context.strip():
            logger.warning("RAG service returned useRag=true without context")
            return None

        logger.info(
            "RAG ON major=%s matched=%s topScore=%s sources=%s latencyMs=%s",
            payload.get("major"),
            payload.get("matchedTerms"),
            payload.get("topScore"),
            [item.get("source") for item in payload.get("results", [])],
            payload.get("latencyMs"),
        )
        return context