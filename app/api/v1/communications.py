"""Communications router: /api/v1/communications."""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.models.request import Communication, DonorMatch
from app.schemas.request import CommunicationCreate, CommunicationResponse
from app.api.deps import get_current_active_user
from app.services.audit import log_system_action

router = APIRouter(prefix="/communications", tags=["Communications"])


@router.post("/{match_id}", response_model=CommunicationResponse, status_code=status.HTTP_201_CREATED)
def send_communication(
    match_id: UUID,
    comm_data: CommunicationCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Send in-app message relating to a donor match."""
    match = db.query(DonorMatch).filter(DonorMatch.match_id == match_id).first()
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match not found.",
        )

    new_comm = Communication(
        match_id=match_id,
        sender_id=current_user.user_id,
        receiver_id=comm_data.receiver_id,
        channel=comm_data.channel,
        message=comm_data.message,
    )
    db.add(new_comm)

    log_system_action(
        db=db,
        action="SEND_COMMUNICATION",
        entity="communications",
        entity_id=new_comm.communication_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(new_comm)
    return new_comm


@router.get("/{match_id}", response_model=List[CommunicationResponse])
def get_match_communications(
    match_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List messages for a specific match."""
    return (
        db.query(Communication)
        .filter(Communication.match_id == match_id)
        .order_by(Communication.sent_at.asc())
        .all()
    )
