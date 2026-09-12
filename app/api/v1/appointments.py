"""Appointments router: /api/v1/appointments."""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole, AppointmentStatus
from app.models.user import User, Donor, Hospital
from app.models.appointment import Appointment
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentStatusUpdate,
)
from app.api.deps import get_current_active_user, RequireRoles
from app.services.audit import log_system_action

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.post("/", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_appointment(
    appointment_data: AppointmentCreate,
    current_user: User = Depends(RequireRoles([UserRole.DONOR])),
    db: Session = Depends(get_db),
):
    """Book a donation appointment at a hospital center."""
    hospital = db.query(Hospital).filter(Hospital.hospital_id == appointment_data.center_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital center not found.",
        )

    new_appointment = Appointment(
        donor_id=current_user.user_id,
        center_id=appointment_data.center_id,
        appointment_date=appointment_data.appointment_date,
        appointment_time=appointment_data.appointment_time,
        status=AppointmentStatus.SCHEDULED,
    )
    db.add(new_appointment)

    log_system_action(
        db=db,
        action="BOOK_APPOINTMENT",
        entity="appointments",
        entity_id=new_appointment.appointment_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(new_appointment)
    return new_appointment


@router.get("/my-appointments", response_model=List[AppointmentResponse])
def get_my_appointments(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List appointments for authenticated donor or hospital center."""
    query = db.query(Appointment)
    if current_user.role == UserRole.DONOR:
        query = query.filter(Appointment.donor_id == current_user.user_id)
    elif current_user.role == UserRole.HOSPITAL_ADMIN:
        hosp = db.query(Hospital).filter(Hospital.user_id == current_user.user_id).first()
        if hosp:
            query = query.filter(Appointment.center_id == hosp.hospital_id)
        else:
            return []
    
    return query.order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc()).all()


@router.patch("/{appointment_id}/status", response_model=AppointmentResponse)
def update_appointment_status(
    appointment_id: UUID,
    status_update: AppointmentStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update appointment status (COMPLETED, CANCELLED)."""
    appointment = db.query(Appointment).filter(Appointment.appointment_id == appointment_id).first()
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )

    # Permission check: Donor or Center Hospital Admin
    is_donor = appointment.donor_id == current_user.user_id
    is_center_admin = False
    if current_user.role == UserRole.HOSPITAL_ADMIN:
        hosp = db.query(Hospital).filter(Hospital.user_id == current_user.user_id).first()
        if hosp and hosp.hospital_id == appointment.center_id:
            is_center_admin = True

    if not (is_donor or is_center_admin or current_user.role == UserRole.SYSTEM_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this appointment.",
        )

    appointment.status = status_update.status

    log_system_action(
        db=db,
        action=f"UPDATE_APPOINTMENT_{status_update.status.value}",
        entity="appointments",
        entity_id=appointment.appointment_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(appointment)
    return appointment
