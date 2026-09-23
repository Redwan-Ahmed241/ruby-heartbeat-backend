"""User management router: /api/v1/users."""
from datetime import date
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.enums import UserRole, UserStatus, AvailabilityStatus
from app.models.user import User, Donor
from app.schemas.auth import UserResponse, UserProfileUpdate
from app.api.deps import RequireRoles, get_current_active_user
from app.api.v1.donors import get_or_create_donor
from app.services.audit import log_system_action

router = APIRouter(prefix="/users", tags=["User Management"])


class UserStatusUpdate(BaseModel):
    status: UserStatus


@router.put("/profile", response_model=UserResponse)
def update_user_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update profile settings for the authenticated user and linked donor/recipient."""
    if payload.full_name is not None and payload.full_name.strip():
        current_user.full_name = payload.full_name.strip()
    if payload.phone is not None and payload.phone.strip():
        current_user.phone = payload.phone.strip()
    if payload.backup_phone is not None:
        clean_backup = payload.backup_phone.strip()
        current_user.backup_phone = clean_backup if clean_backup else None

    # Update or provision linked donor
    donor = get_or_create_donor(db, current_user)
    if payload.blood_group is not None:
        donor.blood_group = payload.blood_group
    if payload.age is not None:
        donor.age = payload.age
        today = date.today()
        donor.date_of_birth = date(today.year - payload.age, today.month, min(today.day, 28))

    loc_val = payload.address or payload.location_zone
    if loc_val and loc_val.strip():
        clean_loc = loc_val.strip()
        donor.address = clean_loc
        if current_user.recipient:
            current_user.recipient.address = clean_loc

    # Last donation date and dynamic eligibility cooldown recalculation
    if payload.last_donation_date is not None:
        donor.last_donation_date = payload.last_donation_date
        days_ago = (date.today() - donor.last_donation_date).days
        if days_ago < 90:
            donor.availability_status = AvailabilityStatus.UNAVAILABLE
        else:
            donor.availability_status = AvailabilityStatus.AVAILABLE

    log_system_action(
        db=db,
        action="UPDATE_USER_PROFILE",
        entity="users",
        entity_id=current_user.user_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(current_user)
    if donor:
        db.refresh(donor)
    return current_user


@router.get("/", response_model=List[UserResponse])
def list_users(
    role: Optional[UserRole] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(RequireRoles([UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """List all users with optional role and search filters."""
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (User.full_name.ilike(pattern)) | (User.email.ilike(pattern))
        )

    return query.order_by(User.created_at.desc()).all()


@router.patch("/{user_id}/status", response_model=UserResponse)
def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    current_user: User = Depends(RequireRoles([UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Toggle a user's account status (ACTIVE / BLOCKED)."""
    target_user = db.query(User).filter(User.user_id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if target_user.user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own account status.",
        )

    target_user.status = payload.status

    log_system_action(
        db=db,
        action=f"USER_STATUS_{payload.status.value}",
        entity="users",
        entity_id=target_user.user_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(target_user)
    return target_user
