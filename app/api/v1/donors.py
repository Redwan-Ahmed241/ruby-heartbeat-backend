"""Donors router: /api/v1/donors."""
from datetime import date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.enums import UserRole, BloodGroup, AvailabilityStatus
from app.models.user import User, Donor, MedicalInfo, DonationHistory
from app.schemas.donor import (
    DonorResponse,
    DonorProfileUpdate,
    AvailabilityUpdate,
    MedicalInfoUpsert,
    MedicalInfoResponse,
    DonationHistoryCreate,
    DonationHistoryResponse,
    EligibilityCheckResponse,
)
from app.api.deps import get_current_active_user, RequireRoles
from app.services.eligibility import check_donor_eligibility
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
    """Fetch donor's historical donation log."""
    donor = get_or_create_donor(db, current_user)
    history = (
        db.query(DonationHistory)
        .filter(DonationHistory.donor_id == donor.donor_id)
        .order_by(DonationHistory.donation_date.desc())
        .all()
    )
    return history


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
