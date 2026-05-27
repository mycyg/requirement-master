"""In-process user presence for the LAN-style nickname identity model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock


ONLINE_TTL_SECONDS = 120


@dataclass(frozen=True)
class PresenceState:
    is_online: bool
    last_seen_at: datetime | None


_lock = RLock()
_last_seen: dict[str, datetime] = {}
_open_streams: dict[str, int] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def touch_user(user_id: str) -> None:
    with _lock:
        _last_seen[user_id] = _now()


def mark_stream_open(user_id: str) -> None:
    with _lock:
        _last_seen[user_id] = _now()
        _open_streams[user_id] = _open_streams.get(user_id, 0) + 1


def mark_stream_closed(user_id: str) -> None:
    with _lock:
        _last_seen[user_id] = _now()
        count = _open_streams.get(user_id, 0)
        if count <= 1:
            _open_streams.pop(user_id, None)
        else:
            _open_streams[user_id] = count - 1


def forget_user(user_id: str) -> None:
    with _lock:
        _last_seen.pop(user_id, None)
        _open_streams.pop(user_id, None)


def get_presence(user_id: str) -> PresenceState:
    now = _now()
    with _lock:
        last_seen_at = _last_seen.get(user_id)
        stream_count = _open_streams.get(user_id, 0)
    recent = last_seen_at is not None and now - last_seen_at <= timedelta(seconds=ONLINE_TTL_SECONDS)
    return PresenceState(is_online=stream_count > 0 or recent, last_seen_at=last_seen_at)


def get_presence_map(user_ids: list[str]) -> dict[str, PresenceState]:
    return {user_id: get_presence(user_id) for user_id in user_ids}
