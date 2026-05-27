from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import User
from schemas import UserOut, UserStatusUpdateIn
from services.presence import get_presence_map

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    search: str = Query(default="", max_length=64),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[UserOut]:
    q = db.query(User)
    term = search.strip()
    if term:
        q = q.filter(User.nickname.ilike(f"%{term}%"))
    rows = q.order_by(User.nickname).all()
    presence = get_presence_map([u.id for u in rows])
    status_rank = {"free": 0, "custom": 1, "busy": 2}
    rows.sort(key=lambda u: (
        not presence[u.id].is_online,
        status_rank.get(u.availability_status or "free", 3),
        u.nickname.casefold(),
    ))
    return [
        UserOut(
            id=u.id,
            nickname=u.nickname,
            is_online=presence[u.id].is_online,
            last_seen_at=presence[u.id].last_seen_at,
            availability_status=u.availability_status or "free",
            availability_text=u.availability_text,
            availability_updated_at=u.availability_updated_at,
        )
        for u in rows[:limit]
    ]


@router.put("/users/me/status", response_model=UserOut)
def update_my_status(
    payload: UserStatusUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> UserOut:
    text = (payload.availability_text or "").strip()
    user.availability_status = payload.availability_status
    user.availability_text = text[:128] if text else None
    user.availability_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    presence = get_presence_map([user.id])[user.id]
    return UserOut(
        id=user.id,
        nickname=user.nickname,
        is_online=presence.is_online,
        last_seen_at=presence.last_seen_at,
        availability_status=user.availability_status,
        availability_text=user.availability_text,
        availability_updated_at=user.availability_updated_at,
    )
