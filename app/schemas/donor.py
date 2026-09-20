"""Pydantic schemas for donor profile, medical info, and donation history."""
from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from app.core.enums import BloodGroup, ComponentType, AvailabilityStatus


class DonorProfileUpdate(BaseModel):
    gender: Optional[str] = Field(None, max_length=10)
    weight: Optional[float] = Field(None, ge=20.0, le=300.0)
    address: Optional[str] = Field(None, max_length=255)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_donation_date: Optional[date] = None


class AvailabilityUpdate(BaseModel):
    availability_status: AvailabilityStatus


class MedicalInfoUpsert(BaseModel):
    hemoglobin_level: float = Field(..., ge=5.0, le=25.0)
    chronic_diseases: Optional[str] = None
    medications: Optional[str] = None
    allergies: Optional[str] = None
    other_notes: Optional[str] = None


class MedicalInfoResponse(BaseModel):
    medical_info_id: UUID
    donor_id: UUID
    hemoglobin_level: float
    chronic_diseases: Optional[str]
    medications: Optional[str]
    allergies: Optional[str]
    other_notes: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class DonationHistoryCreate(BaseModel):
    donation_date: date
    component_type: ComponentType
    quantity: float = Field(..., gt=0)
    hemoglobin_level: float = Field(..., ge=5.0, le=25.0)
    center_name: str = Field(..., max_length=100)
    notes: Optional[str] = None


class DonationHistoryResponse(BaseModel):
    history_id: UUID
    donor_id: UUID
    donation_date: date
    component_type: ComponentType
    quantity: float
    hemoglobin_level: float
    center_name: str
    notes: Optional[str]
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class EligibilityCheckResponse(BaseModel):
    is_eligible: bool
    rejection_reasons: List[str]
    age: Optional[int] = None
    weight: Optional[float] = None
    hemoglobin_level: Optional[float] = None
    days_since_last_donation: Optional[int] = None
    last_donation_date: Optional[date] = None
    cooldown_active: bool = False
    next_eligible_date: Optional[date] = None
    cooldown_days_remaining: Optional[int] = None


class DonorResponse(BaseModel):
    donor_id: UUID
    blood_group: BloodGroup
    date_of_birth: date
    gender: str
    weight: float
    address: str
    latitude: float
    longitude: float
    last_donation_date: Optional[date]
    availability_status: AvailabilityStatus
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    medical_info: Optional[MedicalInfoResponse] = None

    model_config = ConfigDict(from_attributes=True)


class TopDonorResponse(BaseModel):
    donor_id: UUID
    full_name: str
    blood_group: BloodGroup
    area_zone: Optional[str] = None
    donation_count: int
    tier: str
    badge_icon: str
    last_donation_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)

