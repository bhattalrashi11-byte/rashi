from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import (
    AvailabilityBlock,
    AvailabilityType,
    Faculty,
    Room,
    Building,
    Floor,
    FacultyAvailability,
)
from app.schemas import AvailabilityCreate
from app.audit import record_audit

router = APIRouter(
    prefix="/availability",
    tags=["Availability"],
    dependencies=[Depends(get_current_admin)]
)


@router.post("/block")
def create_block(
    data: AvailabilityCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    try:
        kind = AvailabilityType(data.resource_type.upper())
    except ValueError:
        raise HTTPException(400, "Invalid resource type")

    if data.end_at <= data.start_at:
        raise HTTPException(400, "Invalid availability interval")

    resource_models = {
        AvailabilityType.FACULTY: Faculty,
        AvailabilityType.ROOM: Room,
        AvailabilityType.BUILDING: Building,
        AvailabilityType.FLOOR: Floor
    }

    if not db.get(resource_models[kind], data.resource_id):
        raise HTTPException(404, "Resource not found")

    block = AvailabilityBlock(
        resource_type=kind,
        resource_id=data.resource_id,
        start_at=data.start_at,
        end_at=data.end_at,
        reason=data.reason
    )

    db.add(block)
    db.flush()

    record_audit(
        db,
        "AVAILABILITY_CHANGED",
        kind.value,
        data.resource_id,
        admin.id,
        {"reason": data.reason}
    )

    db.commit()

    return {
        "id": block.id,
        "status": "BLOCKED",
        "message": "Create a rescheduling proposal before republishing"
    }


@router.get("/blocks")
def list_blocks(db: Session = Depends(get_db)):
    return db.query(AvailabilityBlock).all()


@router.delete("/blocks/{block_id}")
def remove_block(
    block_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    block = db.get(AvailabilityBlock, block_id)

    if not block:
        raise HTTPException(404, "Availability block not found")

    db.delete(block)

    record_audit(
        db,
        "AVAILABILITY_BLOCK_REMOVED",
        "AvailabilityBlock",
        block_id,
        admin.id
    )

    db.commit()

    return {"status": "REMOVED"}


@router.post("/faculty")
def set_faculty_availability(
    faculty_id: str,
    weekday: int,
    start_time: str,
    end_time: str,
    available: bool,
    db: Session = Depends(get_db)
):
    if not db.get(Faculty, faculty_id):
        raise HTTPException(404, "Faculty not found")

    if not 0 <= weekday <= 6:
        raise HTTPException(400, "Invalid weekday")

    from datetime import time

    try:
        start = time.fromisoformat(start_time)
        end = time.fromisoformat(end_time)
    except ValueError:
        raise HTTPException(400, "Invalid time")

    if end <= start:
        raise HTTPException(400, "End must be after start")

    record = FacultyAvailability(
        faculty_id=faculty_id,
        weekday=weekday,
        start_time=start,
        end_time=end,
        available=available
    )

    db.add(record)
    db.commit()

    return {"status": "SAVED"}