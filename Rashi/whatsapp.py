import json

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.services.whatsapp import (
    WhatsAppService,
    update_delivery_status,
)

router = APIRouter(
    prefix="/whatsapp",
    tags=["WhatsApp"]
)


@router.get("/webhook")
def verify_webhook(
    mode: str = None,
    token: str = None,
    challenge: str = None
):
    if (
        mode == "subscribe"
        and token == settings.WHATSAPP_VERIFY_TOKEN
        and challenge
    ):
        return PlainTextResponse(challenge)

    raise HTTPException(403, "Webhook verification failed")


@router.post("/webhook")
async def webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    body = await request.body()

    signature = request.headers.get(
        "X-Hub-Signature-256", ""
    )

    service = WhatsAppService()

    if not service.verify_signature(body, signature):
        raise HTTPException(403, "Invalid webhook signature")

    payload = json.loads(body)

    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                for status_item in value.get("statuses", []):
                    message_id = status_item.get("id")
                    status = status_item.get("status")

                    timestamp = datetime.fromtimestamp(
                        int(status_item.get("timestamp", 0)),
                        tz=timezone.utc
                    ).replace(tzinfo=None)

                    update_delivery_status(
                        db,
                        message_id,
                        status,
                        timestamp,
                        status_item
                    )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return {"status": "RECEIVED"}