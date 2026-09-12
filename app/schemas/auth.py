"""Pydantic schemas for authentication and user management."""
from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from app.core.enums import UserRole, UserStatus, BloodGroup, AvailabilityStatus


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: str
    role: UserRole
    type: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class DonorProfileCreate(BaseModel):
    blood_group: BloodGroup
    date_of_birth: date
    gender: str = Field(..., max_length=10)
    weight: float = Field(..., ge=20.0, le=300.0)
    address: str = Field(..., max_length=255)
    latitude: float
    longitude: float
    hemoglobin_level: Optional[float] = Field(default=13.0, ge=5.0, le=25.0)
    chronic_diseases: Optional[str] = None
    medications: Optional[str] = None
    allergies: Optional[str] = None
    other_notes: Optional[str] = None


class RecipientProfileCreate(BaseModel):
    nid_passport_no: str = Field(..., max_length=50)
    address: str = Field(..., max_length=255)
    relationship_to_patient: str = Field(..., max_length=100)
    patient_name: str = Field(..., max_length=100)


class HospitalProfileCreate(BaseModel):
    hospital_name: str = Field(..., max_length=100)
    address: str = Field(..., max_length=255)
    latitude: float
    longitude: float
    contact_number: str = Field(..., max_length=20)


class UserRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=6, max_length=20)
    password: str = Field(..., min_length=6)
    role: UserRole

    # Role-specific profiles (provided based on role)
    donor_profile: Optional[DonorProfileCreate] = None
    recipient_profile: Optional[RecipientProfileCreate] = None
    hospital_profile: Optional[HospitalProfileCreate] = None


class DonorBriefResponse(BaseModel):
    donor_id: UUID
    blood_group: BloodGroup
    date_of_birth: date
    gender: str
    weight: float
    address: str
    latitude: float
    longitude: float
    last_donation_date: Optional[date] = None
    availability_status: AvailabilityStatus

    model_config = ConfigDict(from_attributes=True)


class RecipientBriefResponse(BaseModel):
    recipient_id: UUID
    nid_passport_no: str
    address: str
    relationship_to_patient: str
    patient_name: str

    model_config = ConfigDict(from_attributes=True)


class HospitalBriefResponse(BaseModel):
    hospital_id: UUID
    hospital_name: str
    address: str
    latitude: float
    longitude: float
    contact_number: str

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    user_id: UUID
    full_name: str
    email: EmailStr
    phone: str
    role: UserRole
    status: UserStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserResponse(UserBase):
    donor: Optional[DonorBriefResponse] = None
    recipient: Optional[RecipientBriefResponse] = None
    hospital: Optional[HospitalBriefResponse] = None
