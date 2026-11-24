import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.models import (
    Faculty, Section, Semester, Programme, Department, AcademicYear,
    TimetableVersion, ScheduledClass, VersionStatus, Subject, Room, Floor, Building, AuditLog,
    FacultySubjectEligibility, FacultySemesterEligibility
)
from app.dependencies import get_current_faculty
from app.services.academic_helper import format_section_identity
from app.services.image_generator import generate_faculty_weekly_png, sanitize

router = APIRouter(prefix="/faculty", tags=["Faculty Portal"])


def format_minute(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


@router.get("/profile")
def faculty_profile(
    faculty: Faculty = Depends(get_current_faculty),
    db: Session = Depends(get_db)
):
    """
    Returns faculty member's profile, qualifications, department, and teaching safety workload bounds.
    """
    dept = db.get(Department, faculty.department_id) if faculty.department_id else None

    subj_eligs = db.query(FacultySubjectEligibility).filter(
        FacultySubjectEligibility.faculty_id == faculty.id
    ).all()
    sem_eligs = db.query(FacultySemesterEligibility).filter(
        FacultySemesterEligibility.faculty_id == faculty.id
    ).all()

    eligible_subjects = []
    for se in subj_eligs:
        sub = db.get(Subject, se.subject_id)
        if sub:
            eligible_subjects.append({
                "id": sub.id,
                "code": sub.code,
                "name": sub.name
            })

    return {
        "faculty": {
            "id": faculty.id,
            "faculty_id": faculty.faculty_id,
            "full_name": faculty.full_name,
            "email": faculty.email,
            "phone": faculty.phone,
            "whatsapp_number": faculty.whatsapp_number,
            "designation": faculty.designation or "Faculty Member",
            "highest_qualification": faculty.highest_qualification or "Ph.D.",
            "specialisation": faculty.specialisation or "General Academic"
        },
        "department": {
            "id": dept.id,
            "name": dept.name,
            "code": dept.code
        } if dept else None,
        "workload_limits": {
            "max_classes_per_day": faculty.max_classes_per_day,
            "max_classes_per_week": faculty.max_classes_per_week,
            "max_consecutive_hours": faculty.max_consecutive_hours,
            "min_break_minutes": faculty.min_break_minutes,
            "cross_department_approved": faculty.cross_department_approved
        },
        "eligible_subjects": eligible_subjects,
        "eligible_semesters": [se.semester_number for se in sem_eligs]
    }


def get_faculty_published_classes(db: Session, faculty: Faculty) -> list[dict]:
    """
    Finds and serialises all classes taught by this faculty member from currently active PUBLISHED
    timetable versions across all sections and programmes.
    """
    published_versions = db.scalars(
        select(TimetableVersion)
        .where(TimetableVersion.status == VersionStatus.PUBLISHED)
        .order_by(TimetableVersion.version_number.desc())
    ).all()

    if not published_versions:
        return []

    # Map section_id -> latest published version_id
    section_latest_version = {}
    for v in published_versions:
        secs = db.scalars(
            select(ScheduledClass.section_id)
            .where(ScheduledClass.version_id == v.id)
            .distinct()
        ).all()
        for s_id in secs:
            if s_id not in section_latest_version:
                section_latest_version[s_id] = v.id

    active_v_ids = set(section_latest_version.values())
    if not active_v_ids:
        # Fallback to all published version ids
        active_v_ids = {v.id for v in published_versions}

    scheduled = db.scalars(
        select(ScheduledClass)
        .where(
            ScheduledClass.faculty_id == faculty.id,
            ScheduledClass.version_id.in_(active_v_ids)
        )
    ).all()

    classes = []
    for sc in scheduled:
        # If section is tracked, ensure class is from the newest published version for that section
        if sc.section_id in section_latest_version and sc.version_id != section_latest_version[sc.section_id]:
            continue

        subj = db.get(Subject, sc.subject_id)
        sec = db.get(Section, sc.section_id)
        prog = db.get(Programme, sec.programme_id) if sec else None
        sem = db.get(Semester, sec.semester_id) if sec else None
        room = db.get(Room, sc.room_id)
        flr = db.get(Floor, room.floor_id) if room else None
        bld = db.get(Building, flr.building_id) if flr else None

        sec_ident = format_section_identity(
            sec.name if sec else "",
            prog.name if prog else None,
            prog.code if prog else None,
            sem.number if sem else None
        ) if sec else {"section_code": "", "section_display_name": "", "full_name": ""}

        classes.append({
            "id": sc.id,
            "version_id": sc.version_id,
            "weekday": sc.weekday,
            "start_minute": sc.start_minute,
            "end_minute": sc.end_minute,
            "start": format_minute(sc.start_minute),
            "end": format_minute(sc.end_minute),
            "duration": sc.end_minute - sc.start_minute,
            "subject": subj.name if subj else "Unknown",
            "subject_code": subj.code if subj else "",
            "session_type": subj.session_type.value if subj and hasattr(subj.session_type, "value") else "LECTURE",
            "programme": prog.name if prog else "Unknown",
            "programme_code": prog.code if prog else "",
            "semester": sem.number if sem else None,
            "section": {
                "id": sec.id if sec else None,
                "name": sec.name if sec else "",
                "section_code": sec_ident["section_code"],
                "section_display_name": sec_ident["display_name"],
                "full_name": sec_ident["full_name"],
                "student_count": sec.student_count if sec else 0
            },
            "section_code": sec_ident["section_code"],
            "section_display_name": sec_ident["display_name"],
            "classroom": {
                "id": room.id if room else None,
                "name": room.name if room else "TBA",
                "capacity": room.capacity if room else 0
            },
            "room": room.name if room else "TBA",
            "building": bld.name if bld else "",
            "floor": flr.name if flr else ""
        })

    classes.sort(key=lambda c: (c["weekday"], c["start_minute"]))
    return classes


@router.get("/timetable")
def faculty_timetable_view(
    faculty: Faculty = Depends(get_current_faculty),
    db: Session = Depends(get_db)
):
    """
    Returns the combined weekly timetable for this faculty member across all sections and programmes
    from active PUBLISHED timetables.
    """
    classes = get_faculty_published_classes(db, faculty)

    # Compute summary metrics
    days_count = {d: 0 for d in range(7)}
    total_minutes = 0
    distinct_subjects = set()
    distinct_sections = set()

    for c in classes:
        days_count[c["weekday"]] = days_count.get(c["weekday"], 0) + 1
        total_minutes += c["duration"]
        if c.get("subject_code"):
            distinct_subjects.add(c["subject_code"])
        if c.get("section_code"):
            distinct_sections.add(c["section_code"])

    # Overlap / conflict sanity check
    conflicts = []
    by_day = {}
    for c in classes:
        by_day.setdefault(c["weekday"], []).append(c)

    for day, day_classes in by_day.items():
        day_classes_sorted = sorted(day_classes, key=lambda x: x["start_minute"])
        for i in range(len(day_classes_sorted) - 1):
            if day_classes_sorted[i]["end_minute"] > day_classes_sorted[i + 1]["start_minute"]:
                conflicts.append({
                    "class_a": day_classes_sorted[i],
                    "class_b": day_classes_sorted[i + 1],
                    "weekday": day,
                    "reason": "Overlapping class assignment"
                })

    weekly_hours = round(total_minutes / 60, 1)
    remaining_capacity = max(0, faculty.max_classes_per_week - len(classes))

    status = "PUBLISHED" if classes else "NO_CLASSES_SCHEDULED"

    return {
        "status": status,
        "faculty": {
            "id": faculty.id,
            "faculty_id": faculty.faculty_id,
            "full_name": faculty.full_name,
            "designation": faculty.designation or "Faculty Member"
        },
        "classes": classes,
        "summary": {
            "total_classes": len(classes),
            "weekly_hours": weekly_hours,
            "classes_per_day": days_count,
            "distinct_subjects": len(distinct_subjects),
            "distinct_sections": len(distinct_sections),
            "max_classes_per_week": faculty.max_classes_per_week,
            "max_classes_per_day": faculty.max_classes_per_day,
            "remaining_capacity": remaining_capacity,
            "conflicts": conflicts
        }
    }


@router.get("/timetable/download")
def download_faculty_timetable(
    faculty: Faculty = Depends(get_current_faculty),
    db: Session = Depends(get_db)
):
    """
    Generates and returns the faculty's consolidated timetable image as a PNG download.
    """
    classes = get_faculty_published_classes(db, faculty)

    if not classes:
        raise HTTPException(
            404,
            f"No published classes are currently scheduled for faculty {faculty.full_name}. Please publish a timetable version first."
        )

    full_path, filename = generate_faculty_weekly_png(db, faculty.id, classes)

    if not os.path.exists(full_path):
        raise HTTPException(500, "Failed to generate faculty timetable image file.")

    return FileResponse(
        path=full_path,
        media_type="image/png",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/announcements")
def faculty_announcements(
    faculty: Faculty = Depends(get_current_faculty),
    db: Session = Depends(get_db)
):
    """
    Returns published timetable notifications and academic announcements.
    """
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.action.in_(["PUBLISH", "APPROVE", "FACULTY_ASSIGNMENT", "RESCHEDULE"]))
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    ).all()

    announcements = []
    for l in logs:
        action_title = {
            "PUBLISH": "New Timetable Published",
            "APPROVE": "Timetable Version Approved",
            "FACULTY_ASSIGNMENT": "Academic Faculty Assignment Updated",
            "RESCHEDULE": "Timetable Rescheduled"
        }.get(l.action, "Academic Notification")

        announcements.append({
            "id": l.id,
            "title": action_title,
            "action": l.action,
            "timestamp": l.created_at.isoformat() if l.created_at else None,
            "details": l.details or {}
        })

    return announcements
