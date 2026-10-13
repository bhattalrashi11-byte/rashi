from dataclasses import dataclass
from typing import Any


DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
]

# Each item is a one-hour teaching slot.
TIME_SLOTS = [
    "09:00-10:00",
    "10:00-11:00",
    "11:00-12:00",
    "12:00-13:00",
    "14:00-15:00",
    "15:00-16:00",
]


@dataclass
class SchedulingJob:
    request_id: int
    subject: str
    section: str
    faculty_id: int
    sessions_per_week: int
    slots_required: int
    priority: int
    required_capacity: int


class TimetableScheduler:
    def __init__(
        self,
        days=None,
        time_slots=None,
    ):
        self.days = days or DAYS.copy()
        self.time_slots = time_slots or TIME_SLOTS.copy()

    def _sort_jobs(self, jobs, algorithm):
        algorithm = algorithm.upper()

        if algorithm == "PRIORITY":
            # Smaller number means higher priority.
            return sorted(
                jobs,
                key=lambda job: (
                    job.priority,
                    -job.slots_required,
                    job.request_id,
                ),
            )

        if algorithm == "SJF":
            # Shorter classes are considered first.
            return sorted(
                jobs,
                key=lambda job: (
                    job.slots_required,
                    job.priority,
                    job.request_id,
                ),
            )

        raise ValueError(
            "Invalid algorithm. Choose 'PRIORITY' or 'SJF'."
        )

    def generate(
        self,
        requests: list[dict[str, Any]],
        faculty: list[dict[str, Any]],
        rooms: list[dict[str, Any]],
        existing_entries: list[dict[str, Any]] | None = None,
        algorithm: str = "PRIORITY",
    ) -> dict[str, Any]:
        """
        Generate a timetable from scheduling requests.

        Expected request keys:
            id, subject, section, faculty_id,
            sessions_per_week, slots_required,
            priority, required_capacity

        Expected faculty keys:
            id

        Expected room keys:
            id, room_number, capacity

        Existing timetable entries must contain:
            day, time, section, faculty_id, room_id
        """

        existing_entries = existing_entries or []

        faculty_ids = {
            item["id"] for item in faculty
        }

        # Track occupied slots before assigning new sessions.
        occupied_faculty = set()
        occupied_rooms = set()
        occupied_sections = set()

        for entry in existing_entries:
            key = (entry["day"], entry["time"])

            occupied_faculty.add(
                (entry["faculty_id"], *key)
            )
            occupied_rooms.add(
                (entry["room_id"], *key)
            )
            occupied_sections.add(
                (entry["section"], *key)
            )

        # Convert input dictionaries into scheduling jobs.
        jobs = []

        for request in requests:
            faculty_id = request["faculty_id"]

            if faculty_id not in faculty_ids:
                raise ValueError(
                    f"Faculty ID {faculty_id} does not exist."
                )

            if request["sessions_per_week"] < 1:
                raise ValueError(
                    "sessions_per_week must be at least 1."
                )

            if request["slots_required"] != 1:
                raise ValueError(
                    "This version supports one-hour sessions only. "
                    "Multi-slot sessions will be added later."
                )

            if request["priority"] < 1:
                raise ValueError(
                    "Priority must be at least 1."
                )

            jobs.append(
                SchedulingJob(
                    request_id=request["id"],
                    subject=request["subject"],
                    section=request["section"],
                    faculty_id=faculty_id,
                    sessions_per_week=request["sessions_per_week"],
                    slots_required=request["slots_required"],
                    priority=request["priority"],
                    required_capacity=request["required_capacity"],
                )
            )

        sorted_jobs = self._sort_jobs(jobs, algorithm)

        scheduled = []
        unscheduled = []

        for job in sorted_jobs:
            suitable_rooms = sorted(
                [
                    room for room in rooms
                    if room["capacity"] >= job.required_capacity
                ],
                key=lambda room: room["capacity"],
            )

            if not suitable_rooms:
                for session_number in range(
                    1, job.sessions_per_week + 1
                ):
                    unscheduled.append({
                        "request_id": job.request_id,
                        "subject": job.subject,
                        "section": job.section,
                        "session_number": session_number,
                        "reason": "No room has sufficient capacity.",
                    })
                continue

            for session_number in range(
                1, job.sessions_per_week + 1
            ):
                assignment = None

                for day in self.days:
                    if assignment:
                        break

                    for time_slot in self.time_slots:
                        slot_key = (day, time_slot)

                        if (
                            (job.faculty_id, *slot_key)
                            in occupied_faculty
                        ):
                            continue

                        if (
                            (job.section, *slot_key)
                            in occupied_sections
                        ):
                            continue

                        available_room = next(
                            (
                                room for room in suitable_rooms
                                if (
                                    room["id"], *slot_key
                                ) not in occupied_rooms
                            ),
                            None,
                        )

                        if available_room is None:
                            continue

                        assignment = {
                            "request_id": job.request_id,
                            "subject": job.subject,
                            "section": job.section,
                            "faculty_id": job.faculty_id,
                            "room_id": available_room["id"],
                            "room_number": available_room["room_number"],
                            "day": day,
                            "time": time_slot,
                            "priority": job.priority,
                            "session_number": session_number,
                        }

                        occupied_faculty.add(
                            (job.faculty_id, *slot_key)
                        )
                        occupied_rooms.add(
                            (available_room["id"], *slot_key)
                        )
                        occupied_sections.add(
                            (job.section, *slot_key)
                        )

                        scheduled.append(assignment)
                        break

                if assignment is None:
                    unscheduled.append({
                        "request_id": job.request_id,
                        "subject": job.subject,
                        "section": job.section,
                        "session_number": session_number,
                        "reason": (
                            "No available day/time slot satisfies "
                            "the faculty, room and section constraints."
                        ),
                    })

        return {
            "algorithm": algorithm.upper(),
            "total_requested_sessions": sum(
                job.sessions_per_week for job in jobs
            ),
            "scheduled_count": len(scheduled),
            "unscheduled_count": len(unscheduled),
            "scheduled": scheduled,
            "unscheduled": unscheduled,
        }


