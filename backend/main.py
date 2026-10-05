from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import get_db
from models import TimetableEntry


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