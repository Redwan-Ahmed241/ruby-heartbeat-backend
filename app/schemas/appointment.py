"""Pydantic schemas for appointments, events, campaign notices, and system audit logs."""
from datetime import datetime, date, time
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from app.core.enums import (
    AppointmentStatus,
    EventStatus,
    ParticipantRole,
    ParticipantStatus,
)


class AppointmentCreate(BaseModel):
    center_id: UUID
    appointment_date: date
    appointment_time: time


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus


class AppointmentResponse(BaseModel):
    appointment_id: UUID
    donor_id: UUID
    center_id: UUID
    appointment_date: date
    appointment_time: time
    status: AppointmentStatus
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


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
