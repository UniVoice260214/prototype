from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from univoice_worker.rag import HttpRagClient


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    payload: dict = {}
    last_request: dict | None = None

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict) -> FakeResponse:
        type(self).last_request = {"url": url, "json": json, "timeout": self.timeout}
        return FakeResponse(type(self).payload)


@pytest.mark.asyncio
async def test_http_rag_client_returns_context(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAsyncClient.payload = {
        "useRag": True,
        "major": "bme",
        "matchedTerms": ["PCR"],
        "topScore": 0.81,
        "results": [{"source": "bio.pdf"}],
        "context": "PCR 검색 문맥",
        "latencyMs": 123.4,
    }
    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    client = HttpRagClient(
        "http://rag-service:8000/",
        major="bme",
        course_id="course-1",
        timeout_sec=3.0,
    )

    context = await client.retrieve("그 피시알 단계", ["PCR"])

    assert context == "PCR 검색 문맥"
    assert FakeAsyncClient.last_request == {
        "url": "http://rag-service:8000/retrieve",
        "json": {
            "sentence": "그 피시알 단계",
            "glossaryHits": ["PCR"],
            "major": "bme",
            "courseId": "course-1",
        },
        "timeout": 3.0,
    }


@pytest.mark.asyncio
async def test_http_rag_client_returns_none_when_router_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.payload = {
        "useRag": False,
        "major": "auto",
        "reason": "NO_TRIGGER",
        "latencyMs": 0.2,
    }
    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))

    context = await HttpRagClient("http://rag-service:8000").retrieve("오늘 점심", [])

    assert context is None
