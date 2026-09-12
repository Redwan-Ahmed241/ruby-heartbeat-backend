"""Pydantic schemas for blood requests, donor matching, and communications."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from app.core.enums import (
    BloodGroup,
    ComponentType,
    RequestUrgency,
    RequestStatus,
    MatchResponseStatus,
    CommunicationChannel,
)


class BloodRequestCreate(BaseModel):
    blood_group: BloodGroup
    component_type: ComponentType
    quantity: float = Field(..., gt=0)
    urgency: RequestUrgency = RequestUrgency.NORMAL
    required_location: str = Field(..., max_length=255)
    latitude: float
    longitude: float
    notes: Optional[str] = None


class MaskedDonorMatchResponse(BaseModel):
    match_id: UUID
    request_id: UUID
    donor_id: UUID
    blood_group: BloodGroup
    distance_km: float
    match_score: float
    response_status: MatchResponseStatus
    is_notified: bool
    start_date: Optional[datetime]

    # Contact Reveal Safeguard: Phone, address, email are masked in this view
    donor_name_initial: str
    contact_revealed: bool = False

    model_config = ConfigDict(from_attributes=True)


class BloodRequestResponse(BaseModel):
    request_id: UUID
    recipient_id: UUID
    blood_group: BloodGroup
    component_type: ComponentType
    quantity: float
    urgency: RequestUrgency
    required_location: str
    latitude: float
    longitude: float
    status: RequestStatus
    request_date: Optional[datetime]
    notes: Optional[str]
    matches: Optional[List[MaskedDonorMatchResponse]] = None

    model_config = ConfigDict(from_attributes=True)


class MatchRespondRequest(BaseModel):
    response: MatchResponseStatus  # Must be ACCEPTED or DECLINED


class DonorContactReveal(BaseModel):
    match_id: UUID
    donor_id: UUID
    full_name: str
    phone: str
    email: str
    address: str
    latitude: float
    longitude: float
    response_status: MatchResponseStatus


class CommunicationCreate(BaseModel):
    receiver_id: UUID
    message: str = Field(..., min_length=1)
    channel: CommunicationChannel = CommunicationChannel.IN_APP


class CommunicationResponse(BaseModel):
    communication_id: UUID
    match_id: UUID
    sender_id: UUID
    receiver_id: UUID
    channel: CommunicationChannel
    message: str
    sent_at: Optional[datetime]
    is_read: bool

    model_config = ConfigDict(from_attributes=True)