if __name__ == "__main__":
    # Simple standalone test. No database connection is needed.
    scheduler = TimetableScheduler()

    sample_requests = [
        {
            "id": 1,
            "subject": "Computer Networks",
            "section": "CSE-B",
            "faculty_id": 1,
            "sessions_per_week": 3,
            "slots_required": 1,
            "priority": 1,
            "required_capacity": 50,
        },
        {
            "id": 2,
            "subject": "Database Management Systems",
            "section": "CSE-B",
            "faculty_id": 2,
            "sessions_per_week": 2,
            "slots_required": 1,
            "priority": 2,
            "required_capacity": 45,
        },
    ]

    sample_faculty = [
        {"id": 1},
        {"id": 2},
    ]

    sample_rooms = [
        {"id": 1, "room_number": "C-301", "capacity": 60},
        {"id": 2, "room_number": "C-302", "capacity": 50},
    ]

    result = scheduler.generate(
        requests=sample_requests,
        faculty=sample_faculty,
        rooms=sample_rooms,
        algorithm="PRIORITY",
    )

    print("\nTIMETABLE GENERATION RESULT")
    print("=" * 40)
    print(f"Algorithm: {result['algorithm']}")
    print(f"Requested: {result['total_requested_sessions']}")
    print(f"Scheduled: {result['scheduled_count']}")
    print(f"Unscheduled: {result['unscheduled_count']}")

    print("\nSCHEDULED CLASSES")
    for entry in result["scheduled"]:
        print(
            f"{entry['day']:10} | {entry['time']} | "
            f"{entry['subject']} | {entry['section']} | "
            f"Faculty {entry['faculty_id']} | "
            f"Room {entry['room_number']}"
        )

    if result["unscheduled"]:
        print("\nUNSCHEDULED CLASSES")
        for entry in result["unscheduled"]:
            print(entry)
