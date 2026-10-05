import heapq


class SchedulingJob:
    """
    Represents one timetable allocation task.
    """

    def __init__(self, subject, faculty, section, slots_required, priority):
        self.subject = subject
        self.faculty = faculty
        self.section = section
        self.slots_required = slots_required
        self.priority = priority

    def __repr__(self):
        return (
            f"{self.subject} | "
            f"Priority={self.priority} | "
            f"Slots={self.slots_required}"
        )


class TimetableScheduler:

    def __init__(self):
        self.jobs = []

    # --------------------------------------------------
    # Add a scheduling job
    # --------------------------------------------------

    def add_job(
        self,
        subject,
        faculty,
        section,
        slots_required,
        priority
    ):
        job = SchedulingJob(
            subject=subject,
            faculty=faculty,
            section=section,
            slots_required=slots_required,
            priority=priority
        )

        self.jobs.append(job)

    # --------------------------------------------------
    # Priority Scheduling
    # --------------------------------------------------

    def priority_scheduling(self):

        queue = []

        for job in self.jobs:

            heapq.heappush(
                queue,
                (
                    job.priority,
                    job
                )
            )

        result = []

        while queue:

            _, job = heapq.heappop(queue)

            result.append(job)

        return result

    # --------------------------------------------------
    # Shortest Job First
    # --------------------------------------------------

    def sjf_scheduling(self):

        queue = []

        for job in self.jobs:

            heapq.heappush(
                queue,
                (
                    job.slots_required,
                    job
                )
            )

        result = []

        while queue:

            _, job = heapq.heappop(queue)

            result.append(job)

        return result


# --------------------------------------------------
# Test the scheduler
# --------------------------------------------------

if __name__ == "__main__":

    scheduler = TimetableScheduler()

    scheduler.add_job(
        subject="Operating Systems",
        faculty="Dr. Sharma",
        section="CSE-B",
        slots_required=4,
        priority=1
    )

    scheduler.add_job(
        subject="DBMS",
        faculty="Dr. Verma",
        section="CSE-B",
        slots_required=3,
        priority=2
    )

    scheduler.add_job(
        subject="Computer Networks",
        faculty="Dr. Singh",
        section="CSE-B",
        slots_required=2,
        priority=3
    )

    print("\n--- Priority Scheduling ---")

    for job in scheduler.priority_scheduling():
        print(job)

    print("\n--- Shortest Job First ---")

    for job in scheduler.sjf_scheduling():
        print(job)