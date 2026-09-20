from datetime import date, timedelta
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy import case
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.enums import (
    UserRole,
    RequestUrgency,
    RequestStatus,
    BloodGroup,
    MatchResponseStatus,
    AvailabilityStatus,
    ComponentType,
)
from app.models.user import User, Recipient, Donor, DonationHistory
from app.models.request import BloodRequest, DonorMatch
from app.schemas.request import (
    BloodRequestCreate,
    BloodRequestResponse,
    AcceptedDonorSummary,
    MaskedDonorMatchResponse,
    RequestStatusUpdate,
    RequestReopenPayload,
    mask_phone_number,
)
from app.api.deps import get_current_active_user, get_current_user_optional, RequireRoles
from app.services.matching import run_matching_engine
from app.services.audit import log_system_action
from app.services.eligibility import check_donor_eligibility
from app.services.email_service import (
    send_single_donor_match_alert,
    send_emergency_broadcast_alert,
    send_donor_accepted_alert,
    send_donation_completed_thank_you_alert,
    send_match_cancelled_reopened_alert,
)
from app.api.v1.donors import get_or_create_donor

router = APIRouter(prefix="/requests", tags=["Blood Requests"])


def build_masked_match_response(match: DonorMatch) -> MaskedDonorMatchResponse:
    """Build MaskedDonorMatchResponse satisfying the Contact Reveal Safeguard.
    Personal phone, address, and email are NEVER exposed here.
    Coordinates are rounded to 2 decimal places (~1.1 km area grid) to protect donor residential privacy.
    """
    donor = match.donor
    donor_user = donor.user if donor else None
    first_letter = donor_user.full_name[0].upper() if donor_user and donor_user.full_name else "D"
    masked_name = f"Donor {first_letter}***"

    # Privacy rounding for map visualization (~1km accuracy)
    approx_lat = round(float(donor.latitude), 2) if (donor and donor.latitude is not None) else None
    approx_lng = round(float(donor.longitude), 2) if (donor and donor.longitude is not None) else None
    approx_area = donor.address if (donor and donor.address) else None

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
        approx_latitude=approx_lat,
        approx_longitude=approx_lng,
        approx_area=approx_area,
    )


def format_blood_request_response(
    req: BloodRequest,
    viewer_user_id: Optional[UUID] = None,
    is_admin: bool = False,
) -> BloodRequestResponse:
    """Format a BloodRequest model into BloodRequestResponse with masked matches and attendant phone privacy."""
    masked_matches = [build_masked_match_response(m) for m in req.matches] if req.matches else []

    # Privacy check for attendant phone number:
    # Exposed only to:
    # 1. The recipient owner who created the request (req.recipient_id == viewer_user_id)
    # 2. The accepted donor (req.accepted_donor_id == viewer_user_id)
    # 3. Admins
    is_authorized = (
        is_admin
        or (viewer_user_id is not None and (viewer_user_id == req.recipient_id or viewer_user_id == req.accepted_donor_id))
    )

    exposed_phone = req.attendant_phone_number if is_authorized else mask_phone_number(req.attendant_phone_number)

    # Populate accepted donor summary when authorized
    accepted_donor_summary = None
    if req.accepted_donor_id and is_authorized and req.accepted_donor:
        donor_user = req.accepted_donor
        donor_profile = donor_user.donor
        area = donor_profile.address if donor_profile else None
        accepted_donor_summary = AcceptedDonorSummary(
            donor_id=donor_user.user_id,
            full_name=donor_user.full_name,
            phone=donor_user.phone,
            area_zone=area,
            email=donor_user.email,
        )

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
        patient_name=req.patient_name,
        hospital_name=req.hospital_name,
        area_zone=req.area_zone,
        attendant_phone_number=exposed_phone,
        volume_ml=float(req.volume_ml) if req.volume_ml is not None else None,
        accepted_donor_id=req.accepted_donor_id,
        accepted_donor=accepted_donor_summary,
        matches=masked_matches,
    )


