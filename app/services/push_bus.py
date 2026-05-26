"""Tiny in-process pub/sub for SSE. One queue per subscriber.

Topics are plain strings, e.g. "req:<req_id>" for per-requirement updates,
"all" for global events (the tray client subscribes here for new-requirement pings).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass
class Event:
    topic: str
    type: str
    data: Any


class PushBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[Event]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs.setdefault(topic, []).append(q)
        return q

    async def unsubscribe(self, topic: str, q: asyncio.Queue[Event]) -> None:
        async with self._lock:
            if topic in self._subs and q in self._subs[topic]:
                self._subs[topic].remove(q)

    async def publish(self, topic: str, ev_type: str, data: Any) -> None:
        ev = Event(topic=topic, type=ev_type, data=data)
        async with self._lock:
            for q in self._subs.get(topic, []):
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    pass  # slow subscriber; drop


bus = PushBus()


async def stream(topic: str, *, heartbeat_secs: float = 30.0) -> AsyncIterator[Event]:
    """Async iterator over events; emits heartbeat events to keep SSE alive."""
    q = await bus.subscribe(topic)
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=heartbeat_secs)
                yield ev
            except asyncio.TimeoutError:
                yield Event(topic=topic, type="heartbeat", data=None)
    finally:
        await bus.unsubscribe(topic, q)
