"""Administrative moderation router: /api/v1/admin."""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.enums import UserRole, RequestStatus, MatchResponseStatus, AvailabilityStatus
from app.models.user import User, Donor
from app.models.request import BloodRequest, DonorMatch
from app.schemas.auth import UserResponse
from app.schemas.request import BloodRequestResponse
from app.api.deps import RequireRoles
from app.api.v1.requests import format_blood_request_response
from app.services.audit import log_system_action

router = APIRouter(prefix="/admin", tags=["Admin Moderation"])


class AdminCancelRequestPayload(BaseModel):
    reason: Optional[str] = "Cancelled by Administrator"


@router.post("/donors/{user_id}/reset-cooldown", response_model=UserResponse)
def admin_reset_donor_cooldown(
    user_id: UUID,
    current_user: User = Depends(RequireRoles([UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Admin Override: Clear donor cooldown window after medical review.
    Sets last_donation_date to None and availability_status to AVAILABLE.
    """
    target_user = db.query(User).filter(User.user_id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    donor = db.query(Donor).filter(Donor.donor_id == user_id).first()
    if not donor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Donor profile not found for this user.",
        )

    donor.last_donation_date = None
    donor.availability_status = AvailabilityStatus.AVAILABLE

    log_system_action(
        db=db,
        action="ADMIN_RESET_COOLDOWN",
        entity="donors",
        entity_id=donor.donor_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(target_user)
    db.refresh(donor)
    return target_user


@router.post("/requests/{request_id}/cancel", response_model=BloodRequestResponse)
def admin_cancel_blood_request(
    request_id: UUID,
    payload: Optional[AdminCancelRequestPayload] = None,
    current_user: User = Depends(RequireRoles([UserRole.SYSTEM_ADMIN, UserRole.HOSPITAL_ADMIN])),
    db: Session = Depends(get_db),
):
    """Admin Moderation: Cancel/Delete spam, outdated, or duplicate blood requests.
    Transitions request status to CANCELLED and releases candidate donors.
    """
    req = db.query(BloodRequest).filter(BloodRequest.request_id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    req.status = RequestStatus.CANCELLED
    reason = payload.reason if payload and payload.reason else "Cancelled by Administrator"

    # Release candidate matches
    if req.matches:
        for match in req.matches:
            if match.response_status in [MatchResponseStatus.PENDING, MatchResponseStatus.ACCEPTED]:
                match.response_status = MatchResponseStatus.CANCELLED

    log_system_action(
        db=db,
        action="ADMIN_CANCEL_REQUEST",
        entity="blood_requests",
        entity_id=req.request_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(req)
    return format_blood_request_response(req, viewer_user_id=current_user.user_id, is_admin=True)
