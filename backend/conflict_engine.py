from concurrent.futures import ThreadPoolExecutor
from threading import Lock


class ConflictEngine:

    def __init__(self):
        self.lock = Lock()

    # --------------------------------------------------
    # Faculty conflict
    # --------------------------------------------------

    def check_faculty(self, new_entry, existing_entries):

        for entry in existing_entries:

            if (
                entry["faculty"] == new_entry["faculty_id"]
                and entry["day"] == new_entry["day"]
                and entry["time"] == new_entry["time"]
            ):
                return "Faculty conflict"

        return None

    # --------------------------------------------------
    # Room conflict
    # --------------------------------------------------

    def check_room(self, new_entry, existing_entries):

        for entry in existing_entries:

            if (
                entry["room"] == new_entry["room_id"]
                and entry["day"] == new_entry["day"]
                and entry["time"] == new_entry["time"]
            ):
                return "Room conflict"

        return None

    # --------------------------------------------------
    # Section conflict
    # --------------------------------------------------

    def check_section(self, new_entry, existing_entries):

        for entry in existing_entries:

            if (
                entry["section"] == new_entry["section"]
                and entry["day"] == new_entry["day"]
                and entry["time"] == new_entry["time"]
            ):
                return "Section conflict"

        return None

    # --------------------------------------------------
    # Run checks concurrently
    # --------------------------------------------------

    def check_conflicts(self, new_entry, existing_entries):

        with self.lock:

            with ThreadPoolExecutor(max_workers=3) as executor:

                faculty_future = executor.submit(
                    self.check_faculty,
                    new_entry,
                    existing_entries
                )

                room_future = executor.submit(
                    self.check_room,
                    new_entry,
                    existing_entries
                )

                section_future = executor.submit(
                    self.check_section,
                    new_entry,
                    existing_entries
                )

                results = [
                    faculty_future.result(),
                    room_future.result(),
                    section_future.result()
                ]

        conflicts = [
            result
            for result in results
            if result is not None
        ]

        return conflicts


# --------------------------------------------------
# Test
# --------------------------------------------------

if __name__ == "__main__":

    engine = ConflictEngine()

    existing_entries = [
        {
            "subject": "Operating Systems",
            "faculty": 1,
            "room": 1,
            "section": "CSE-A",
            "day": "Monday",
            "time": "10:00-11:00"
        },
        {
            "subject": "DBMS",
            "faculty": 2,
            "room": 2,
            "section": "CSE-B",
            "day": "Monday",
            "time": "11:00-12:00"
        }
    ]

    new_entry = {
        "subject": "Computer Networks",
        "faculty_id": 1,
        "room_id": 2,
        "section": "CSE-C",
        "day": "Monday",
        "time": "10:00-11:00"
    }

    conflicts = engine.check_conflicts(
        new_entry,
        existing_entries
    )

    if conflicts:
        print("CONFLICT DETECTED:")

        for conflict in conflicts:
            print("-", conflict)

    else:
        print("No conflicts. Assignment is valid.")