@router.post("/", response_model=BloodRequestResponse, status_code=status.HTTP_201_CREATED)
def create_blood_request(
    request_data: BloodRequestCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create blood request with Phase 3 fields and trigger the Intelligent Matching Engine automatically."""
    recipient = db.query(Recipient).filter(Recipient.recipient_id == current_user.user_id).first()
    if not recipient:
        donor_addr = current_user.donor.address if current_user.donor and current_user.donor.address else "Dhaka, Bangladesh"
        recipient = Recipient(
            recipient_id=current_user.user_id,
            nid_passport_no="N/A",
            address=donor_addr,
            relationship_to_patient="Self",
            patient_name=current_user.full_name,
        )
        db.add(recipient)
        db.flush()

    recipient_id = recipient.recipient_id

    # Fallback/derivation for Phase 3 fields if omitted
    patient_name = request_data.patient_name or recipient.patient_name or current_user.full_name
    hospital_name = request_data.hospital_name or request_data.required_location
    attendant_phone = request_data.attendant_phone_number or current_user.phone
    volume_ml = request_data.volume_ml if request_data.volume_ml is not None else (float(request_data.quantity) * 450.0)

    blood_req = BloodRequest(
        recipient_id=recipient_id,
        blood_group=request_data.blood_group,
        component_type=request_data.component_type,
        quantity=request_data.quantity,
        urgency=request_data.urgency,
        required_location=request_data.required_location,
        latitude=request_data.latitude,
        longitude=request_data.longitude,
        status=RequestStatus.OPEN,
        notes=request_data.notes,
        patient_name=patient_name,
        hospital_name=hospital_name,
        area_zone=request_data.area_zone,
        attendant_phone_number=attendant_phone,
        volume_ml=volume_ml,
    )
    db.add(blood_req)
    db.flush()

    matches = run_matching_engine(db=db, request=blood_req, is_emergency=(request_data.urgency == RequestUrgency.EMERGENCY))
    if matches:
        blood_group_val = (
            blood_req.blood_group.value
            if hasattr(blood_req.blood_group, "value")
            else str(blood_req.blood_group)
        )

        display_hospital = blood_req.hospital_name or blood_req.required_location

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
                    hospital_name=display_hospital,
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
                        hospital_name=display_hospital,
                        match_id=str(m.match_id),
                        distance_km=float(m.distance_km) if m.distance_km is not None else None,
                        request_id=str(blood_req.request_id),
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

    return format_blood_request_response(blood_req, viewer_user_id=current_user.user_id, is_admin=False)


@router.post("/emergency", response_model=BloodRequestResponse, status_code=status.HTTP_201_CREATED)
def create_emergency_request(
    request_data: BloodRequestCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """High-priority endpoint: bypasses queues, expands radius immediately to 50 km, flags as EMERGENCY."""
    request_data.urgency = RequestUrgency.EMERGENCY

    recipient = db.query(Recipient).filter(Recipient.recipient_id == current_user.user_id).first()
    if not recipient:
        donor_addr = current_user.donor.address if current_user.donor and current_user.donor.address else "Dhaka, Bangladesh"
        recipient = Recipient(
            recipient_id=current_user.user_id,
            nid_passport_no="N/A",
            address=donor_addr,
            relationship_to_patient="Self",
            patient_name=current_user.full_name,
        )
        db.add(recipient)
        db.flush()

    recipient_id = recipient.recipient_id

    patient_name = request_data.patient_name or recipient.patient_name or current_user.full_name
    hospital_name = request_data.hospital_name or request_data.required_location
    attendant_phone = request_data.attendant_phone_number or current_user.phone
    volume_ml = request_data.volume_ml if request_data.volume_ml is not None else (float(request_data.quantity) * 450.0)

    blood_req = BloodRequest(
        recipient_id=recipient_id,
        blood_group=request_data.blood_group,
        component_type=request_data.component_type,
        quantity=request_data.quantity,
        urgency=RequestUrgency.EMERGENCY,
        required_location=request_data.required_location,
        latitude=request_data.latitude,
        longitude=request_data.longitude,
        status=RequestStatus.OPEN,
        notes=request_data.notes,
        patient_name=patient_name,
        hospital_name=hospital_name,
        area_zone=request_data.area_zone,
        attendant_phone_number=attendant_phone,
        volume_ml=volume_ml,
    )
    db.add(blood_req)
    db.flush()

    matches = run_matching_engine(db=db, request=blood_req, is_emergency=True)
    if matches:
        blood_group_val = (
            blood_req.blood_group.value
            if hasattr(blood_req.blood_group, "value")
            else str(blood_req.blood_group)
        )
        display_hospital = blood_req.hospital_name or blood_req.required_location

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
                hospital_name=display_hospital,
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

    return format_blood_request_response(blood_req, viewer_user_id=current_user.user_id, is_admin=False)


@router.get("/", response_model=List[BloodRequestResponse])
def list_blood_requests(
    blood_group: Optional[BloodGroup] = None,
    urgency: Optional[RequestUrgency] = None,
    status_filter: Optional[RequestStatus] = Query(None, alias="status"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """List blood requests with filters and attendant phone privacy protection."""
    query = db.query(BloodRequest).options(
        joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user),
        joinedload(BloodRequest.accepted_donor).joinedload(User.donor),
    )

    if blood_group:
        query = query.filter(BloodRequest.blood_group == blood_group)
    if urgency:
        query = query.filter(BloodRequest.urgency == urgency)
    if status_filter:
        query = query.filter(BloodRequest.status == status_filter)

    urgency_priority = case(
        (BloodRequest.urgency == RequestUrgency.EMERGENCY, 1),
        (BloodRequest.urgency == RequestUrgency.URGENT, 2),
        else_=3,
    )
    requests = query.order_by(urgency_priority.asc(), BloodRequest.request_date.desc()).all()
    viewer_id = current_user.user_id if current_user else None
    is_admin = current_user.role in [UserRole.SYSTEM_ADMIN, UserRole.HOSPITAL_ADMIN] if current_user else False
    return [
        format_blood_request_response(req, viewer_user_id=viewer_id, is_admin=is_admin)
        for req in requests
    ]


@router.get("/{request_id}", response_model=BloodRequestResponse)
def get_blood_request(
    request_id: UUID,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Get request details by ID with privacy protection."""
    req = (
        db.query(BloodRequest)
        .options(
            joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user),
            joinedload(BloodRequest.accepted_donor).joinedload(User.donor),
        )
        .filter(BloodRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    viewer_id = current_user.user_id if current_user else None
    is_admin = current_user.role in [UserRole.SYSTEM_ADMIN, UserRole.HOSPITAL_ADMIN] if current_user else False
    return format_blood_request_response(req, viewer_user_id=viewer_id, is_admin=is_admin)


@router.post("/{request_id}/accept", response_model=BloodRequestResponse)
def accept_blood_request(
    request_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Accept an open blood request as a donor, unmask attendant contact, and notify recipient."""
    req = (
        db.query(BloodRequest)
        .options(
            joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user),
            joinedload(BloodRequest.accepted_donor).joinedload(User.donor),
            joinedload(BloodRequest.recipient).joinedload(Recipient.user),
        )
        .filter(BloodRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    # 1. Self-acceptance check
    if req.recipient_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot accept your own blood request.",
        )

    # 2. Check if already accepted or terminal
    if req.status == RequestStatus.ACCEPTED:
        if req.accepted_donor_id == current_user.user_id:
            return format_blood_request_response(req, viewer_user_id=current_user.user_id, is_admin=False)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This blood request has already been accepted by another donor.",
            )
    elif req.status in [RequestStatus.COMPLETED, RequestStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This blood request is no longer active (status: {req.status.value}).",
        )

    # 3. Eligibility check for current user
    donor = get_or_create_donor(db, current_user)
    is_eligible, rejections, metrics = check_donor_eligibility(
        donor, target_component=req.component_type
    )
    if not is_eligible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "You are not currently eligible to accept this donation request.",
                "rejections": rejections,
                "metrics": metrics,
            },
        )

    # 4. Set status and accepted donor
    req.status = RequestStatus.ACCEPTED
    req.accepted_donor_id = current_user.user_id

    # 5. Dispatch transactional email alert to recipient
    recipient_user = req.recipient.user if req.recipient and req.recipient.user else None
    if not recipient_user:
        recipient_user = db.query(User).filter(User.user_id == req.recipient_id).first()

    if recipient_user and recipient_user.email:
        background_tasks.add_task(
            send_donor_accepted_alert,
            recipient_email=recipient_user.email,
            recipient_name=recipient_user.full_name or "Recipient",
            donor_name=current_user.full_name,
            donor_phone=current_user.phone,
            donor_area=donor.address or "Dhaka, Bangladesh",
            request_id=str(req.request_id),
        )

    log_system_action(
        db=db,
        action="ACCEPT_BLOOD_REQUEST",
        entity="blood_requests",
        entity_id=req.request_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(req)

    return format_blood_request_response(req, viewer_user_id=current_user.user_id, is_admin=False)


def resolve_request_completion(
    db: Session,
    req: BloodRequest,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    """Execute post-donation resolution:
    1. Set req.status = RequestStatus.COMPLETED.
    2. Write DonationHistory record for accepted donor.
    3. Update donor last_donation_date to date.today().
    4. Set donor availability_status to UNAVAILABLE (90-day recovery cooldown).
    5. Optionally dispatch thank-you alert email.
    """
    req.status = RequestStatus.COMPLETED

    if not req.accepted_donor_id:
        return

    donor = (
        db.query(Donor)
        .options(
            joinedload(Donor.user),
            joinedload(Donor.medical_info),
        )
        .filter(Donor.donor_id == req.accepted_donor_id)
        .first()
    )

    if donor:
        today = date.today()
        min_days = 90 if req.component_type == ComponentType.WHOLE_BLOOD else 14
        next_eligible_date = today + timedelta(days=min_days)
        next_eligible_str = next_eligible_date.strftime("%Y-%m-%d")

        hb = 13.5
        if donor.medical_info and donor.medical_info.hemoglobin_level is not None:
            hb = float(donor.medical_info.hemoglobin_level)

        hospital_disp = req.hospital_name or req.required_location or "Transfusion Center"
        notes = f"Completed donation for request #{str(req.request_id)[:8].upper()}"
        if req.patient_name:
            notes += f" (Patient: {req.patient_name})"

        donation_record = DonationHistory(
            donor_id=donor.donor_id,
            donation_date=today,
            component_type=req.component_type,
            quantity=float(req.quantity),
            hemoglobin_level=hb,
            center_name=hospital_disp,
            notes=notes,
        )
        db.add(donation_record)

        donor.last_donation_date = today
        donor.availability_status = AvailabilityStatus.UNAVAILABLE

        if background_tasks and donor.user and donor.user.email:
            background_tasks.add_task(
                send_donation_completed_thank_you_alert,
                donor_email=donor.user.email,
                donor_name=donor.user.full_name or "Valued Hero",
                hospital_name=hospital_disp,
                units=float(req.quantity),
                component_type=req.component_type.value if hasattr(req.component_type, "value") else str(req.component_type),
                next_eligible_date=next_eligible_str,
            )


@router.post("/{request_id}/complete", response_model=BloodRequestResponse)
def complete_blood_request(
    request_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Mark an accepted blood request as completed, log donor donation history,
    activate 90-day cooldown, and dispatch thank-you receipt.
    """
    req = (
        db.query(BloodRequest)
        .options(
            joinedload(BloodRequest.accepted_donor).joinedload(User.donor),
            joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user),
            joinedload(BloodRequest.recipient).joinedload(Recipient.user),
        )
        .filter(BloodRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    is_admin = current_user.role in [UserRole.SYSTEM_ADMIN, UserRole.HOSPITAL_ADMIN]
    is_owner = (req.recipient_id == current_user.user_id)

    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the request creator or an administrator can confirm donation completion.",
        )

    if req.status not in [RequestStatus.ACCEPTED, RequestStatus.PROCESSING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete request in status '{req.status.value}'. Request must be in 'ACCEPTED' or 'PROCESSING' status.",
        )

    if not req.accepted_donor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete request without an assigned accepted donor.",
        )

    resolve_request_completion(db=db, req=req, background_tasks=background_tasks)

    log_system_action(
        db=db,
        action="COMPLETE_BLOOD_REQUEST",
        entity="blood_requests",
        entity_id=req.request_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(req)
    return format_blood_request_response(req, viewer_user_id=current_user.user_id, is_admin=is_admin)


@router.post("/{request_id}/reopen", response_model=BloodRequestResponse)
def reopen_blood_request(
    request_id: UUID,
    background_tasks: BackgroundTasks,
    payload: Optional[RequestReopenPayload] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Cancel an active match and re-open blood request search (Doc Section 9).
    
    Rules:
    - Allowed by: Request creator (recipient), currently accepted donor, or admin.
    - Status check: Request must be in ACCEPTED, PROCESSING, or CANCELLED status.
    - Completion check: Cannot re-open an already COMPLETED request.
    - Zero penalty: Previous donor is NOT penalized (no cooldown, no donation history).
    - Status revert: Request reverts to OPEN, accepted_donor_id = None.
    - Restart search: Matching engine re-runs and alerts candidate donors.
    """
    req = (
        db.query(BloodRequest)
        .options(
            joinedload(BloodRequest.accepted_donor).joinedload(User.donor),
            joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user),
            joinedload(BloodRequest.recipient).joinedload(Recipient.user),
        )
        .filter(BloodRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    is_admin = current_user.role in [UserRole.SYSTEM_ADMIN, UserRole.HOSPITAL_ADMIN]
    is_owner = (req.recipient_id == current_user.user_id)
    is_accepted_donor = (req.accepted_donor_id == current_user.user_id)

    if not (is_admin or is_owner or is_accepted_donor):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this match or re-open the blood request.",
        )

    if req.status == RequestStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot re-open a completed blood request where donation transfusion has already taken place.",
        )

    if req.status == RequestStatus.OPEN and not req.accepted_donor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Blood request is already open and currently searching for donors.",
        )

    # 1. Capture released donor and parties for notifications
    released_donor_user = req.accepted_donor
    released_donor = released_donor_user.donor if released_donor_user and released_donor_user.donor else None
    released_donor_name = released_donor_user.full_name if released_donor_user else "Volunteer Donor"

    cancelled_by_label = (
        "donor" if is_accepted_donor
        else "recipient" if is_owner
        else "administrator"
    )

    reason = payload.reason if payload and payload.reason else None

    # 2. Reset match for released donor to DECLINED
    if req.accepted_donor_id:
        for match in req.matches:
            if match.donor_id == req.accepted_donor_id:
                match.response_status = MatchResponseStatus.DECLINED

    # 3. Ensure released donor remains AVAILABLE and has ZERO cooldown penalty
    if released_donor:
        released_donor.availability_status = AvailabilityStatus.AVAILABLE

    # 4. Revert request status to OPEN and clear accepted_donor_id
    req.status = RequestStatus.OPEN
    req.accepted_donor_id = None

    # 5. Restart matching engine to find alternative compatible donors
    matches = run_matching_engine(
        db=db,
        request=req,
        is_emergency=(req.urgency == RequestUrgency.EMERGENCY),
    )

    blood_group_val = (
        req.blood_group.value
        if hasattr(req.blood_group, "value")
        else str(req.blood_group)
    )
    display_hospital = req.hospital_name or req.required_location or "Transfusion Center"

    # 6. Dispatch alerts to new candidate donors
    if matches and background_tasks:
        if req.urgency == RequestUrgency.EMERGENCY:
            emergency_emails = [
                m.donor.user.email
                for m in matches
                if m.donor and m.donor.user and m.donor.user.email
                and (not released_donor or m.donor_id != released_donor.donor_id)
            ]
            if emergency_emails:
                background_tasks.add_task(
                    send_emergency_broadcast_alert,
                    donor_emails=emergency_emails,
                    blood_group=blood_group_val,
                    hospital_name=display_hospital,
                    units_needed=float(req.quantity),
                    request_id=str(req.request_id),
                )
        else:
            for m in matches:
                if m.donor and m.donor.user and m.donor.user.email:
                    if released_donor and m.donor_id == released_donor.donor_id:
                        continue
                    background_tasks.add_task(
                        send_single_donor_match_alert,
                        donor_email=m.donor.user.email,
                        donor_name=m.donor.user.full_name or "Valued Donor",
                        blood_group=blood_group_val,
                        hospital_name=display_hospital,
                        match_id=str(m.match_id),
                        distance_km=float(m.distance_km) if m.distance_km is not None else None,
                        request_id=str(req.request_id),
                    )

    # 7. Notify the opposite party of the cancellation
    recipient_user = req.recipient.user if req.recipient and req.recipient.user else None
    if not recipient_user:
        recipient_user = db.query(User).filter(User.user_id == req.recipient_id).first()

    recipient_name = recipient_user.full_name if recipient_user else "Recipient"

    if background_tasks:
        if is_accepted_donor and recipient_user and recipient_user.email:
            # Donor cancelled -> notify recipient
            background_tasks.add_task(
                send_match_cancelled_reopened_alert,
                target_email=recipient_user.email,
                recipient_name=recipient_name,
                donor_name=released_donor_name,
                hospital_name=display_hospital,
                cancelled_by="donor",
                request_id=str(req.request_id),
                reason=reason,
            )
        elif is_owner and released_donor_user and released_donor_user.email:
            # Recipient cancelled -> notify donor
            background_tasks.add_task(
                send_match_cancelled_reopened_alert,
                target_email=released_donor_user.email,
                recipient_name=released_donor_name,
                donor_name=released_donor_name,
                hospital_name=display_hospital,
                cancelled_by="recipient",
                request_id=str(req.request_id),
                reason=reason,
            )

    log_system_action(
        db=db,
        action="REOPEN_BLOOD_REQUEST",
        entity="blood_requests",
        entity_id=req.request_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(req)
    return format_blood_request_response(req, viewer_user_id=current_user.user_id, is_admin=is_admin)


@router.patch("/{request_id}/status", response_model=BloodRequestResponse)
def update_request_status(
    request_id: UUID,
    status_update: RequestStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update blood request lifecycle status: OPEN -> ACCEPTED -> PROCESSING -> COMPLETED / CANCELLED."""
    req = (
        db.query(BloodRequest)
        .options(
            joinedload(BloodRequest.accepted_donor).joinedload(User.donor),
            joinedload(BloodRequest.matches).joinedload(DonorMatch.donor).joinedload(Donor.user),
        )
        .filter(BloodRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood request not found.",
        )

    is_admin = current_user.role in [UserRole.SYSTEM_ADMIN, UserRole.HOSPITAL_ADMIN]
    is_owner = (req.recipient_id == current_user.user_id)
    is_accepted_donor = (req.accepted_donor_id == current_user.user_id)

    # Permission check
    if not (is_admin or is_owner or is_accepted_donor):
        # A compatible user accepting the request can transition to ACCEPTED
        if status_update.status == RequestStatus.ACCEPTED:
            req.accepted_donor_id = current_user.user_id
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this blood request status.",
            )

    if status_update.accepted_donor_id:
        req.accepted_donor_id = status_update.accepted_donor_id
    elif status_update.status == RequestStatus.ACCEPTED and not req.accepted_donor_id:
        req.accepted_donor_id = current_user.user_id

    if status_update.status == RequestStatus.COMPLETED:
        resolve_request_completion(db=db, req=req)
    else:
        req.status = status_update.status

    log_system_action(
        db=db,
        action=f"UPDATE_REQUEST_STATUS_{status_update.status.value}",
        entity="blood_requests",
        entity_id=req.request_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(req)
    return format_blood_request_response(req, viewer_user_id=current_user.user_id, is_admin=is_admin)


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
