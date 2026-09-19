"""User and role related models."""
import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column,
    String,
    Date,
    DateTime,
    Numeric,
    Text,
    ForeignKey,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import (
    UserRole,
    UserStatus,
    BloodGroup,
    ComponentType,
    AvailabilityStatus,
)


class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole, name="user_role_enum"), nullable=False)
    status = Column(SQLEnum(UserStatus, name="user_status_enum"), default=UserStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    donor = relationship("Donor", back_populates="user", uselist=False, cascade="all, delete-orphan")
    recipient = relationship("Recipient", back_populates="user", uselist=False, cascade="all, delete-orphan")
    hospital = relationship("Hospital", back_populates="user", uselist=False, cascade="all, delete-orphan")
    system_logs = relationship("SystemLog", back_populates="user")


class Donor(Base):
    __tablename__ = "donors"

    donor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    blood_group = Column(SQLEnum(BloodGroup, name="blood_group_enum"), nullable=False, index=True)
    date_of_birth = Column(Date, nullable=False)
    gender = Column(String(10), nullable=False)
    weight = Column(Numeric(5, 2), nullable=False)
    address = Column(String(255), nullable=False)
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)
    last_donation_date = Column(Date, nullable=True)
    availability_status = Column(
        SQLEnum(AvailabilityStatus, name="availability_status_enum"),
        default=AvailabilityStatus.AVAILABLE,
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User", back_populates="donor")
    medical_info = relationship("MedicalInfo", back_populates="donor", uselist=False, cascade="all, delete-orphan")
    donation_history = relationship("DonationHistory", back_populates="donor", cascade="all, delete-orphan")
    matches = relationship("DonorMatch", back_populates="donor", cascade="all, delete-orphan")


class MedicalInfo(Base):
    __tablename__ = "medical_info"

    medical_info_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    donor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("donors.donor_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    hemoglobin_level = Column(Numeric(4, 1), nullable=False)
    chronic_diseases = Column(Text, nullable=True)
    medications = Column(Text, nullable=True)
    allergies = Column(Text, nullable=True)
    other_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    donor = relationship("Donor", back_populates="medical_info")


class DonationHistory(Base):
    __tablename__ = "donation_history"

    history_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    donor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("donors.donor_id", ondelete="CASCADE"),
        nullable=False,
    )
    donation_date = Column(Date, nullable=False)
    component_type = Column(SQLEnum(ComponentType, name="component_type_enum"), nullable=False)
    quantity = Column(Numeric(5, 2), nullable=False)
    hemoglobin_level = Column(Numeric(4, 1), nullable=False)
    center_name = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())

    # Relationships
    donor = relationship("Donor", back_populates="donation_history")


class Recipient(Base):
    __tablename__ = "recipients"

    recipient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    nid_passport_no = Column(String(50), nullable=False)
    address = Column(String(255), nullable=False)
    relationship_to_patient = Column(String(100), nullable=False)
    patient_name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User", back_populates="recipient")
    blood_requests = relationship("BloodRequest", back_populates="recipient", cascade="all, delete-orphan")


class Hospital(Base):
    __tablename__ = "hospitals"

    hospital_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    hospital_name = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)
    contact_number = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User", back_populates="hospital")
    inventory = relationship("BloodInventory", back_populates="hospital", cascade="all, delete-orphan")
