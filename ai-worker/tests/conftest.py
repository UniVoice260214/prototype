from __future__ import annotations

import pytest


@pytest.fixture
def session_id() -> str:
    return "session-123"
