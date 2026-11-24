"""
Audit Log API Router for Schedulix DBMS demonstration.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import AuditLog, Admin

router = APIRouter(
    prefix="/audit",
    tags=["Audit Logs"],
    dependencies=[Depends(get_current_admin)]
)


@router.get("/logs")
def get_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Returns the persistent DBMS audit trail recording logins, creation/modification
    of academic records, timetable generation, rescheduling, and SQL trigger logs.
    """
    query = select(AuditLog).order_by(AuditLog.created_at.desc())

    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)

    logs = db.scalars(query.limit(limit)).all()

    admins = {a.id: a.username for a in db.query(Admin).all()}

    return [
        {
            "id": log.id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "admin_id": log.admin_id,
            "actor": admins.get(log.admin_id, "System / Trigger" if not log.admin_id else "Administrator"),
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None
        }
        for log in logs
    ]
