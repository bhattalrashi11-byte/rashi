from sqlalchemy.orm import Session

from models import TimetableEntry
from conflict_engine import ConflictEngine


class ScheduleService:

    def __init__(self, db: Session):
        self.db = db
        self.conflict_engine = ConflictEngine()

    def get_existing_entries(self):

        entries = self.db.query(TimetableEntry).all()

        result = []

        for entry in entries:

            result.append({
                "id": entry.id,
                "subject": entry.subject,
                "faculty": entry.faculty_id,
                "room": entry.room_id,
                "section": entry.section,
                "day": entry.day,
                "time": entry.time
            })

        return result


    def check_assignment(self, new_entry):

        existing_entries = self.get_existing_entries()

        conflicts = self.conflict_engine.check_conflicts(
            new_entry,
            existing_entries
        )

        return conflicts


    def create_entry(self, new_entry):

        conflicts = self.check_assignment(new_entry)

        if conflicts:

            return {
                "success": False,
                "message": "Timetable conflict detected",
                "conflicts": conflicts
            }

        entry = TimetableEntry(
            day=new_entry["day"],
            time=new_entry["time"],
            subject=new_entry["subject"],
            section=new_entry["section"],
            faculty_id=new_entry["faculty_id"],
            room_id=new_entry["room_id"]
        )

        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)

        return {
            "success": True,
            "message": "Timetable entry created",
            "entry_id": entry.id
        }