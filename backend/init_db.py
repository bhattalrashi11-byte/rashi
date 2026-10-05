from database import engine, SessionLocal, Base
from models import Faculty, Room, TimetableEntry


# --------------------------------------------------
# 1. Create all tables
# --------------------------------------------------

Base.metadata.create_all(bind=engine)

print("Database tables created successfully.")


# --------------------------------------------------
# 2. Create a database session
# --------------------------------------------------

db = SessionLocal()


try:
    # --------------------------------------------------
    # 3. Insert sample faculty
    # --------------------------------------------------

    faculty1 = Faculty(
        name="Dr. Sharma",
        department="Computer Science"
    )

    faculty2 = Faculty(
        name="Dr. Verma",
        department="Computer Science"
    )

    db.add_all([faculty1, faculty2])
    db.commit()

    print("Faculty data inserted.")


    # --------------------------------------------------
    # 4. Insert sample rooms
    # --------------------------------------------------

    room1 = Room(
        room_number="C-301",
        capacity=60
    )

    room2 = Room(
        room_number="C-302",
        capacity=50
    )

    db.add_all([room1, room2])
    db.commit()

    print("Room data inserted.")


    # --------------------------------------------------
    # 5. Insert sample timetable entries
    # --------------------------------------------------

    timetable1 = TimetableEntry(
        day="Monday",
        time="10:00-11:00",
        subject="Operating Systems",
        section="CSE-B",
        faculty_id=faculty1.id,
        room_id=room1.id
    )

    timetable2 = TimetableEntry(
        day="Monday",
        time="11:00-12:00",
        subject="DBMS",
        section="CSE-B",
        faculty_id=faculty2.id,
        room_id=room2.id
    )

    db.add_all([timetable1, timetable2])
    db.commit()

    print("Timetable data inserted.")


finally:
    db.close()

    print("Database connection closed.")