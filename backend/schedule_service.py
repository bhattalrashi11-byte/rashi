from sqlalchemy.orm import Session

from models import (
    Faculty,
    Room,
    TimetableEntry,
    SchedulingRequest,
)
from scheduler import TimetableScheduler


class ScheduleService:
    def __init__(self, db: Session):
        self.db = db
        self.scheduler = TimetableScheduler()

    def generate_timetable(self, algorithm: str = "PRIORITY"):
        """
        Generate a timetable preview from database records.

        This method does not save generated entries to the database.
        It only returns the proposed timetable for validation.
        """

        # 1. Fetch scheduling requirements
        requests_db = (
            self.db.query(SchedulingRequest)
            .filter(SchedulingRequest.status == "pending")
            .all()
        )

        # 2. Fetch available faculty and rooms
        faculty_db = self.db.query(Faculty).all()
        rooms_db = self.db.query(Room).all()

        # 3. Fetch already occupied timetable slots
        existing_db = self.db.query(TimetableEntry).all()

        # 4. Convert scheduling requests into dictionaries
        requests = [
            {
                "id": request.id,
                "subject": request.subject,
                "section": request.section,
                "faculty_id": request.faculty_id,
                "sessions_per_week": request.sessions_per_week,
                "slots_required": request.slots_required,
                "priority": request.priority,
                "required_capacity": request.required_capacity,
            }
            for request in requests_db
        ]

        # 5. Convert faculty into dictionaries
        faculty = [
            {"id": member.id}
            for member in faculty_db
        ]

        # 6. Convert rooms into dictionaries
        rooms = [
            {
                "id": room.id,
                "room_number": room.room_number,
                "capacity": room.capacity,
            }
            for room in rooms_db
        ]

        # 7. Convert existing timetable entries
        existing_entries = [
            {
                "day": entry.day,
                "time": entry.time,
                "section": entry.section,
                "faculty_id": entry.faculty_id,
                "room_id": entry.room_id,
            }
            for entry in existing_db
        ]

        # 8. Generate a timetable using the selected algorithm
        result = self.scheduler.generate(
            requests=requests,
            faculty=faculty,
            rooms=rooms,
            existing_entries=existing_entries,
            algorithm=algorithm,
        )

        # 9. Return a preview without modifying the database
        result["mode"] = "preview"
        result["message"] = (
            "Timetable generated successfully."
            if result["unscheduled_count"] == 0
            else "Timetable generated with some unscheduled sessions."
        )

        return result
