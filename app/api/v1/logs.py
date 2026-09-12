"""System audit logs router: /api/v1/system-logs."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.models.user import User
from app.models.audit import SystemLog
from app.schemas.appointment import SystemLogResponse
from app.api.deps import RequireRoles

router = APIRouter(prefix="/system-logs", tags=["System Logs"])


@router.get("/", response_model=List[SystemLogResponse])
def get_system_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    current_user: User = Depends(RequireRoles([UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Read audit trail logs (System Admin only)."""
    query = db.query(SystemLog)
    if action:
        query = query.filter(SystemLog.action.ilike(f"%{action}%"))

    return query.order_by(SystemLog.timestamp.desc()).offset(offset).limit(limit).all()
