"""
Endpoints demonstrating Operating System and DBMS concepts:
1. CPU Scheduling Policies (Priority, SJF, Hybrid)
2. Semaphore Concurrency Control & Mutual Exclusion
3. Deadlock Prevention & Coffman Condition Handling
4. Critical Section Protection
"""

import time
import threading
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db, SessionLocal
from app.dependencies import get_current_admin
from app.concurrency import (
    acquire_generation_semaphore,
    DeadlockPreventionManager,
    GENERATION_SEMAPHORE,
    TIMETABLE_ADVISORY_LOCK_ID
)
from app.models import Faculty, Room, ScheduledClass

router = APIRouter(prefix="/os", tags=["OS & DBMS Concepts Demonstration"])


@router.get("/concepts")
def get_os_concepts():
    """
    Returns an academic explanation of the OS & DBMS concepts implemented in Schedulix,
    directly linking concepts to the actual codebase.
    """
    return {
        "title": "Schedulix OS and DBMS Architecture",
        "concepts": {
            "cpu_scheduling": {
                "name": "CPU Scheduling Analogy",
                "strategies": ["Priority Scheduling", "Shortest Job First (SJF)", "Hybrid Priority-SJF"],
                "formula": "Score = (Priority_Weight * (Priority / 10)) + (SJF_Weight * ((Max_Dur - Dur) / (Max_Dur - Min_Dur)))",
                "code_location": "backend/app/services/scheduler.py -> score()"
            },
            "semaphores": {
                "name": "Counting / Binary Semaphore",
                "mechanism": "Python threading.Semaphore(1) combined with PostgreSQL pg_try_advisory_xact_lock",
                "invariants": "Guarantees that at most 1 timetable generation executes for the institution simultaneously.",
                "code_location": "backend/app/concurrency.py -> acquire_generation_semaphore()"
            },
            "deadlock_prevention": {
                "name": "Coffman Conditions & Deadlock Prevention",
                "eliminated_conditions": {
                    "Circular Wait": "Enforces strict canonical resource lock ordering (Faculty -> Room -> Session).",
                    "Hold and Wait": "Atomic multi-resource lock acquisition with immediate rollback on timeout.",
                    "No Preemption": "PostgreSQL bounded lock_timeout triggers transaction abort and safe rollback."
                },
                "code_location": "backend/app/concurrency.py -> DeadlockPreventionManager"
            },
            "critical_sections": {
                "name": "Critical Sections",
                "protected_operations": [
                    "Timetable Generation (OR-Tools solver execution and persistence)",
                    "Manual / Automatic Rescheduling (slot reassignment and conflict check)",
                    "Unique Identifier Generation (Student/Faculty ID serial allocation)"
                ]
            },
            "dbms_triggers": {
                "name": "SQL Triggers and ACID",
                "triggers": [
                    "trg_audit_scheduled_classes (Automated audit trail)",
                    "trg_validate_faculty_availability (Overlapping window prevention)",
                    "trg_maintain_session_metadata (Session duration and override tracking)"
                ],
                "code_location": "backend/triggers.sql"
            }
        }
    }


@router.get("/semaphore/status")
def get_semaphore_status(db: Session = Depends(get_db)):
    """
    Inspects the live state of the concurrency semaphore and database advisory locks.
    """
    # Check PostgreSQL advisory lock status
    is_db_locked = db.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = :lock_id"),
        {"lock_id": TIMETABLE_ADVISORY_LOCK_ID}
    ).scalar() > 0

    return {
        "local_semaphore_available": not GENERATION_SEMAPHORE._value == 0,
        "db_advisory_lock_active": is_db_locked,
        "status": "BUSY" if is_db_locked or GENERATION_SEMAPHORE._value == 0 else "IDLE",
        "description": "Binary semaphore controlling access to timetable generation engine."
    }


@router.post("/semaphore/test-concurrency")
def test_semaphore_concurrency(
    hold_seconds: float = Query(default=2.0, ge=0.5, le=10.0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """
    Simulates a long-running timetable generation inside the semaphore critical section.
    If another request is sent while this runs, the semaphore rejects it with HTTP 429 Too Many Requests.
    """
    with acquire_generation_semaphore(db, scope="TEST", timeout_seconds=1.0) as sem_info:
        time.sleep(hold_seconds)
        return {
            "status": "COMPLETED",
            "message": f"Successfully held critical section for {hold_seconds} seconds under semaphore control.",
            "semaphore_info": sem_info
        }


@router.post("/deadlock/test-prevention")
def test_deadlock_prevention(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """
    Demonstrates deadlock prevention by acquiring multiple resource locks (e.g. Faculty and Room)
    in strict canonical order. Demonstrates that circular wait is impossible.
    """
    faculty = db.query(Faculty).first()
    room = db.query(Room).first()

    if not faculty or not room:
        raise HTTPException(400, "Need at least 1 faculty and 1 room to run deadlock demonstration.")

    # Request resources in random / unordered input
    requested_unordered = [
        {"type": "CLASSROOM", "id": room.id},
        {"type": "FACULTY", "id": faculty.id}
    ]

    result = DeadlockPreventionManager.acquire_ordered_locks(
        db,
        requested_unordered,
        timeout_seconds=2.0
    )

    db.commit()

    return {
        "status": "SUCCESS",
        "explanation": "Deadlock prevented: resources were automatically sorted and locked in canonical hierarchy (FACULTY before CLASSROOM) eliminating Circular Wait.",
        "input_order": ["CLASSROOM", "FACULTY"],
        "enforced_order": result["lock_order"],
        "strategy": result["strategy"]
    }
