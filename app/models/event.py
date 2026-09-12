"""Donation events, participants, and campaign notice models."""
import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column,
    String,
    Date,
    DateTime,
    Text,
    ForeignKey,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import (
    EventStatus,
    ParticipantRole,
    ParticipantStatus,
)


class DonationEvent(Base):
    __tablename__ = "donation_events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    organizer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    location = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(
        SQLEnum(EventStatus, name="event_status_enum"),
        default=EventStatus.UPCOMING,
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
    organizer = relationship("User", foreign_keys=[organizer_id])
    participants = relationship("EventParticipant", back_populates="event", cascade="all, delete-orphan")


class EventParticipant(Base):
    __tablename__ = "event_participants"

    participant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("donation_events.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(
        SQLEnum(ParticipantRole, name="participant_role_enum"),
        default=ParticipantRole.PARTICIPANT,
        nullable=False,
    )
    status = Column(
        SQLEnum(ParticipantStatus, name="participant_status_enum"),
        default=ParticipantStatus.REGISTERED,
        nullable=False,
    )
    registered_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    checkin_time = Column(DateTime, nullable=True)

    # Relationships
    event = relationship("DonationEvent", back_populates="participants")
    user = relationship("User")


class CampaignNotice(Base):
    __tablename__ = "campaign_notices"

    notice_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    source = Column(String(100), nullable=False)
    publish_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=False)
    link = Column(String(255), nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())

    # Relationships
    creator = relationship("User")
