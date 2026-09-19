"""Matches and Contact Reveal Safeguard router: /api/v1/matches."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.enums import UserRole, MatchResponseStatus, RequestStatus
from app.models.user import User, Donor
from app.models.request import DonorMatch, BloodRequest
from app.schemas.request import MatchRespondRequest, DonorContactReveal
from app.api.deps import get_current_active_user, RequireRoles
from app.services.audit import log_system_action

router = APIRouter(prefix="/matches", tags=["Donor Matches"])


@router.post("/{match_id}/respond", status_code=status.HTTP_200_OK)
def respond_to_match(
    match_id: UUID,
    response_data: MatchRespondRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Donor accepts or declines a match request."""
    if response_data.response not in [MatchResponseStatus.ACCEPTED, MatchResponseStatus.DECLINED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Response status must be ACCEPTED or DECLINED.",
        )

    match = db.query(DonorMatch).filter(DonorMatch.match_id == match_id).first()
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match record not found.",
        )

    # Ensure the responding donor owns this match
    if match.donor_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to respond to this match.",
        )

    match.response_status = response_data.response

    # If accepted, update request status
    if response_data.response == MatchResponseStatus.ACCEPTED:
        req = db.query(BloodRequest).filter(BloodRequest.request_id == match.request_id).first()
        if req:
            req.status = RequestStatus.MATCHED

    log_system_action(
        db=db,
        action=f"MATCH_RESPOND_{response_data.response.value}",
        entity="donor_match",
        entity_id=match.match_id,
        user_id=current_user.user_id,
    )

    db.commit()
    return {
        "message": f"Match response recorded as {response_data.response.value}",
        "match_id": str(match.match_id),
        "response_status": match.response_status.value,
    }


@router.get("/{match_id}/contact", response_model=DonorContactReveal)
def get_donor_contact(
    match_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Contact Reveal Safeguard:
    Returns donor contact information (phone, address, email) ONLY IF response_status == 'ACCEPTED'.
    Otherwise, raises HTTP 403 Forbidden.
    """
    match = (
        db.query(DonorMatch)
        .options(
            joinedload(DonorMatch.donor).joinedload(Donor.user),
            joinedload(DonorMatch.blood_request),
        )
        .filter(DonorMatch.match_id == match_id)
        .first()
    )
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match record not found.",
        )

    # Contact Reveal Safeguard Enforcement
    if match.response_status != MatchResponseStatus.ACCEPTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contact information is masked until the donor has explicitly ACCEPTED the request.",
        )

    # Validate that current user is the recipient, the donor, hospital admin, or system admin
    is_recipient = (
        match.blood_request and match.blood_request.recipient_id == current_user.user_id
    )
    is_donor = match.donor_id == current_user.user_id
    is_admin = current_user.role in [UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN]

    if not (is_recipient or is_donor or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this contact information.",
        )

    donor = match.donor
    donor_user = donor.user

    log_system_action(
        db=db,
        action="VIEW_DONOR_CONTACT",
        entity="donor_match",
        entity_id=match.match_id,
        user_id=current_user.user_id,
    )
    db.commit()

    return DonorContactReveal(
        match_id=match.match_id,
        donor_id=donor.donor_id,
        full_name=donor_user.full_name,
        phone=donor_user.phone,
        email=donor_user.email,
        address=donor.address,
        latitude=float(donor.latitude),
        longitude=float(donor.longitude),
        response_status=match.response_status,
    )
