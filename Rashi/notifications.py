"""
Email Notifications and Delivery History API router.
Replaces WhatsApp as primary notification workflow per Section 11.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import EmailNotification, NotificationDelivery, TimetableVersion
from app.services.email import EmailService, notify_version_subscribers

router = APIRouter(prefix="/notifications", tags=["Email Notifications"])


@router.get("/status")
def smtp_status():
    """Returns the configuration status of the SMTP service."""
    service = EmailService()
    return {
        "smtp_configured": service.is_configured,
        "smtp_host": service.host or "Not configured",
        "smtp_port": service.port,
        "from_email": service.from_email,
        "mode": "LIVE_SMTP" if service.is_configured else "MOCK_SIMULATOR"
    }


@router.post("/send/{version_id}")
def send_timetable_notifications(
    version_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """
    Sends section timetable PNGs to students and faculty for the published version.
    """
    version = db.get(TimetableVersion, version_id)
    if not version:
        raise HTTPException(404, "Timetable version not found")

    result = notify_version_subscribers(db, version_id, admin_id=admin.id)
    return result


@router.get("/history")
def notification_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """
    Returns historical email notifications and delivery logs.
    """
    notifications = db.scalars(
        select(EmailNotification)
        .order_by(EmailNotification.created_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": n.id,
            "version_id": n.version_id,
            "recipient_type": n.recipient_type,
            "recipient_id": n.recipient_id,
            "recipient_email": n.recipient_email,
            "subject": n.subject,
            "status": n.status.value,
            "attempts": n.attempts,
            "last_error": n.last_error,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        }
        for n in notifications
    ]
