from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import TimetableEntry
from schedule_service import ScheduleService


app = FastAPI(
    title="Schedulix",
    description="University Timetable Management System",
    version="0.1.0"
)


# --------------------------------------------------
# CORS
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Request Schema
# --------------------------------------------------

class TimetableRequest(BaseModel):
    day: str
    time: str
    subject: str
    section: str
    faculty_id: int
    room_id: int


# --------------------------------------------------
# Root
# --------------------------------------------------

@app.get("/")
def root():
    return {
        "message": "Welcome to Schedulix",
        "status": "running"
    }


# --------------------------------------------------
# Health Check
# --------------------------------------------------

@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


# --------------------------------------------------
# Get Timetable
# --------------------------------------------------

@app.get("/api/timetable")
def get_timetable(db: Session = Depends(get_db)):

    entries = db.query(TimetableEntry).all()

    timetable = []

    for entry in entries:

        timetable.append({
            "id": entry.id,
            "day": entry.day,
            "time": entry.time,
            "subject": entry.subject,
            "section": entry.section,
            "faculty_id": entry.faculty_id,
            "room_id": entry.room_id
        })

    return {
        "count": len(timetable),
        "timetable": timetable
    }


# --------------------------------------------------
# Create Timetable Entry
# --------------------------------------------------

@app.post("/api/timetable")
def create_timetable_entry(
    request: TimetableRequest,
    db: Session = Depends(get_db)
):

    service = ScheduleService(db)

    new_entry = {
        "day": request.day,
        "time": request.time,
        "subject": request.subject,
        "section": request.section,
        "faculty_id": request.faculty_id,
        "room_id": request.room_id
    }

    result = service.create_entry(new_entry)

    return result