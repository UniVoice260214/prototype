from __future__ import annotations

import asyncio

import pytest

from univoice_worker.dedupe import InMemoryDedupeStore, tts_dedupe_key


@pytest.mark.asyncio
async def test_processing_acquire_is_atomic() -> None:
    store = InMemoryDedupeStore()
    key = tts_dedupe_key("session-123", "session-123-seg-000001", "vi-VN")

    results = await asyncio.gather(*(store.try_acquire(key) for _ in range(10)))

    assert results.count(True) == 1
    assert results.count(False) == 9


@pytest.mark.asyncio
async def test_done_state_blocks_duplicate_tts() -> None:
    store = InMemoryDedupeStore(ttl_sec=3600)
    key = "session-123:session-123-seg-000001:vi-VN"

    assert await store.try_acquire(key)
    await store.mark_done(key)

    assert await store.is_done(key)
    assert not await store.try_acquire(key)


@pytest.mark.asyncio
async def test_failed_state_can_release_for_retry_policy() -> None:
    store = InMemoryDedupeStore(failed_ttl_sec=0)
    key = "session-123:session-123-seg-000001:vi-VN"

    assert await store.try_acquire(key)
    await store.mark_failed(key)

    assert not await store.is_done(key)
    assert await store.try_acquire(key)


@pytest.mark.asyncio
async def test_failed_ttl_blocks_until_expired() -> None:
    store = InMemoryDedupeStore(failed_ttl_sec=1)
    key = "session-123:session-123-seg-000001:vi-VN"

    assert await store.try_acquire(key)
    await store.mark_failed(key)

    assert not await store.try_acquire(key)
