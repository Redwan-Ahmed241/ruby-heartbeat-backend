from datetime import datetime, date, timedelta
"""Matches and Contact Reveal Safeguard router: /api/v1/matches."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.enums import UserRole, MatchResponseStatus, RequestStatus, AvailabilityStatus
from app.models.user import User, Donor
from app.models.request import DonorMatch, BloodRequest
from app.schemas.request import MatchRespondRequest, DonorContactReveal, MatchCompletionStatusResponse
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

    # Clinical Eligibility + Donor Concurrency Lock
    if response_data.response == MatchResponseStatus.ACCEPTED:
        # === Clinical Cooldown Guard (90-day whole blood) ===
        donor = (
            db.query(Donor)
            .options(joinedload(Donor.medical_info))
            .filter(Donor.donor_id == current_user.user_id)
            .first()
        )
        if donor:
            from app.services.eligibility import check_donor_eligibility
            is_eligible, rejections, metrics = check_donor_eligibility(donor)
            if not is_eligible:
                cooldown_msg = "; ".join(rejections)
                next_date = metrics.get("next_eligible_date")
                detail = f"You are not currently eligible to donate: {cooldown_msg}"
                if next_date:
                    detail += f" Next eligible date: {next_date.strftime('%Y-%m-%d')}."
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=detail,
                )

        # === Donor Concurrency Lock ===
        active_match = (
            db.query(DonorMatch)
            .join(BloodRequest, DonorMatch.request_id == BloodRequest.request_id)
            .filter(
                DonorMatch.donor_id == current_user.user_id,
                DonorMatch.match_id != match_id,
                DonorMatch.response_status == MatchResponseStatus.ACCEPTED,
                BloodRequest.status.in_([
                    RequestStatus.MATCHED,
                    RequestStatus.PROCESSING,
                    RequestStatus.ACCEPTED,
                ]),
            )
            .first()
        )
        if active_match:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have an active accepted donation commitment. You must complete or cancel your active commitment before accepting another request.",
            )

    match.response_status = response_data.response

    # If accepted, update request status and assign accepted_donor_id
    if response_data.response == MatchResponseStatus.ACCEPTED:
        req = db.query(BloodRequest).filter(BloodRequest.request_id == match.request_id).first()
        if req:
            req.status = RequestStatus.MATCHED
            req.accepted_donor_id = current_user.user_id
    elif response_data.response in [MatchResponseStatus.DECLINED, MatchResponseStatus.CANCELLED]:
        req = db.query(BloodRequest).filter(BloodRequest.request_id == match.request_id).first()
        if req and (req.accepted_donor_id == current_user.user_id or req.status == RequestStatus.MATCHED):
            other_accepted = (
                db.query(DonorMatch)
                .filter(
                    DonorMatch.request_id == req.request_id,
                    DonorMatch.match_id != match.match_id,
                    DonorMatch.response_status == MatchResponseStatus.ACCEPTED,
                )
                .first()
            )
            if not other_accepted:
                req.accepted_donor_id = None
                if req.status in [RequestStatus.MATCHED, RequestStatus.ACCEPTED]:
                    req.status = RequestStatus.OPEN

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


@router.post("/{match_id}/confirm-completion", response_model=MatchCompletionStatusResponse)
def confirm_match_completion(
    match_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Two-Sided Completion Confirmation & Automatic 90-Day Cooldown:
    - Donor calling it sets donor_confirmed_completion = True
    - Recipient calling it sets recipient_confirmed_completion = True
    - When both are True:
      1. match marks COMPLETED and request marks COMPLETED
      2. donor.total_donations increments by 1
      3. donor.last_donation_date updates to date.today()
      4. donor placed in 90-day cooldown (is_available = False)
      5. Donor concurrency lock released
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

    is_donor = (match.donor_id == current_user.user_id)
    is_recipient = (match.blood_request and match.blood_request.recipient_id == current_user.user_id)
    is_admin = current_user.role in [UserRole.SYSTEM_ADMIN, UserRole.HOSPITAL_ADMIN]

    if not (is_donor or is_recipient or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the participating donor, recipient, or admin can confirm completion.",
        )

    if is_donor:
        match.donor_confirmed_completion = True
    if is_recipient:
        match.recipient_confirmed_completion = True
    if is_admin:
        match.donor_confirmed_completion = True
        match.recipient_confirmed_completion = True

    is_mutually_completed = bool(match.donor_confirmed_completion and match.recipient_confirmed_completion)
    cooldown_until = None

    if is_mutually_completed:
        now_dt = datetime.utcnow()
        match.response_status = MatchResponseStatus.COMPLETED
        match.completed_at = now_dt
        if match.blood_request:
            match.blood_request.status = RequestStatus.COMPLETED

        donor = db.query(Donor).filter(Donor.donor_id == match.donor_id).first()
        if donor:
            donor.total_donations = (donor.total_donations or 0) + 1
            donor.last_donation_date = date.today()
            donor.availability_status = AvailabilityStatus.UNAVAILABLE
            db.add(donor)
            db.flush()

        cooldown_until = now_dt + timedelta(days=90)

        log_system_action(
            db=db,
            action="DONATION_MUTUALLY_COMPLETED",
            entity="donor_match",
            entity_id=match.match_id,
            user_id=current_user.user_id,
        )

    db.commit()
    db.refresh(match)

    return MatchCompletionStatusResponse(
        match_id=match.match_id,
        request_id=match.request_id,
        status=match.response_status,
        donor_confirmed_completion=match.donor_confirmed_completion,
        recipient_confirmed_completion=match.recipient_confirmed_completion,
        is_completed=is_mutually_completed,
        completed_at=match.completed_at,
        cooldown_until=cooldown_until,
    )
