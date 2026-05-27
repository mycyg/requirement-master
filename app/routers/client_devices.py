from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import current_client_device, current_user, hash_client_token, make_client_token
from db import get_db
from models import ClientDevice, User
from schemas import ClientDeviceOut, ClientDeviceRegisterIn, ClientDeviceRegisterOut

router = APIRouter(prefix="/api/client-devices", tags=["client-devices"])


def _out(device: ClientDevice) -> ClientDeviceOut:
    return ClientDeviceOut(
        id=device.id,
        device_name=device.device_name,
        platform=device.platform,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
        created_at=device.created_at,
    )


@router.post("/register", response_model=ClientDeviceRegisterOut, status_code=status.HTTP_201_CREATED)
def register_client_device(
    payload: ClientDeviceRegisterIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ClientDeviceRegisterOut:
    token = make_client_token()
    device = ClientDevice(
        user_id=user.id,
        device_name=payload.device_name.strip(),
        platform=(payload.platform or "unknown").strip()[:64] or "unknown",
        client_token_hash=hash_client_token(token),
        last_seen_at=datetime.utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return ClientDeviceRegisterOut(device=_out(device), client_token=token)


@router.get("/me", response_model=list[ClientDeviceOut])
def list_my_client_devices(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ClientDeviceOut]:
    rows = (
        db.query(ClientDevice)
        .filter(ClientDevice.user_id == user.id)
        .order_by(ClientDevice.revoked_at.isnot(None), ClientDevice.last_seen_at.desc())
        .all()
    )
    return [_out(row) for row in rows]


@router.post("/{device_id}/revoke", response_model=ClientDeviceOut)
def revoke_client_device(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ClientDeviceOut:
    device = (
        db.query(ClientDevice)
        .filter(ClientDevice.id == device_id, ClientDevice.user_id == user.id)
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="client device not found")
    if not device.revoked_at:
        device.revoked_at = datetime.utcnow()
        db.commit()
        db.refresh(device)
    return _out(device)


@router.post("/revoke-current", response_model=ClientDeviceOut)
def revoke_current_client_device(
    device: ClientDevice = Depends(current_client_device),
    db: Session = Depends(get_db),
) -> ClientDeviceOut:
    device.revoked_at = datetime.utcnow()
    db.commit()
    db.refresh(device)
    return _out(device)
