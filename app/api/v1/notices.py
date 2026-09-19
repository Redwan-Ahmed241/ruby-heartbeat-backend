"""Campaign notices router: /api/v1/campaign-notices."""
from typing import List
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.models.user import User
from app.models.event import CampaignNotice
from app.schemas.events_notices import CampaignNoticeCreate, CampaignNoticeResponse
from app.api.deps import RequireRoles
from app.services.audit import log_system_action

router = APIRouter(prefix="/campaign-notices", tags=["Campaign Notices"])


@router.get("/", response_model=List[CampaignNoticeResponse])
def get_campaign_notices(db: Session = Depends(get_db)):
    """Public campaign notices: list all active notices."""
    today = date.today()
    return (
        db.query(CampaignNotice)
        .filter(CampaignNotice.expiry_date >= today)
        .order_by(CampaignNotice.publish_date.desc())
        .all()
    )


@router.post("/", response_model=CampaignNoticeResponse, status_code=status.HTTP_201_CREATED)
def create_campaign_notice(
    notice_data: CampaignNoticeCreate,
    current_user: User = Depends(RequireRoles([UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Create a new public campaign notice (Admin only)."""
    notice = CampaignNotice(
        title=notice_data.title,
        description=notice_data.description,
        source=notice_data.source,
        publish_date=notice_data.publish_date,
        expiry_date=notice_data.expiry_date,
        link=notice_data.link,
        created_by=current_user.user_id,
    )
    db.add(notice)

    log_system_action(
        db=db,
        action="CREATE_CAMPAIGN_NOTICE",
        entity="campaign_notices",
        entity_id=notice.notice_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(notice)
    return notice
