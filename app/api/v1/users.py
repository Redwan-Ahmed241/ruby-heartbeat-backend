"""User management router: /api/v1/users (System Admin only)."""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.enums import UserRole, UserStatus
from app.models.user import User
from app.schemas.auth import UserResponse
from app.api.deps import RequireRoles
from app.services.audit import log_system_action

router = APIRouter(prefix="/users", tags=["User Management"])


class UserStatusUpdate(BaseModel):
    status: UserStatus


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
