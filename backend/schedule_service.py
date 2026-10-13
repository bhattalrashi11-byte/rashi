from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

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

    def _generate(self, algorithm: str):
        # Fetch pending requests.
        requests_db = (
            self.db.query(SchedulingRequest)
            .filter(SchedulingRequest.status == "pending")
            .order_by(SchedulingRequest.id)
            .all()
        )

        faculty_db = self.db.query(Faculty).all()
        rooms_db = self.db.query(Room).all()
        existing_db = self.db.query(TimetableEntry).all()

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

        faculty = [
            {"id": member.id}
            for member in faculty_db
        ]

        rooms = [
            {
                "id": room.id,
                "room_number": room.room_number,
                "capacity": room.capacity,
            }
            for room in rooms_db
        ]

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

        result = self.scheduler.generate(
            requests=requests,
            faculty=faculty,
            rooms=rooms,
            existing_entries=existing_entries,
            algorithm=algorithm,
        )

        result["request_ids"] = [
            request.id for request in requests_db
        ]

        return result

    def generate_timetable(self, algorithm: str = "PRIORITY"):
        """Generate a preview without saving it."""

        result = self._generate(algorithm)
        result["mode"] = "preview"

        result["message"] = (
            "Timetable preview generated successfully."
            if result["unscheduled_count"] == 0
            else "Preview generated with unscheduled sessions."
        )

        return result

    def save_generated_timetable(
        self,
        algorithm: str = "PRIORITY",
    ):
        """
        Generate and save a complete timetable in one transaction.

        Nothing is saved if any requested session cannot be allocated.
        """

        try:
            result = self._generate(algorithm)

            if not result["request_ids"]:
                result["mode"] = "saved"
                result["message"] = (
                    "There are no pending scheduling requests."
                )
                result["saved_count"] = 0
                return result

            # Do not save an incomplete timetable.
            if result["unscheduled_count"] > 0:
                result["mode"] = "not_saved"
                result["message"] = (
                    "Timetable was not saved because some sessions "
                    "could not be scheduled. Resolve the conflicts "
                    "or add more resources and try again."
                )
                result["saved_count"] = 0
                return result

            # Insert every generated entry.
            for item in result["scheduled"]:
                entry = TimetableEntry(
                    day=item["day"],
                    time=item["time"],
                    subject=item["subject"],
                    section=item["section"],
                    faculty_id=item["faculty_id"],
                    room_id=item["room_id"],
                )
                self.db.add(entry)

            # Mark requests as completed.
            (
                self.db.query(SchedulingRequest)
                .filter(
                    SchedulingRequest.id.in_(
                        result["request_ids"]
                    )
                )
                .update(
                    {"status": "scheduled"},
                    synchronize_session=False,
                )
            )

            # Commit all inserts and status changes together.
            self.db.commit()

            result["mode"] = "saved"
            result["saved_count"] = result["scheduled_count"]
            result["message"] = (
                "Timetable generated and saved successfully."
            )

            return result

        except SQLAlchemyError:
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise
