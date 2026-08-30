import asyncio

import pytest

from health_dashboard.services.sync_queue import _reset_for_tests, provider_sync_slot, sync_queue_snapshot


@pytest.mark.asyncio
async def test_sync_queue_serializes_provider_writes() -> None:
    _reset_for_tests()
    entered = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def contender() -> None:
        async with provider_sync_slot("strava"):
            order.append("strava")
            entered.set()

    async with provider_sync_slot("whoop"):
        order.append("whoop")
        task = asyncio.create_task(contender())
        await asyncio.sleep(0)
        snapshot = sync_queue_snapshot()
        assert snapshot.current_provider == "whoop"
        assert snapshot.queued_count == 1
        assert not entered.is_set()
        release.set()

    await task
    assert order == ["whoop", "strava"]
    assert sync_queue_snapshot().current_provider is None
    _reset_for_tests()
