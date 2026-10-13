from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database import get_db
from models import (
    Faculty,
    Room,
    TimetableEntry,
    SchedulingRequest,
)
from schedule_service import ScheduleService


app = FastAPI(
    title="Schedulix API",
    description="Intelligent Academic Timetable Scheduling System",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TimetableRequest(BaseModel):
    day: str
    time: str
    subject: str
    section: str
    faculty_id: int
    room_id: int


class SchedulingRequestCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=100)
    section: str = Field(min_length=1, max_length=50)
    faculty_id: int = Field(gt=0)
    sessions_per_week: int = Field(ge=1, le=30)
    slots_required: int = Field(default=1, ge=1, le=1)
    priority: int = Field(default=3, ge=1, le=10)
    required_capacity: int = Field(default=1, ge=1)


def validate_algorithm(algorithm: str) -> str:
    algorithm = algorithm.upper()

    if algorithm not in ("PRIORITY", "SJF"):
        raise HTTPException(
            status_code=400,
            detail="Algorithm must be PRIORITY or SJF.",
        )

    return algorithm


@app.get("/")
def home():
    return {
        "message": "Welcome to Schedulix API",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/timetable")
def get_timetable(db: Session = Depends(get_db)):
    entries = (
        db.query(TimetableEntry)
        .order_by(
            TimetableEntry.day,
            TimetableEntry.time,
        )
        .all()
    )

    return [
        {
            "id": entry.id,
            "day": entry.day,
            "time": entry.time,
            "subject": entry.subject,
            "section": entry.section,
            "faculty_id": entry.faculty_id,
            "faculty_name": entry.faculty.name,
            "room_id": entry.room_id,
            "room_number": entry.room.room_number,
        }
        for entry in entries
    ]


@app.post("/api/timetable")
def create_timetable_entry(
    request: TimetableRequest,
    db: Session = Depends(get_db),
):
    faculty = db.get(Faculty, request.faculty_id)
    room = db.get(Room, request.room_id)

    if faculty is None:
        raise HTTPException(
            status_code=404,
            detail="Faculty not found.",
        )

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="Room not found.",
        )

    entry = TimetableEntry(
        day=request.day,
        time=request.time,
        subject=request.subject,
        section=request.section,
        faculty_id=request.faculty_id,
        room_id=request.room_id,
    )

    try:
        db.add(entry)
        db.commit()
        db.refresh(entry)

        return {
            "message": "Timetable entry created successfully.",
            "id": entry.id,
        }

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Could not create timetable entry. "
                "A faculty or room slot may already be occupied."
            ),
        )


@app.post("/api/scheduling-requests")
def create_scheduling_request(
    request: SchedulingRequestCreate,
    db: Session = Depends(get_db),
):
    faculty = db.get(Faculty, request.faculty_id)

    if faculty is None:
        raise HTTPException(
            status_code=404,
            detail="Faculty not found.",
        )

    scheduling_request = SchedulingRequest(
        subject=request.subject,
        section=request.section,
        faculty_id=request.faculty_id,
        sessions_per_week=request.sessions_per_week,
        slots_required=request.slots_required,
        priority=request.priority,
        required_capacity=request.required_capacity,
        status="pending",
    )

    try:
        db.add(scheduling_request)
        db.commit()
        db.refresh(scheduling_request)

        return {
            "message": "Scheduling request created successfully.",
            "request_id": scheduling_request.id,
            "status": scheduling_request.status,
        }

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to save scheduling request.",
        )


@app.get("/api/scheduling-requests")
def get_scheduling_requests(
    db: Session = Depends(get_db),
):
    requests = (
        db.query(SchedulingRequest)
        .order_by(SchedulingRequest.id)
        .all()
    )

    return [
        {
            "id": request.id,
            "subject": request.subject,
            "section": request.section,
            "faculty_id": request.faculty_id,
            "faculty_name": request.faculty.name,
            "sessions_per_week": request.sessions_per_week,
            "slots_required": request.slots_required,
            "priority": request.priority,
            "required_capacity": request.required_capacity,
            "status": request.status,
        }
        for request in requests
    ]


@app.post("/api/timetable/generate")
def generate_timetable(
    algorithm: str = Query(default="PRIORITY"),
    db: Session = Depends(get_db),
):
    algorithm = validate_algorithm(algorithm)

    try:
        service = ScheduleService(db)
        return service.generate_timetable(algorithm=algorithm)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Database error while generating timetable.",
        )


@app.post("/api/timetable/save")
def save_timetable(
    algorithm: str = Query(default="PRIORITY"),
    db: Session = Depends(get_db),
):
    algorithm = validate_algorithm(algorithm)

    try:
        service = ScheduleService(db)
        result = service.save_generated_timetable(
            algorithm=algorithm
        )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except SQLAlchemyError:
        raise HTTPException(
            status_code=409,
            detail=(
                "Timetable could not be saved. "
                "The database transaction was rolled back."
            ),
        )


@app.get("/api/faculty")
def get_faculty(db: Session = Depends(get_db)):
    faculty = db.query(Faculty).order_by(Faculty.id).all()

    return [
        {
            "id": member.id,
            "name": member.name,
            "department": member.department,
        }
        for member in faculty
    ]


@app.get("/api/rooms")
def get_rooms(db: Session = Depends(get_db)):
    rooms = db.query(Room).order_by(Room.id).all()

    return [
        {
            "id": room.id,
            "room_number": room.room_number,
            "capacity": room.capacity,
        }
        for room in rooms
    ]
