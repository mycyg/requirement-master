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


def _user_from_worker_token(db: Session, raw_token: str | None) -> User | None:
    """Resolve a User from the X-YQGL-Client-Token header. The Tauri
    desktop client's webview (WebView2) maintains a SEPARATE cookie
    store from the Rust-side reqwest jar, so calls made via the React
    `clientFetch` (web fetch) DO NOT carry the yqgl_id cookie that
    Rust's identify command stored. The worker token IS reliably sent
    by clientFetch via `headers`, so use it as a fallback auth path.
    Without this, every clientFetch to a cookie-only route 401s —
    Inbox silently returned empty, Clarify visibly errored."""
    if not raw_token:
        return None
    token = raw_token.strip()
    if not token:
        return None
    device = (
        db.query(ClientDevice)
        .filter(
            ClientDevice.client_token_hash == hash_client_token(token),
            ClientDevice.revoked_at.is_(None),
        )
        .first()
    )
    if not device:
        return None
    user = db.query(User).filter(
        User.id == device.user_id, User.deleted_at.is_(None),
    ).first()
    # Deliberately DO NOT update device.last_seen_at here — that would hold
    # SQLite's single-writer lock open across the entire request, and any
    # concurrent write (e.g. the chat handler updating requirement status)
    # blocks → "database is locked" 500. Device freshness is tracked by
    # `_lookup_client_device` (require_local_client routes) which commits
    # right away. For the fallback path here, presence is tracked via
    # `touch_user` (in-memory) which the caller invokes.
    return user


def current_user(
    db: Session = Depends(get_db),
    yqgl_id: str | None = Cookie(default=None),
    x_yqgl_client_token: str | None = Header(default=None, alias=LOCAL_CLIENT_HEADER),
) -> User:
    # Soft-deleted users must be treated as if they don't exist for auth
    # purposes — otherwise admin's "DELETE user" is meaningless for any
    # session that already had a valid cookie.
    token = _verify(yqgl_id)
    if token:
        user = db.query(User).filter(
            User.cookie_token == token, User.deleted_at.is_(None),
        ).first()
        if user:
            touch_user(user.id)
            return user
    # Fall back to worker token (used by the desktop client's webview).
    user = _user_from_worker_token(db, x_yqgl_client_token)
    if user:
        touch_user(user.id)
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not identified")


def optional_current_user(
    db: Session = Depends(get_db),
    yqgl_id: str | None = Cookie(default=None),
    x_yqgl_client_token: str | None = Header(default=None, alias=LOCAL_CLIENT_HEADER),
) -> User | None:
    token = _verify(yqgl_id)
    if token:
        user = db.query(User).filter(
            User.cookie_token == token, User.deleted_at.is_(None),
        ).first()
        if user:
            touch_user(user.id)
            return user
    user = _user_from_worker_token(db, x_yqgl_client_token)
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


def require_stream_user(
    yqgl_id: str | None = Cookie(default=None),
    x_yqgl_client_token: str | None = Header(default=None, alias=LOCAL_CLIENT_HEADER),
) -> StreamUser:
    """Authenticate long-lived streams without holding a DB session open.
    Accepts cookie OR worker token (desktop client's WebView2 cookie jar
    is separate from Rust's reqwest jar; we send the worker token on
    every clientFetch including SSE)."""
    token = _verify(yqgl_id)
    db = SessionLocal()
    try:
        if token:
            row = db.query(User.id, User.nickname).filter(
                User.cookie_token == token, User.deleted_at.is_(None),
            ).first()
            if row:
                touch_user(row.id)
                return StreamUser(id=row.id, nickname=row.nickname)
        # Fall back to worker token
        user = _user_from_worker_token(db, x_yqgl_client_token)
        if user:
            touch_user(user.id)
            return StreamUser(id=user.id, nickname=user.nickname)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not identified")
    finally:
        db.close()


def get_or_create_user(db: Session, nickname: str) -> tuple[User, bool]:
    """Returns (user, created). Nickname collisions reuse the existing live
    row. A soft-deleted user with the same nickname is treated as if it
    doesn't exist — they cannot self-resurrect via identify. If their
    nickname was tombstoned during delete (e.g. `_deleted_<id>_alice`), a
    new person named "Alice" can identify cleanly. Hard policy: only an
    admin's explicit un-delete (not implemented; manual DB intervention)
    can bring a deleted account back."""
    # The 'live' row, if any, with this nickname.
    user = db.query(User).filter(
        User.nickname == nickname, User.deleted_at.is_(None),
    ).first()
    if user:
        return user, False
    user = User(nickname=nickname, cookie_token=_make_token())
    db.add(user)
    db.flush()
    return user, True


def forget_user_cookie(db: Session, user: User) -> None:
    """Rotate the user's cookie_token so all outstanding cookies become
    invalid immediately. Used on soft-delete and on /logout."""
    user.cookie_token = _make_token()
    db.flush()
