from database import engine, SessionLocal, Base
from models import Faculty, Room, TimetableEntry, SchedulingRequest


def init_db():
    # 1. Create any missing tables
    Base.metadata.create_all(bind=engine)
    print("Database tables checked/created successfully.")

    db = SessionLocal()

    try:
        # 2. Create sample faculty only if missing
        faculty1 = (
            db.query(Faculty)
            .filter_by(name="Dr. Sharma", department="Computer Science")
            .first()
        )

        if faculty1 is None:
            faculty1 = Faculty(
                name="Dr. Sharma",
                department="Computer Science"
            )
            db.add(faculty1)
            db.flush()

        faculty2 = (
            db.query(Faculty)
            .filter_by(name="Dr. Verma", department="Computer Science")
            .first()
        )

        if faculty2 is None:
            faculty2 = Faculty(
                name="Dr. Verma",
                department="Computer Science"
            )
            db.add(faculty2)
            db.flush()

        db.flush()
        print("Faculty records checked.")

        # 3. Create sample rooms only if missing
        room1 = (
            db.query(Room)
            .filter_by(room_number="C-301")
            .first()
        )

        if room1 is None:
            room1 = Room(
                room_number="C-301",
                capacity=60
            )
            db.add(room1)
            db.flush()

        room2 = (
            db.query(Room)
            .filter_by(room_number="C-302")
            .first()
        )

        if room2 is None:
            room2 = Room(
                room_number="C-302",
                capacity=50
            )
            db.add(room2)
            db.flush()

        db.flush()
        print("Room records checked.")

        # 4. Add initial timetable entries only if missing
        timetable1 = (
            db.query(TimetableEntry)
            .filter_by(
                day="Monday",
                time="10:00-11:00",
                subject="Operating Systems",
                section="CSE-B"
            )
            .first()
        )

        if timetable1 is None:
            timetable1 = TimetableEntry(
                day="Monday",
                time="10:00-11:00",
                subject="Operating Systems",
                section="CSE-B",
                faculty_id=faculty1.id,
                room_id=room1.id
            )
            db.add(timetable1)

        timetable2 = (
            db.query(TimetableEntry)
            .filter_by(
                day="Monday",
                time="11:00-12:00",
                subject="DBMS",
                section="CSE-B"
            )
            .first()
        )

        if timetable2 is None:
            timetable2 = TimetableEntry(
                day="Monday",
                time="11:00-12:00",
                subject="DBMS",
                section="CSE-B",
                faculty_id=faculty2.id,
                room_id=room2.id
            )
            db.add(timetable2)

        db.flush()
        print("Sample timetable entries checked.")

        # 5. Add example scheduling requests only if missing
        request1 = (
            db.query(SchedulingRequest)
            .filter_by(
                subject="Computer Networks",
                section="CSE-B",
                faculty_id=faculty1.id
            )
            .first()
        )

        if request1 is None:
            request1 = SchedulingRequest(
                subject="Computer Networks",
                section="CSE-B",
                faculty_id=faculty1.id,
                sessions_per_week=3,
                slots_required=1,
                priority=1,
                required_capacity=50,
                status="pending"
            )
            db.add(request1)

        request2 = (
            db.query(SchedulingRequest)
            .filter_by(
                subject="Database Management Systems",
                section="CSE-B",
                faculty_id=faculty2.id
            )
            .first()
        )

        if request2 is None:
            request2 = SchedulingRequest(
                subject="Database Management Systems",
                section="CSE-B",
                faculty_id=faculty2.id,
                sessions_per_week=2,
                slots_required=1,
                priority=2,
                required_capacity=45,
                status="pending"
            )
            db.add(request2)

        db.commit()

        print("Scheduling requests checked/created.")
        print("Database initialization completed successfully.")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
        print("Database connection closed.")


if __name__ == "__main__":
    init_db()
