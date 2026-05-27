from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import User
from schemas import UserOut
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
    rows.sort(key=lambda u: (not presence[u.id].is_online, u.nickname.casefold()))
    return [
        UserOut(
            id=u.id,
            nickname=u.nickname,
            is_online=presence[u.id].is_online,
            last_seen_at=presence[u.id].last_seen_at,
        )
        for u in rows[:limit]
    ]
