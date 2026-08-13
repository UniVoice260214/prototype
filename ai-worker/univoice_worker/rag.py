"""RAG 교체 지점(seam)과 데모용 HTTP RAG 클라이언트.

아키텍처 가이드의 파이프라인에서 RAG 는 "번역 직전에 강의자료 문맥을 붙이는" 단계다.
파이프라인은 아래 인터페이스에만 의존하므로 구현체를 바꿔도 번역·TTS 코드는
수정하지 않는다.
"""

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class RagClient(Protocol):
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        """문장과 감지된 glossary 용어에 대한 강의자료 문맥을 반환한다."""
        ...


class NoOpRagClient:
    """RAG 미적용 기본 구현 — 항상 None (문맥 주입 없이 번역)."""

    # 지연 계측에서 "RAG 0ms"(빠름)와 "RAG 미측정"(안 돎)을 구분하기 위한 표식.
    # 이게 없으면 RAG 를 끈 측정 결과가 "RAG 오버헤드 0ms"로 잘못 읽힌다.
    latency_enabled = False

    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        return None


class HttpRagClient:
    """별도 RAG 서비스에서 Router + FAISS 검색 문맥을 가져온다.

    RAG 장애가 실시간 번역 전체를 막지 않도록 네트워크/응답 오류 시에는
    로그를 남기고 None으로 fail-open 한다. 데모 Compose에서는 서비스
    healthcheck가 통과한 뒤 AI worker가 시작되므로 정상 시에는 항상 RAG를 쓴다.
    """

    # 연속 실패가 이 횟수에 닿으면 경고가 아니라 에러로 올린다.
    DEGRADED_THRESHOLD = 3

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
        self._client: Any | None = None
        self._consecutive_failures = 0
        self._on_count = 0
        self._off_count = 0

    def _ensure_client(self) -> Any:
        """세그먼트마다 새 클라이언트를 만들면 TLS 핸드셰이크가 반복된다."""
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self._timeout_sec)
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 - 종료는 best-effort.
                logger.exception("RAG client close failed")
        if self._on_count == 0 and (self._off_count or self._consecutive_failures):
            # 개별 OFF 는 정상(NO_TRIGGER)이지만, 세션 통틀어 한 번도 안 켜졌다면 설정 오류다.
            logger.error(
                "RAG 가 세션 내내 한 번도 동작하지 않았다 (on=0 off=%d 실패=%d major=%s) "
                "— 인덱스/전공 매핑을 확인하라",
                self._off_count,
                self._consecutive_failures,
                self._major,
            )

    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        try:
            client = self._ensure_client()
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
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.DEGRADED_THRESHOLD:
                logger.error(
                    "RAG 연속 %d회 실패 — 문맥 없이 번역 중이다 (url=%s)",
                    self._consecutive_failures,
                    self._url,
                )
            else:
                logger.warning(
                    "RAG 요청 실패 (%d회 연속); 문맥 없이 진행",
                    self._consecutive_failures,
                    exc_info=True,
                )
            return None
        self._consecutive_failures = 0

        if not payload.get("useRag"):
            self._off_count += 1
            logger.info(
                "RAG OFF major=%s reason=%s latencyMs=%s",
                payload.get("major"),
                payload.get("reason"),
                payload.get("latencyMs"),
            )
            return None
        self._on_count += 1

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