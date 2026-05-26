"""Cookie-based nickname identity (no password; LAN-only use).

Cookie holds an opaque token; server side maps token → User row.
Signed with itsdangerous so a tampered cookie won't validate.
"""
from __future__ import annotations

import secrets as _secrets  # stdlib; renamed to avoid local shadowing in scripts/

from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import User

COOKIE_NAME = "yqgl_id"
_serializer = URLSafeSerializer(settings.cookie_secret, salt="yqgl-identity-v1")


def _make_token() -> str:
    return _secrets.token_urlsafe(32)


def issue_cookie(response: Response, user: User) -> None:
    signed = _serializer.dumps(user.cookie_token)
    response.set_cookie(
        COOKIE_NAME,
        signed,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
    )


def _verify(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return _serializer.loads(raw)
    except BadSignature:
        return None


def current_user(
    db: Session = Depends(get_db),
    yqgl_id: str | None = Cookie(default=None),
) -> User:
    token = _verify(yqgl_id)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not identified")
    user = db.query(User).filter(User.cookie_token == token).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not identified")
    return user


def optional_current_user(
    db: Session = Depends(get_db),
    yqgl_id: str | None = Cookie(default=None),
) -> User | None:
    token = _verify(yqgl_id)
    if not token:
        return None
    return db.query(User).filter(User.cookie_token == token).first()


def get_or_create_user(db: Session, nickname: str) -> tuple[User, bool]:
    """Returns (user, created). Nickname collisions reuse existing."""
    user = db.query(User).filter(User.nickname == nickname).first()
    if user:
        return user, False
    user = User(nickname=nickname, cookie_token=_make_token())
    db.add(user)
    db.flush()
    return user, True
