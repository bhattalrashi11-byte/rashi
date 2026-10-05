from concurrent.futures import ThreadPoolExecutor
from threading import Lock


class ConflictEngine:

    def __init__(self):
        # Shared resource lock
        self.lock = Lock()


    def check_faculty(self, new_entry, existing_entries):

        for entry in existing_entries:

            if (
                entry["faculty"] == new_entry["faculty"]
                and entry["day"] == new_entry["day"]
                and entry["time"] == new_entry["time"]
            ):
                return "Faculty conflict"

        return None


    def check_room(self, new_entry, existing_entries):

        for entry in existing_entries:

            if (
                entry["room"] == new_entry["room"]
                and entry["day"] == new_entry["day"]
                and entry["time"] == new_entry["time"]
            ):
                return "Room conflict"

        return None


    def check_section(self, new_entry, existing_entries):

        for entry in existing_entries:

            if (
                entry["section"] == new_entry["section"]
                and entry["day"] == new_entry["day"]
                and entry["time"] == new_entry["time"]
            ):
                return "Section conflict"

        return None


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


if __name__ == "__main__":

    engine = ConflictEngine()

    existing_entries = [

        {
            "subject": "Operating Systems",
            "faculty": "Dr. Sharma",
            "room": "C-301",
            "section": "CSE-A",
            "day": "Monday",
            "time": "10:00-11:00"
        },

        {
            "subject": "DBMS",
            "faculty": "Dr. Verma",
            "room": "C-302",
            "section": "CSE-B",
            "day": "Monday",
            "time": "11:00-12:00"
        }
    ]

    new_entry = {

        "subject": "Computer Networks",
        "faculty": "Dr. Sharma",
        "room": "C-305",
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