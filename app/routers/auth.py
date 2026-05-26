from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import current_user, get_or_create_user, issue_cookie, optional_current_user
from db import get_db
from models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class IdentifyIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)


class IdentifyOut(BaseModel):
    id: str
    nickname: str
    created: bool


@router.post("/identify", response_model=IdentifyOut)
def identify(payload: IdentifyIn, response: Response, db: Session = Depends(get_db)) -> IdentifyOut:
    nickname = payload.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty nickname")
    user, created = get_or_create_user(db, nickname)
    db.commit()
    issue_cookie(response, user)
    return IdentifyOut(id=user.id, nickname=user.nickname, created=created)


@router.get("/me", response_model=IdentifyOut | None)
def me(user: User | None = Depends(optional_current_user)) -> IdentifyOut | None:
    if user is None:
        return None
    return IdentifyOut(id=user.id, nickname=user.nickname, created=False)


@router.post("/logout")
def logout(response: Response, _: User = Depends(current_user)) -> dict:
    response.delete_cookie("yqgl_id")
    return {"ok": True}
