from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import current_user, get_or_create_user, issue_cookie, optional_current_user
from db import get_db
from models import User
from services.presence import forget_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class IdentifyIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)


def _validate_nickname(nickname: str) -> str:
    """Reject nicknames that would collide with internal tombstone format
    or contain control characters. Doesn't otherwise restrict — UTF-8
    Chinese / emoji are fine."""
    n = nickname.strip()
    if not n:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty nickname")
    if n.startswith("_deleted_"):
        # Reserved prefix used by delete_user to tombstone deceased
        # accounts. Letting users self-register with this would let them
        # impersonate the visual style of admin's deleted records.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="昵称不能以 _deleted_ 开头")
    if any(c in n for c in "\r\n\t\x00"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="昵称不能包含控制字符")
    return n


class IdentifyOut(BaseModel):
    id: str
    nickname: str
    created: bool
    is_admin: bool = False


@router.post("/identify", response_model=IdentifyOut)
def identify(payload: IdentifyIn, response: Response, db: Session = Depends(get_db)) -> IdentifyOut:
    nickname = _validate_nickname(payload.nickname)
    user, created = get_or_create_user(db, nickname)
    db.commit()
    issue_cookie(response, user)
    return IdentifyOut(
        id=user.id, nickname=user.nickname, created=created,
        is_admin=bool(getattr(user, "is_admin", False)),
    )


@router.get("/me", response_model=IdentifyOut | None)
def me(user: User | None = Depends(optional_current_user)) -> IdentifyOut | None:
    if user is None:
        return None
    return IdentifyOut(
        id=user.id, nickname=user.display_name, created=False,
        is_admin=bool(getattr(user, "is_admin", False)),
    )


@router.post("/logout")
def logout(response: Response, user: User = Depends(current_user)) -> dict:
    response.delete_cookie("yqgl_id")
    forget_user(user.id)
    return {"ok": True}
