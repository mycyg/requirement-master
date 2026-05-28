from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import current_user, forget_user_cookie
from db import get_db
from models import User
from schemas import UserOut, UserStatusUpdateIn
from services.permissions import is_admin
from services.presence import get_presence_map

router = APIRouter(prefix="/api", tags=["users"])


class _AdminPatchIn(BaseModel):
    is_admin: bool


@router.get("/users", response_model=list[UserOut])
def list_users(
    search: str = Query(default="", max_length=64),
    limit: int = Query(default=30, ge=1, le=100),
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[UserOut]:
    q = db.query(User)
    if not include_deleted:
        q = q.filter(User.deleted_at.is_(None))
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
            nickname=u.display_name,
            is_online=presence[u.id].is_online,
            last_seen_at=presence[u.id].last_seen_at,
            availability_status=u.availability_status or "free",
            availability_text=u.availability_text,
            availability_updated_at=u.availability_updated_at,
            is_admin=bool(getattr(u, "is_admin", False)),
            deleted_at=getattr(u, "deleted_at", None),
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
        nickname=user.display_name,
        is_online=presence.is_online,
        last_seen_at=presence.last_seen_at,
        availability_status=user.availability_status,
        availability_text=user.availability_text,
        availability_updated_at=user.availability_updated_at,
        is_admin=bool(getattr(user, "is_admin", False)),
        deleted_at=getattr(user, "deleted_at", None),
    )


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> None:
    """Admin-only soft-delete (sets `deleted_at`). Hard-delete would raise
    IntegrityError because ~15 tables reference users.id without ondelete
    cascade — by design, since users own historical work that shouldn't
    disappear.

    Hardening to make soft-delete actually mean something:
      - refuse if actor == target (lockout protection)
      - refuse if target is the last live admin (lockout protection)
      - drop the admin flag (so set_user_admin can't trivially restore)
      - rotate cookie_token so all outstanding browser sessions become
        invalid immediately (without this, the user's open tabs keep
        working until cookie expiry)
      - tombstone the nickname (prefix `_deleted_<id8>_`) so a new person
        with the same name can identify cleanly; the old user can never
        re-identify because get_or_create_user filters deleted_at
      - revoke all ClientDevice rows (kills worker-token auth)
    """
    from datetime import datetime
    from models import ClientDevice
    if not is_admin(actor):
        raise HTTPException(status_code=403, detail="only admins can delete users")
    if user_id == actor.id:
        raise HTTPException(status_code=400, detail="cannot delete yourself")
    target = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if target.is_admin:
        remaining = db.query(User).filter(
            User.is_admin == True, User.id != user_id, User.deleted_at.is_(None),  # noqa: E712
        ).count()
        if remaining == 0:
            raise HTTPException(status_code=400, detail="cannot delete the last admin")
    target.deleted_at = datetime.utcnow()
    target.is_admin = False
    # Free the original nickname so a new person with the same name can
    # identify. 64-char column → truncate prefix conservatively.
    suffix = f"_deleted_{target.id[:8]}_"
    target.nickname = (suffix + target.nickname)[:64]
    forget_user_cookie(db, target)  # rotate cookie_token
    db.query(ClientDevice).filter(
        ClientDevice.user_id == user_id, ClientDevice.revoked_at.is_(None),
    ).update({"revoked_at": datetime.utcnow()})
    db.commit()


@router.put("/users/{user_id}/admin", response_model=UserOut)
def set_user_admin(
    user_id: str,
    payload: _AdminPatchIn,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> UserOut:
    """Grant or revoke admin. Admin-only. Refuses to revoke the last
    remaining admin so the install can't be locked out. Refuses to act
    on soft-deleted users — otherwise admin could resurrect them."""
    if not is_admin(actor):
        raise HTTPException(status_code=403, detail="only admins can change admin status")
    target = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if not payload.is_admin and target.is_admin:
        remaining = db.query(User).filter(
            User.is_admin == True, User.id != user_id, User.deleted_at.is_(None),  # noqa: E712
        ).count()
        if remaining == 0:
            raise HTTPException(status_code=400, detail="cannot revoke the last admin")
    target.is_admin = payload.is_admin
    db.commit()
    db.refresh(target)
    presence = get_presence_map([target.id])[target.id]
    return UserOut(
        id=target.id,
        nickname=target.display_name,
        is_online=presence.is_online,
        last_seen_at=presence.last_seen_at,
        availability_status=target.availability_status or "free",
        availability_text=target.availability_text,
        availability_updated_at=target.availability_updated_at,
        is_admin=bool(target.is_admin),
        deleted_at=target.deleted_at,
    )
