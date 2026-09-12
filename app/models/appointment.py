"""Appointment models."""
import uuid
from datetime import datetime, date, time
from sqlalchemy import (
    Column,
    Date,
    Time,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import AppointmentStatus


class Appointment(Base):
    __tablename__ = "appointments"

    appointment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    donor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("donors.donor_id", ondelete="CASCADE"),
        nullable=False,
    )
    center_id = Column(
        UUID(as_uuid=True),
        ForeignKey("hospitals.hospital_id", ondelete="CASCADE"),
        nullable=False,
    )
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(Time, nullable=False)
    status = Column(
        SQLEnum(AppointmentStatus, name="appointment_status_enum"),
        default=AppointmentStatus.SCHEDULED,
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    donor = relationship("Donor", back_populates="appointments")
    hospital = relationship("Hospital", back_populates="appointments")
