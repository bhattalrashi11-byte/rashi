from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
)
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

    scheduling_requests = relationship(
        "SchedulingRequest",
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


class SchedulingRequest(Base):
    """
    Stores classes that need to be scheduled.

    Each request can require multiple sessions per week.
    The scheduler will convert these requirements into
    actual timetable entries.
    """

    __tablename__ = "scheduling_requests"

    id = Column(Integer, primary_key=True)

    subject = Column(String(100), nullable=False)
    section = Column(String(50), nullable=False)

    faculty_id = Column(
        Integer,
        ForeignKey("faculty.id"),
        nullable=False
    )

    sessions_per_week = Column(
        Integer,
        nullable=False,
        default=1
    )

    slots_required = Column(
        Integer,
        nullable=False,
        default=1
    )

    priority = Column(
        Integer,
        nullable=False,
        default=3
    )

    required_capacity = Column(
        Integer,
        nullable=False,
        default=1
    )

    status = Column(
        String(20),
        nullable=False,
        default="pending"
    )

    faculty = relationship(
        "Faculty",
        back_populates="scheduling_requests"
    )

    __table_args__ = (
        CheckConstraint(
            "sessions_per_week >= 1",
            name="check_sessions_per_week"
        ),
        CheckConstraint(
            "slots_required >= 1",
            name="check_slots_required"
        ),
        CheckConstraint(
            "priority >= 1",
            name="check_priority"
        ),
        CheckConstraint(
            "required_capacity >= 1",
            name="check_required_capacity"
        ),
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
