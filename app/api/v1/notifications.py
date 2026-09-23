"""Notifications management router: /api/v1/notifications."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.enums import MatchResponseStatus
from app.models.user import User
from app.models.request import DonorMatch
from app.api.deps import get_current_active_user
from app.services.audit import log_system_action

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class ClearAllResponse(BaseModel):
    cleared_count: int
    message: str


@router.post("/clear-all", response_model=ClearAllResponse)
@router.delete("/clear-all", response_model=ClearAllResponse)
def clear_all_notifications(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Dismiss all pending notification match alerts for the authenticated donor.
    Transitions pending matches to DECLINED to clear notification backlog.
    """
    pending_matches = (
        db.query(DonorMatch)
        .filter(
            DonorMatch.donor_id == current_user.user_id,
            DonorMatch.response_status == MatchResponseStatus.PENDING,
        )
        .all()
    )

    cleared_count = len(pending_matches)
    for m in pending_matches:
        m.response_status = MatchResponseStatus.DECLINED

    log_system_action(
        db=db,
        action="CLEAR_ALL_NOTIFICATIONS",
        entity="donor_match",
        entity_id=current_user.user_id,
        user_id=current_user.user_id,
    )

    db.commit()

    return ClearAllResponse(
        cleared_count=cleared_count,
        message=f"Successfully dismissed {cleared_count} pending notifications.",
    )
