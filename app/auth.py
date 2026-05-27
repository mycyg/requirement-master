"""Cookie-based nickname identity (no password; LAN-only use).

Cookie holds an opaque token; server side maps token → User row.
Signed with itsdangerous so a tampered cookie won't validate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import secrets as _secrets  # stdlib; renamed to avoid local shadowing in scripts/

from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from config import settings
from db import SessionLocal, get_db
from models import ClientDevice, User
from services.presence import touch_user

COOKIE_NAME = "yqgl_id"
LOCAL_CLIENT_HEADER = "X-YQGL-Client-Token"
_serializer = URLSafeSerializer(settings.cookie_secret, salt="yqgl-identity-v1")


@dataclass(frozen=True)
class StreamUser:
    id: str
    nickname: str


def _make_token() -> str:
    return _secrets.token_urlsafe(32)


def make_client_token() -> str:
    return _secrets.token_urlsafe(48)


def hash_client_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_cookie(response: Response, user: User) -> None:
    touch_user(user.id)
    signed = _serializer.dumps(user.cookie_token)
    response.set_cookie(
        COOKIE_NAME,
        signed,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
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
    touch_user(user.id)
    return user


def optional_current_user(
    db: Session = Depends(get_db),
    yqgl_id: str | None = Cookie(default=None),
) -> User | None:
    token = _verify(yqgl_id)
    if not token:
        return None
    user = db.query(User).filter(User.cookie_token == token).first()
    if user:
        touch_user(user.id)
    return user


def _lookup_client_device(db: Session, user: User, token: str | None) -> ClientDevice | None:
    if not token:
        return None
    token = token.strip()
    if not token:
        return None
    device = (
        db.query(ClientDevice)
        .filter(
            ClientDevice.client_token_hash == hash_client_token(token),
            ClientDevice.user_id == user.id,
            ClientDevice.revoked_at.is_(None),
        )
        .first()
    )
    if not device:
        return None
    device.last_seen_at = datetime.utcnow()
    db.commit()
    return device


def current_client_device(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    x_yqgl_client_token: str | None = Header(default=None, alias=LOCAL_CLIENT_HEADER),
) -> ClientDevice:
    device = _lookup_client_device(db, user, x_yqgl_client_token)
    if not device:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="local client required")
    return device


def require_local_client(
    device: ClientDevice = Depends(current_client_device),
) -> User:
    return device.user


def optional_local_client(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    x_yqgl_client_token: str | None = Header(default=None, alias=LOCAL_CLIENT_HEADER),
) -> User | None:
    if not x_yqgl_client_token:
        return None
    device = _lookup_client_device(db, user, x_yqgl_client_token)
    if not device:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="local client required")
    return device.user


def require_stream_user(yqgl_id: str | None = Cookie(default=None)) -> StreamUser:
    """Authenticate long-lived streams without holding a DB session open."""
    token = _verify(yqgl_id)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not identified")
    db = SessionLocal()
    try:
        row = db.query(User.id, User.nickname).filter(User.cookie_token == token).first()
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not identified")
        touch_user(row.id)
        return StreamUser(id=row.id, nickname=row.nickname)
    finally:
        db.close()


def get_or_create_user(db: Session, nickname: str) -> tuple[User, bool]:
    """Returns (user, created). Nickname collisions reuse existing."""
    user = db.query(User).filter(User.nickname == nickname).first()
    if user:
        return user, False
    user = User(nickname=nickname, cookie_token=_make_token())
    db.add(user)
    db.flush()
    return user, True
