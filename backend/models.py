from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class Faculty(Base):
    __tablename__ = "faculty"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    department = Column(String(100), nullable=False)

    timetable_entries = relationship(
        "TimetableEntry",
        back_populates="faculty"
    )


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True)
    room_number = Column(String(20), nullable=False)
    capacity = Column(Integer, nullable=False)

    timetable_entries = relationship(
        "TimetableEntry",
        back_populates="room"
    )


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"

    id = Column(Integer, primary_key=True)

    day = Column(String(20), nullable=False)
    time = Column(String(20), nullable=False)

    subject = Column(String(100), nullable=False)
    section = Column(String(50), nullable=False)

    faculty_id = Column(
        Integer,
        ForeignKey("faculty.id"),
        nullable=False
    )

    room_id = Column(
        Integer,
        ForeignKey("rooms.id"),
        nullable=False
    )

    faculty = relationship(
        "Faculty",
        back_populates="timetable_entries"
    )

    room = relationship(
        "Room",
        back_populates="timetable_entries"
    )

    # Prevent the same faculty or room
    # from being assigned twice to the same slot.
    __table_args__ = (
        UniqueConstraint(
            "faculty_id",
            "day",
            "time",
            name="unique_faculty_slot"
        ),
        UniqueConstraint(
            "room_id",
            "day",
            "time",
            name="unique_room_slot"
        ),
    )