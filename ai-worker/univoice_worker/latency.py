"""세그먼트별 지연 계측.

기본은 비활성이다. `LATENCY_LOG_PATH` 가 설정된 경우에만 JSONL 한 줄씩 append 한다.
운영 경로에 영향을 주지 않도록 (1) 기본 off, (2) 기록 실패 시 조용히 자기 비활성화,
(3) 예외를 절대 호출부로 올리지 않는다 — 계측이 자막을 막으면 안 된다.

시간 기준은 전부 `time.monotonic()` 이다. 세그먼터/파이프라인이 이미 monotonic 을
쓰므로 동일 기준으로 뺄셈이 성립한다. wall clock(`time.time()`)과 섞지 말 것.

집계는 `tools/latency_report.py` 가 한다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_PATH = "LATENCY_LOG_PATH"


def elapsed_ms(start: float | None, end: float | None) -> float | None:
    """두 monotonic 시각의 차이를 ms 로. 어느 한쪽이 없으면 None."""
    if start is None or end is None:
        return None
    return round((end - start) * 1000, 1)


class LatencyLog:
    """JSONL 지연 기록기. 스레드 안전(STT 콜백 스레드에서도 부를 수 있다)."""

    def __init__(self, path: str | None = None) -> None:
        target = path if path is not None else os.environ.get(ENV_PATH, "")
        target = (target or "").strip()
        self._path: Path | None = Path(target) if target else None
        self._lock = threading.Lock()
        self._prepared = False

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def record(self, kind: str, **fields: Any) -> None:
        if self._path is None:
            return
        payload = {"kind": kind, **{k: v for k, v in fields.items() if v is not None}}
        try:
            line = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):  # pragma: no cover - 방어
            logger.exception("지연 레코드 직렬화 실패")
            return
        try:
            with self._lock:
                path = self._path
                if path is None:
                    return
                if not self._prepared:
                    if path.parent and str(path.parent):
                        path.parent.mkdir(parents=True, exist_ok=True)
                    self._prepared = True
                with path.open("a", encoding="utf-8") as fp:
                    fp.write(line + "\n")
        except OSError:
            # 한 번 실패하면 계속 실패한다. 반복 예외로 파이프라인을 괴롭히지 않는다.
            logger.exception("지연 로그 기록 실패; 계측을 끈다: %s", self._path)
            self._path = None
            return
        logger.info("[latency] %s", line)


_default: LatencyLog | None = None
_default_lock = threading.Lock()


def default_log() -> LatencyLog:
    """프로세스 공용 기록기. 환경변수는 최초 1회만 읽는다."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = LatencyLog()
    return _default


def reset_default_log() -> None:
    """테스트용 — 환경변수를 바꾼 뒤 다시 읽게 한다."""
    global _default
    with _default_lock:
        _default = None
