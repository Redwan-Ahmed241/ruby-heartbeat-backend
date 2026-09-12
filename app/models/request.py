"""Blood requests, donor matches, and communication models."""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Numeric,
    Text,
    Boolean,
    ForeignKey,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import (
    BloodGroup,
    ComponentType,
    RequestUrgency,
    RequestStatus,
    MatchResponseStatus,
    CommunicationChannel,
)


class BloodRequest(Base):
    __tablename__ = "blood_requests"

    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("recipients.recipient_id", ondelete="CASCADE"),
        nullable=False,
    )
    blood_group = Column(SQLEnum(BloodGroup, name="blood_group_enum"), nullable=False)
    component_type = Column(SQLEnum(ComponentType, name="component_type_enum"), nullable=False)
    quantity = Column(Numeric(5, 2), nullable=False)
    urgency = Column(
        SQLEnum(RequestUrgency, name="request_urgency_enum"),
        default=RequestUrgency.NORMAL,
        nullable=False,
    )
    required_location = Column(String(255), nullable=False)
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)
    status = Column(
        SQLEnum(RequestStatus, name="request_status_enum"),
        default=RequestStatus.PENDING,
        nullable=False,
    )
    request_date = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    notes = Column(Text, nullable=True)

    # Relationships
    recipient = relationship("Recipient", back_populates="blood_requests")
    matches = relationship("DonorMatch", back_populates="blood_request", cascade="all, delete-orphan")


class DonorMatch(Base):
    __tablename__ = "donor_match"

    match_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("blood_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    donor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("donors.donor_id", ondelete="CASCADE"),
        nullable=False,
    )
    match_score = Column(Numeric(5, 2), nullable=False)
    distance_km = Column(Numeric(6, 2), nullable=False)
    is_notified = Column(Boolean, default=False, nullable=False)
    response_status = Column(
        SQLEnum(MatchResponseStatus, name="match_response_status_enum"),
        default=MatchResponseStatus.PENDING,
        nullable=False,
    )
    start_date = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    blood_request = relationship("BloodRequest", back_populates="matches")
    donor = relationship("Donor", back_populates="matches")
    communications = relationship("Communication", back_populates="match", cascade="all, delete-orphan")


class Communication(Base):
    __tablename__ = "communications"

    communication_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(
        UUID(as_uuid=True),
        ForeignKey("donor_match.match_id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    receiver_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    channel = Column(
        SQLEnum(CommunicationChannel, name="communication_channel_enum"),
        default=CommunicationChannel.IN_APP,
        nullable=False,
    )
    message = Column(Text, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())

    # Relationships
    match = relationship("DonorMatch", back_populates="communications")
    sender = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])
