"""Pydantic schemas for events, campaign notices, and system audit logs."""
from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from app.core.enums import (
    EventStatus,
    ParticipantRole,
    ParticipantStatus,
)


class DonationEventCreate(BaseModel):
    title: str = Field(..., max_length=100)
    description: str
    location: str = Field(..., max_length=255)
    start_date: date
    end_date: date


class EventResponse(BaseModel):
    event_id: UUID
    title: str
    description: str
    organizer_id: UUID
    location: str
    start_date: date
    end_date: date
    status: EventStatus
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class EventParticipantCreate(BaseModel):
    role: ParticipantRole = ParticipantRole.PARTICIPANT


class EventParticipantResponse(BaseModel):
    participant_id: UUID
    event_id: UUID
    user_id: UUID
    role: ParticipantRole
    status: ParticipantStatus
    registered_at: Optional[datetime]
    checkin_time: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class CampaignNoticeCreate(BaseModel):
    title: str = Field(..., max_length=100)
    description: str
    source: str = Field(..., max_length=100)
    publish_date: date
    expiry_date: date
    link: Optional[str] = Field(None, max_length=255)


class CampaignNoticeResponse(BaseModel):
    notice_id: UUID
    title: str
    description: str
    source: str
    publish_date: date
    expiry_date: date
    link: Optional[str]
    created_by: UUID
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SystemLogResponse(BaseModel):
    log_id: UUID
    user_id: Optional[UUID]
    action: str
    entity: str
    entity_id: Optional[UUID]
    ip_address: Optional[str]
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

