from app.schemas.donor import MedicalInfoResponse
from app.models.user import calculate_age
"""Pydantic schemas for authentication and user management."""
from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, computed_field, model_validator
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
    date_of_birth: Optional[date] = None
    age: Optional[int] = None
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
    role: Optional[UserRole] = UserRole.DONOR
    date_of_birth: date  # Mandatory
    age: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def extract_dob_from_profile(cls, data):
        if isinstance(data, dict):
            if "date_of_birth" not in data or not data["date_of_birth"]:
                dp = data.get("donor_profile")
                if isinstance(dp, dict) and dp.get("date_of_birth"):
                    data["date_of_birth"] = dp["date_of_birth"]
        return data

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob_and_age(cls, v: date, info) -> date:
        if v > date.today():
            raise ValueError("Date of birth cannot be in the future.")

        age = calculate_age(v)
        role = info.data.get("role")
        role_str = getattr(role, "value", str(role)) if role is not None else None

        if role_str == "DONOR" or role == UserRole.DONOR:
            if age < 18:
                raise ValueError(f"Donor must be at least 18 years old (calculated age: {age} years).")
            if age > 65:
                raise ValueError(f"Maximum eligible age for regular blood donation is 65 years (calculated age: {age} years).")
        elif age < 1:
            raise ValueError("Please provide a valid date of birth.")

        return v

    @model_validator(mode="after")
    def populate_calculated_age(self):
        if self.date_of_birth:
            self.age = calculate_age(self.date_of_birth)
        return self

    # Unified account profile fields
    blood_group: Optional[BloodGroup] = None
    gender: Optional[str] = Field(default=None, max_length=10)
    weight: Optional[float] = Field(default=None, ge=20.0, le=300.0)
    address: Optional[str] = Field(default=None, max_length=255)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    nid_passport_no: Optional[str] = Field(default=None, max_length=50)
    nid_or_birth_cert: Optional[str] = Field(default=None, max_length=50)

    # Role-specific profiles (retained for backward compatibility)
    donor_profile: Optional[DonorProfileCreate] = None
    recipient_profile: Optional[RecipientProfileCreate] = None
    hospital_profile: Optional[HospitalProfileCreate] = None


UserCreate = UserRegisterRequest


class DonorBriefResponse(BaseModel):
    donor_id: UUID
    blood_group: BloodGroup
    date_of_birth: Optional[date] = None
    gender: str
    weight: float
    address: str
    latitude: float
    longitude: float
    last_donation_date: Optional[date] = None
    availability_status: AvailabilityStatus
    total_donations: Optional[int] = 0
    medical_info: Optional[MedicalInfoResponse] = None

    @computed_field
    def age(self) -> Optional[int]:
        if self.date_of_birth:
            return calculate_age(self.date_of_birth)
        return None

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
    date_of_birth: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    nid_or_birth_cert: Optional[str] = None
    backup_phone: Optional[str] = None

    @computed_field
    def age(self) -> Optional[int]:
        if self.date_of_birth:
            return calculate_age(self.date_of_birth)
        return None

    model_config = ConfigDict(from_attributes=True)


class UserResponse(UserBase):
    donor: Optional[DonorBriefResponse] = None
    recipient: Optional[RecipientBriefResponse] = None
    hospital: Optional[HospitalBriefResponse] = None


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[str] = Field(None, min_length=6, max_length=20)
    backup_phone: Optional[str] = Field(None, max_length=20)
    location_zone: Optional[str] = None
    address: Optional[str] = Field(None, max_length=255)
    blood_group: Optional[BloodGroup] = None
    date_of_birth: Optional[date] = None
    last_donation_date: Optional[date] = None
    weight: Optional[float] = Field(None, ge=20.0, le=300.0)
    hemoglobin: Optional[float] = Field(None, ge=5.0, le=25.0)
    hemoglobin_level: Optional[float] = Field(None, ge=5.0, le=25.0)
    age: Optional[int] = Field(None, ge=18, le=65)

ProfileUpdateSchema = UserProfileUpdate
