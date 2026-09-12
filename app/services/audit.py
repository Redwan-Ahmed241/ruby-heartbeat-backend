"""Audit log service for persisting system events."""
import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.audit import SystemLog

logger = logging.getLogger(__name__)


def log_system_action(
    db: Session,
    action: str,
    entity: str,
    entity_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> SystemLog:
    """Create an audit trail record in system_logs table."""
    log_entry = SystemLog(
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        ip_address=ip_address,
    )
    db.add(log_entry)
    try:
        db.flush()
    except Exception as e:
        logger.error(f"Failed to record audit log: {e}")
    return log_entry
