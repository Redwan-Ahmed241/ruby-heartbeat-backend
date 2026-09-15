"""Donation events and participants router: /api/v1/events."""
from typing import List
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import (
    UserRole,
    EventStatus,
    ParticipantRole,
    ParticipantStatus,
)
from app.models.user import User
from app.models.event import DonationEvent, EventParticipant
from app.schemas.appointment import (
    DonationEventCreate,
    EventResponse,
    EventParticipantCreate,
    EventParticipantResponse,
)
from app.api.deps import get_current_active_user, RequireRoles
from app.services.audit import log_system_action

router = APIRouter(prefix="/events", tags=["Donation Events"])


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_donation_event(
    event_data: DonationEventCreate,
    current_user: User = Depends(RequireRoles([UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Create a donation campaign/event."""
    new_event = DonationEvent(
        title=event_data.title,
        description=event_data.description,
        organizer_id=current_user.user_id,
        location=event_data.location,
        start_date=event_data.start_date,
        end_date=event_data.end_date,
        status=EventStatus.UPCOMING,
    )
    db.add(new_event)

    log_system_action(
        db=db,
        action="CREATE_EVENT",
        entity="donation_events",
        entity_id=new_event.event_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(new_event)
    return new_event


@router.get("/", response_model=List[EventResponse])
def list_events(db: Session = Depends(get_db)):
    """List all upcoming/active donation events."""
    return db.query(DonationEvent).order_by(DonationEvent.start_date.asc()).all()


@router.post("/{event_id}/register", response_model=EventParticipantResponse, status_code=status.HTTP_201_CREATED)
def register_for_event(
    event_id: UUID,
    participant_data: EventParticipantCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Register for a donation campaign/event."""
    event = db.query(DonationEvent).filter(DonationEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Donation event not found.",
        )

    # Check if already registered
    existing = (
        db.query(EventParticipant)
        .filter(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == current_user.user_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already registered for this event.",
        )

    participant = EventParticipant(
        event_id=event_id,
        user_id=current_user.user_id,
        role=participant_data.role,
        status=ParticipantStatus.REGISTERED,
    )
    db.add(participant)

    log_system_action(
        db=db,
        action="REGISTER_EVENT",
        entity="event_participants",
        entity_id=participant.participant_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(participant)
    return participant


@router.get("/my-registrations", response_model=List[EventResponse])
def get_my_registered_events(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get all events the current user is registered for (status != CANCELLED)."""
    participant_rows = (
        db.query(EventParticipant)
        .filter(
            EventParticipant.user_id == current_user.user_id,
            EventParticipant.status != ParticipantStatus.CANCELLED,
        )
        .all()
    )
    event_ids = [p.event_id for p in participant_rows]
    if not event_ids:
        return []
    return (
        db.query(DonationEvent)
        .filter(DonationEvent.event_id.in_(event_ids))
        .order_by(DonationEvent.start_date.asc())
        .all()
    )


@router.post("/{event_id}/checkin", response_model=EventParticipantResponse)
def checkin_participant(
    event_id: UUID,
    user_id: UUID,
    current_user: User = Depends(RequireRoles([UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Check in a participant at the event."""
    participant = (
        db.query(EventParticipant)
        .filter(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == user_id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant registration not found for this event.",
        )

    participant.status = ParticipantStatus.ATTENDED
    participant.checkin_time = datetime.utcnow()

    log_system_action(
        db=db,
        action="CHECKIN_PARTICIPANT",
        entity="event_participants",
        entity_id=participant.participant_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(participant)
    return participant
