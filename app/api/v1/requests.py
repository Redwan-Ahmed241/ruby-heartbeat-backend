"""Blood requests router: /api/v1/requests."""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.enums import (
    UserRole,
    RequestUrgency,
    RequestStatus,
    BloodGroup,
    MatchResponseStatus,
)
from app.models.user import User, Recipient, Donor
from app.models.request import BloodRequest, DonorMatch
from app.schemas.request import (
    BloodRequestCreate,
    BloodRequestResponse,
    MaskedDonorMatchResponse,
)
from app.api.deps import get_current_active_user, RequireRoles
from app.services.matching import run_matching_engine
from app.services.audit import log_system_action
from app.services.email_service import (
    send_single_donor_match_alert,
    send_emergency_broadcast_alert,
)

router = APIRouter(prefix="/requests", tags=["Blood Requests"])


def build_masked_match_response(match: DonorMatch) -> MaskedDonorMatchResponse:
    """Build MaskedDonorMatchResponse satisfying the Contact Reveal Safeguard.
    Personal phone, address, and email are NEVER exposed here.
    """
    donor_user = match.donor.user if match.donor else None
    first_letter = donor_user.full_name[0].upper() if donor_user and donor_user.full_name else "D"
    masked_name = f"Donor {first_letter}***"

    return MaskedDonorMatchResponse(
        match_id=match.match_id,
        request_id=match.request_id,
        donor_id=match.donor_id,
        blood_group=match.donor.blood_group,
        distance_km=float(match.distance_km),
        match_score=float(match.match_score),
        response_status=match.response_status,
        is_notified=match.is_notified,
        start_date=match.start_date,
        donor_name_initial=masked_name,
        contact_revealed=(match.response_status == MatchResponseStatus.ACCEPTED),
    )


def format_blood_request_response(req: BloodRequest) -> BloodRequestResponse:
    """Format a BloodRequest model into BloodRequestResponse with masked matches."""
    masked_matches = [build_masked_match_response(m) for m in req.matches] if req.matches else []
    return BloodRequestResponse(
        request_id=req.request_id,
        recipient_id=req.recipient_id,
        blood_group=req.blood_group,
        component_type=req.component_type,
        quantity=float(req.quantity),
        urgency=req.urgency,
        required_location=req.required_location,
        latitude=float(req.latitude),
        longitude=float(req.longitude),
        status=req.status,
        request_date=req.request_date,
        notes=req.notes,
        matches=masked_matches,
    )


