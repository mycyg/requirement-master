from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import User
from schemas import UserOut

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
    rows = q.order_by(User.nickname).limit(limit).all()
    return [UserOut(id=u.id, nickname=u.nickname) for u in rows]
