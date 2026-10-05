from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Schedulix",
    description="University Timetable Management System",
    version="0.1.0"
)

# Allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "Welcome to Schedulix",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


@app.get("/api/timetable")
def get_timetable():
    """
    Temporary timetable data.

    Later this will come from PostgreSQL
    through SQLAlchemy.
    """

    timetable = [
        {
            "id": 1,
            "day": "Monday",
            "time": "10:00-11:00",
            "subject": "Operating Systems",
            "faculty": "Dr. Sharma",
            "room": "C-301",
            "section": "CSE-B"
        },
        {
            "id": 2,
            "day": "Monday",
            "time": "11:00-12:00",
            "subject": "DBMS",
            "faculty": "Dr. Verma",
            "room": "C-302",
            "section": "CSE-B"
        },
        {
            "id": 3,
            "day": "Tuesday",
            "time": "10:00-11:00",
            "subject": "Computer Networks",
            "faculty": "Dr. Singh",
            "room": "C-301",
            "section": "CSE-B"
        }
    ]

    return {
        "count": len(timetable),
        "timetable": timetable
    }