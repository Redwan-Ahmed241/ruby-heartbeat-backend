"""Donors router: /api/v1/donors."""
from datetime import date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.enums import UserRole, BloodGroup, AvailabilityStatus, UserStatus
from app.models.user import User, Donor, MedicalInfo, DonationHistory
from app.models.request import BloodRequest, DonorMatch
from app.core.enums import MatchResponseStatus, RequestStatus
from app.schemas.donor import (
    DonorResponse,
    DonorProfileUpdate,
    AvailabilityUpdate,
    MedicalInfoUpsert,
    MedicalInfoResponse,
    DonationHistoryCreate,
    DonationHistoryResponse,
    EligibilityCheckResponse,
    TopDonorResponse,
)
from app.api.deps import get_current_active_user, RequireRoles
from app.services.eligibility import check_donor_eligibility, calculate_donor_tier
from app.services.audit import log_system_action

router = APIRouter(prefix="/donors", tags=["Donors"])


def get_or_create_donor(db: Session, current_user: User) -> Donor:
    """Retrieve donor profile or auto-provision for unified accounts."""
    donor = (
        db.query(Donor)
        .options(joinedload(Donor.medical_info))
        .filter(Donor.donor_id == current_user.user_id)
        .first()
    )
    if not donor:
        addr = (
            current_user.recipient.address
            if current_user.recipient and current_user.recipient.address
            else "Dhaka, Bangladesh"
        )
        donor = Donor(
            donor_id=current_user.user_id,
            blood_group=BloodGroup.O_POSITIVE,
            date_of_birth=date(2000, 1, 1),
            gender="Other",
            weight=65.0,
            address=addr,
            latitude=23.8103,
            longitude=90.4125,
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        db.add(donor)
        db.flush()

        med_info = MedicalInfo(
            donor_id=donor.donor_id,
            hemoglobin_level=13.0,
        )
        db.add(med_info)
        db.flush()
        db.refresh(donor)
    return donor


@router.get("/me", response_model=DonorResponse)
@router.get("/profile", response_model=DonorResponse)
def get_donor_profile(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve donor profile, clinical parameters, coordinates, and availability status."""
    return get_or_create_donor(db, current_user)


@router.put("/profile", response_model=DonorResponse)
def update_donor_profile(
    profile_data: DonorProfileUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update donor personal data, address, and coordinates."""
    donor = get_or_create_donor(db, current_user)

    for field, value in profile_data.model_dump(exclude_unset=True).items():
        setattr(donor, field, value)

    log_system_action(
        db=db,
        action="UPDATE_DONOR_PROFILE",
        entity="donors",
        entity_id=donor.donor_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(donor)
    return donor


@router.patch("/availability", response_model=DonorResponse)
def toggle_availability(
    status_data: AvailabilityUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Toggle donor availability between AVAILABLE and UNAVAILABLE."""
    donor = get_or_create_donor(db, current_user)

    donor.availability_status = status_data.availability_status

    log_system_action(
        db=db,
        action=f"SET_AVAILABILITY_{status_data.availability_status.value}",
        entity="donors",
        entity_id=donor.donor_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(donor)
    return donor


@router.get("/eligibility", response_model=EligibilityCheckResponse)
def get_eligibility(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Run automated eligibility check against donor's current records."""
    donor = get_or_create_donor(db, current_user)

    is_eligible, rejections, metrics = check_donor_eligibility(donor)
    return EligibilityCheckResponse(
        is_eligible=is_eligible,
        rejection_reasons=rejections,
        age=metrics.get("age"),
        weight=metrics.get("weight"),
        hemoglobin_level=metrics.get("hemoglobin_level"),
        days_since_last_donation=metrics.get("days_since_last_donation"),
        last_donation_date=metrics.get("last_donation_date"),
        cooldown_active=metrics.get("cooldown_active", False),
        next_eligible_date=metrics.get("next_eligible_date"),
        cooldown_days_remaining=metrics.get("cooldown_days_remaining"),
    )


@router.post("/medical-info", response_model=MedicalInfoResponse)
def upsert_medical_info(
    med_data: MedicalInfoUpsert,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Upsert donor medical info (hemoglobin level, allergies, chronic diseases)."""
    donor = get_or_create_donor(db, current_user)

    med_info = (
        db.query(MedicalInfo)
        .filter(MedicalInfo.donor_id == donor.donor_id)
        .first()
    )
    if not med_info:
        med_info = MedicalInfo(donor_id=donor.donor_id)
        db.add(med_info)

    for field, value in med_data.model_dump().items():
        setattr(med_info, field, value)

    log_system_action(
        db=db,
        action="UPSERT_MEDICAL_INFO",
        entity="medical_info",
        entity_id=med_info.medical_info_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(med_info)
    return med_info


@router.get("/history", response_model=List[DonationHistoryResponse])
def get_donation_history(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Fetch donor's historical donation log including completed matches."""
    donor = get_or_create_donor(db, current_user)
    history_records = (
        db.query(DonationHistory)
        .filter(DonationHistory.donor_id == donor.donor_id)
        .order_by(DonationHistory.donation_date.desc())
        .all()
    )

    results: List[DonationHistoryResponse] = []
    seen_dates = set()
    for h in history_records:
        seen_dates.add(h.donation_date)
        results.append(
            DonationHistoryResponse(
                history_id=h.history_id,
                donor_id=h.donor_id,
                donation_date=h.donation_date,
                component_type=h.component_type,
                quantity=float(h.quantity),
                hemoglobin_level=float(h.hemoglobin_level),
                center_name=h.center_name,
                notes=h.notes,
                created_at=h.created_at,
                completed_at=h.created_at,
                units_donated=float(h.quantity),
                facility_name=h.center_name,
            )
        )

    # Also capture completed matches
    completed_matches = (
        db.query(DonorMatch, BloodRequest)
        .join(BloodRequest, BloodRequest.request_id == DonorMatch.request_id)
        .filter(
            DonorMatch.donor_id == donor.donor_id,
            BloodRequest.status == RequestStatus.COMPLETED,
        )
        .all()
    )
    for m, req in completed_matches:
        d_date = m.completed_at.date() if m.completed_at else (req.request_date.date() if req.request_date else date.today())
        if d_date not in seen_dates:
            seen_dates.add(d_date)
            fac_name = req.hospital_name or req.required_location or "Transfusion Facility"
            results.append(
                DonationHistoryResponse(
                    history_id=m.match_id,
                    donor_id=donor.donor_id,
                    donation_date=d_date,
                    component_type=req.component_type,
                    quantity=float(req.quantity),
                    hemoglobin_level=13.5,
                    center_name=fac_name,
                    notes=f"Completed donation for request #{str(req.request_id)[:8].upper()}",
                    created_at=req.request_date,
                    completed_at=m.completed_at or req.request_date,
                    units_donated=float(req.quantity),
                    facility_name=fac_name,
                )
            )

    results.sort(key=lambda r: r.donation_date, reverse=True)
    return results


@router.post("/history", response_model=DonationHistoryResponse, status_code=status.HTTP_201_CREATED)
def record_donation_history(
    history_data: DonationHistoryCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Record a past donation in the donor's history."""
    donor = get_or_create_donor(db, current_user)
    target_donor_id = donor.donor_id
    new_entry = DonationHistory(
        donor_id=target_donor_id,
        **history_data.model_dump(),
    )
    db.add(new_entry)

    # Update donor's last_donation_date if newer
    if not donor.last_donation_date or history_data.donation_date > donor.last_donation_date:
        donor.last_donation_date = history_data.donation_date

    db.commit()
    db.refresh(new_entry)
    return new_entry


@router.get("/top", response_model=List[TopDonorResponse])
def get_top_donors(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Public leaderboard endpoint returning top ranked donors.
    
    Ranking priority:
    1. Tier priority (Diamond: 4 > Platinum: 3 > Silver: 2 > Bronze: 1)
    2. Verified completed donation count descending
    3. Most recent donation date descending
    """
    donor_counts = (
        db.query(
            DonationHistory.donor_id,
            func.count(DonationHistory.history_id).label("donation_count"),
            func.max(DonationHistory.donation_date).label("latest_donation_date"),
        )
        .group_by(DonationHistory.donor_id)
        .having(func.count(DonationHistory.history_id) >= 1)
        .subquery()
    )

    results = (
        db.query(
            Donor,
            donor_counts.c.donation_count,
            donor_counts.c.latest_donation_date,
        )
        .join(donor_counts, Donor.donor_id == donor_counts.c.donor_id)
        .join(Donor.user)
        .options(joinedload(Donor.user))
        .filter(User.status == UserStatus.ACTIVE)
        .all()
    )

    ranked_donors = []
    for donor, count, latest_date in results:
        tier, icon, priority = calculate_donor_tier(count)
        area_zone = donor.address.split(",")[0].strip() if donor.address else "Dhaka"
        last_date = latest_date or donor.last_donation_date

        ranked_donors.append({
            "donor_id": donor.donor_id,
            "full_name": donor.user.full_name if donor.user else "Anonymous Donor",
            "blood_group": donor.blood_group,
            "area_zone": area_zone,
            "donation_count": count,
            "tier": tier,
            "badge_icon": icon,
            "priority": priority,
            "last_donation_date": last_date,
        })

    # Sort strictly by tier priority desc, donation_count desc, last_donation_date desc
    ranked_donors.sort(
        key=lambda d: (
            d["priority"],
            d["donation_count"],
            d["last_donation_date"] or date.min,
        ),
        reverse=True,
    )

    top_donors = ranked_donors[:limit]
    return [
        TopDonorResponse(
            donor_id=d["donor_id"],
            full_name=d["full_name"],
            blood_group=d["blood_group"],
            area_zone=d["area_zone"],
            donation_count=d["donation_count"],
            tier=d["tier"],
            badge_icon=d["badge_icon"],
            last_donation_date=d["last_donation_date"],
        )
        for d in top_donors
    ]


@router.get("/leaderboard", response_model=List[TopDonorResponse])
def get_donor_leaderboard(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Public leaderboard endpoint returning top ranked donors with blood group."""
    return get_top_donors(limit=limit, db=db)