@router.post("/", response_model=BloodRequestResponse, status_code=status.HTTP_201_CREATED)
def create_blood_request(
    request_data: BloodRequestCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(RequireRoles([UserRole.RECIPIENT, UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Create blood request and trigger the Intelligent Matching Engine automatically."""
    recipient = db.query(Recipient).filter(Recipient.recipient_id == current_user.user_id).first()
    if not recipient and current_user.role == UserRole.RECIPIENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient profile not found for this user.",
        )

    recipient_id = recipient.recipient_id if recipient else current_user.user_id

    blood_req = BloodRequest(
        recipient_id=recipient_id,
        blood_group=request_data.blood_group,
        component_type=request_data.component_type,
        quantity=request_data.quantity,
        urgency=request_data.urgency,
        required_location=request_data.required_location,
        latitude=request_data.latitude,
        longitude=request_data.longitude,
        status=RequestStatus.PENDING,
        notes=request_data.notes,
    )
    db.add(blood_req)
    db.flush()

    matches = run_matching_engine(db=db, request=blood_req, is_emergency=(request_data.urgency == RequestUrgency.EMERGENCY))
    if matches:
        blood_req.status = RequestStatus.MATCHED

        blood_group_val = (
            blood_req.blood_group.value
            if hasattr(blood_req.blood_group, "value")
            else str(blood_req.blood_group)
        )

        if request_data.urgency == RequestUrgency.EMERGENCY:
            emergency_emails = [
                m.donor.user.email
                for m in matches
                if m.donor and m.donor.user and m.donor.user.email
            ]
            if emergency_emails:
                background_tasks.add_task(
                    send_emergency_broadcast_alert,
                    donor_emails=emergency_emails,
                    blood_group=blood_group_val,
                    hospital_name=blood_req.required_location,
                    units_needed=float(blood_req.quantity),
                    request_id=str(blood_req.request_id),
                )
        else:
            for m in matches:
                if m.donor and m.donor.user and m.donor.user.email:
                    background_tasks.add_task(
                        send_single_donor_match_alert,
                        donor_email=m.donor.user.email,
                        donor_name=m.donor.user.full_name or "Valued Donor",
                        blood_group=blood_group_val,
                        hospital_name=blood_req.required_location,
                        match_id=str(m.match_id),
                        distance_km=float(m.distance_km) if m.distance_km is not None else None,
                    )

    log_system_action(
        db=db,
        action="CREATE_BLOOD_REQUEST",
        entity="blood_requests",
        entity_id=blood_req.request_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(blood_req)

    return format_blood_request_response(blood_req)


@router.post("/emergency", response_model=BloodRequestResponse, status_code=status.HTTP_201_CREATED)
def create_emergency_request(
    request_data: BloodRequestCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(RequireRoles([UserRole.RECIPIENT, UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """High-priority endpoint: bypasses queues, expands radius immediately to 50 km, flags as EMERGENCY."""
    request_data.urgency = RequestUrgency.EMERGENCY
    
    recipient = db.query(Recipient).filter(Recipient.recipient_id == current_user.user_id).first()
    recipient_id = recipient.recipient_id if recipient else current_user.user_id

    blood_req = BloodRequest(
        recipient_id=recipient_id,
        blood_group=request_data.blood_group,
        component_type=request_data.component_type,
        quantity=request_data.quantity,
        urgency=RequestUrgency.EMERGENCY,
        required_location=request_data.required_location,
        latitude=request_data.latitude,
        longitude=request_data.longitude,
        status=RequestStatus.PENDING,
        notes=request_data.notes,
    )
    db.add(blood_req)
    db.flush()

    matches = run_matching_engine(db=db, request=blood_req, is_emergency=True)
    if matches:
        blood_req.status = RequestStatus.MATCHED

        blood_group_val = (
            blood_req.blood_group.value
            if hasattr(blood_req.blood_group, "value")
            else str(blood_req.blood_group)
        )
        emergency_emails = [
            m.donor.user.email
            for m in matches
            if m.donor and m.donor.user and m.donor.user.email
        ]
        if emergency_emails:
            background_tasks.add_task(
                send_emergency_broadcast_alert,
                donor_emails=emergency_emails,
                blood_group=blood_group_val,
                hospital_name=blood_req.required_location,
                units_needed=float(blood_req.quantity),
                request_id=str(blood_req.request_id),
            )

    log_system_action(
        db=db,
        action="CREATE_EMERGENCY_REQUEST",
        entity="blood_requests",
        entity_id=blood_req.request_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(blood_req)

    return format_blood_request_response(blood_req)


@router.get("/", response_model=List[BloodRequestResponse])
def list_blood_requests(
    blood_group: Optional[BloodGroup] = None,
    urgency: Optional[RequestUrgency] = None,
    status_filter: Optional[RequestStatus] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List blood requests with filters."""
    query = db.query(BloodRequest).options(
        joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user)
    )

    if blood_group:
        query = query.filter(BloodRequest.blood_group == blood_group)
    if urgency:
        query = query.filter(BloodRequest.urgency == urgency)
    if status_filter:
        query = query.filter(BloodRequest.status == status_filter)

    requests = query.order_by(BloodRequest.request_date.desc()).all()
    return [format_blood_request_response(req) for req in requests]


@router.get("/{request_id}", response_model=BloodRequestResponse)
def get_blood_request(
    request_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get request details by ID."""
    req = (
        db.query(BloodRequest)
        .options(
            joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user)
        )
        .filter(BloodRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    return format_blood_request_response(req)


@router.get("/{request_id}/matches", response_model=List[MaskedDonorMatchResponse])
def get_request_matches(
    request_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Returns matched donors for a request with personal contact info strictly masked."""
    req = db.query(BloodRequest).filter(BloodRequest.request_id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    matches = (
        db.query(DonorMatch)
        .options(joinedload(DonorMatch.donor).joinedload(Donor.user))
        .filter(DonorMatch.request_id == request_id)
        .order_by(DonorMatch.match_score.desc())
        .all()
    )

    return [build_masked_match_response(m) for m in matches]
