"""Notifications management router: /api/v1/notifications."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, joinedload
from app.models.request import BloodRequest
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



@router.get("/my-notifications")
def get_my_notifications(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve active notifications and match alerts for the authenticated user,
    strictly omitting alerts for any blood requests created by the user themselves.
    """
    matches = (
        db.query(DonorMatch)
        .options(
            joinedload(DonorMatch.blood_request)
        )
        .filter(DonorMatch.donor_id == current_user.user_id)
        .order_by(DonorMatch.start_date.desc())
        .all()
    )

    items = []
    for m in matches:
        req = m.blood_request
        if not req or req.recipient_id == current_user.user_id:
            continue
        items.append({
            "match_id": str(m.match_id),
            "request_id": str(req.request_id),
            "blood_group": req.blood_group.value if hasattr(req.blood_group, "value") else str(req.blood_group),
            "hospital_name": req.hospital_name or req.required_location,
            "urgency": req.urgency.value if hasattr(req.urgency, "value") else str(req.urgency),
            "response_status": m.response_status.value if hasattr(m.response_status, "value") else str(m.response_status),
            "created_at": m.start_date.isoformat() if m.start_date else None,
            "message": f"Blood match alert: {req.blood_group} needed at {req.hospital_name or req.required_location}",
        })
    return items
