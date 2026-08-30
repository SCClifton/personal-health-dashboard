from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator


@dataclass(frozen=True)
class SyncQueueSnapshot:
    current_provider: str | None
    queued_count: int
    last_started_at: datetime | None


_lock = asyncio.Lock()
_current_provider: str | None = None
_queued_count = 0
_last_started_at: datetime | None = None


@asynccontextmanager
async def provider_sync_slot(provider: str) -> AsyncIterator[None]:
    global _current_provider, _queued_count, _last_started_at
    if _lock.locked():
        _queued_count += 1
        try:
            await _lock.acquire()
        finally:
            _queued_count = max(0, _queued_count - 1)
    else:
        await _lock.acquire()
    _current_provider = provider
    _last_started_at = datetime.now(timezone.utc)
    try:
        yield
    finally:
        _current_provider = None
        _lock.release()


def sync_queue_snapshot() -> SyncQueueSnapshot:
    return SyncQueueSnapshot(
        current_provider=_current_provider,
        queued_count=_queued_count,
        last_started_at=_last_started_at,
    )


def _reset_for_tests() -> None:
    global _current_provider, _queued_count, _last_started_at
    _current_provider = None
    _queued_count = 0
    _last_started_at = None
