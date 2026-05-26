"""Small helper to record ActivityLog rows consistently."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from models import ActivityLog


def log_activity(
    db: Session,
    *,
    requirement_id: str,
    actor_nickname: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> ActivityLog:
    row = ActivityLog(
        requirement_id=requirement_id,
        actor_nickname=actor_nickname,
        action=action,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    db.add(row)
    return row
