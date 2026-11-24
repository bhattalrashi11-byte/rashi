import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.models import (
    Student, Section, Semester, Programme, Department, AcademicYear,
    Enrolment, TimetableVersion, ScheduledClass, VersionStatus,
    Faculty, Subject, Room, Floor, Building, AuditLog
)
from app.dependencies import get_current_student
from app.services.image_generator import generate_timetable_png, sanitize

router = APIRouter(prefix="/student", tags=["Student Portal"])


@router.get("/profile")
def student_profile(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """
    Returns student's academic profile and enrolled section information.
    """
    dept = db.get(Department, student.department_id) if student.department_id else None
    prog = db.get(Programme, student.programme_id) if student.programme_id else None

    active_enr = db.query(Enrolment).filter(
        Enrolment.student_id == student.id,
        Enrolment.active.is_(True)
    ).first()

    section = None
    semester = None
    academic_year = None

    if active_enr:
        section = db.get(Section, active_enr.section_id)
        if section:
            semester = db.get(Semester, section.semester_id)
            if semester:
                academic_year = db.get(AcademicYear, semester.academic_year_id)

    curr_sem = student.current_semester or (semester.number if semester else 1)
    curr_year = student.current_year or ((curr_sem + 1) // 2)

    return {
        "student": {
            "id": student.id,
            "student_id": student.student_id,
            "full_name": student.full_name,
            "email": student.email,
            "phone": student.phone,
            "admission_year": student.admission_year,
            "current_year": curr_year,
            "current_semester": curr_sem,
        },
        "department": {
            "id": dept.id,
            "name": dept.name,
            "code": dept.code
        } if dept else None,
        "programme": {
            "id": prog.id,
            "name": prog.name,
            "code": prog.code
        } if prog else None,
        "semester": {
            "id": semester.id,
            "number": semester.number
        } if semester else None,
        "academic_year": {
            "id": academic_year.id,
            "name": academic_year.name
        } if academic_year else None,
        "section": {
            "id": section.id,
            "name": section.name,
            "student_count": section.student_count
        } if section else None
    }


@router.get("/timetable")
def student_timetable(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """
    Returns the latest PUBLISHED timetable for the student's assigned section only.
    Draft timetables are strictly withheld from students.
    """
    active_enr = db.query(Enrolment).filter(
        Enrolment.student_id == student.id,
        Enrolment.active.is_(True)
    ).first()

    if not active_enr:
        return {
            "status": "UNENROLLED",
            "message": "You are not currently enrolled in any section.",
            "version": None,
            "classes": []
        }

    section = db.get(Section, active_enr.section_id)
    if not section:
        return {
            "status": "UNENROLLED",
            "message": "Enrolled section not found.",
            "version": None,
            "classes": []
        }

    # Find the latest PUBLISHED timetable that contains scheduled classes for this section
    published_versions = db.scalars(
        select(TimetableVersion)
        .where(TimetableVersion.status == VersionStatus.PUBLISHED)
        .order_by(TimetableVersion.version_number.desc())
    ).all()

    target_version = None
    classes = []

    for v in published_versions:
        scheduled = db.scalars(
            select(ScheduledClass).where(
                ScheduledClass.version_id == v.id,
                ScheduledClass.section_id == section.id
            )
        ).all()
        if scheduled:
            target_version = v
            for sc in scheduled:
                faculty = db.get(Faculty, sc.faculty_id)
                subject = db.get(Subject, sc.subject_id)
                room = db.get(Room, sc.room_id)
                floor = db.get(Floor, room.floor_id) if room else None
                building = db.get(Building, floor.building_id) if floor else None

                classes.append({
                    "id": sc.id,
                    "weekday": sc.weekday,
                    "start_minute": sc.start_minute,
                    "end_minute": sc.end_minute,
                    "duration": sc.end_minute - sc.start_minute,
                    "subject": subject.name if subject else "Unknown",
                    "subject_code": subject.code if subject else "",
                    "session_type": subject.session_type.value if subject and hasattr(subject.session_type, "value") else "LECTURE",
                    "faculty": faculty.full_name if faculty else "Unknown",
                    "faculty_id": faculty.faculty_id if faculty else "",
                    "room": room.name if room else "Unknown",
                    "building": building.name if building else ""
                })
            break

    if not target_version:
        return {
            "status": "NO_PUBLISHED_TIMETABLE",
            "message": f"No published timetable is currently available for Section {section.name}.",
            "section": {"id": section.id, "name": section.name},
            "version": None,
            "classes": []
        }

    return {
        "status": "PUBLISHED",
        "version": {
            "id": target_version.id,
            "version_number": target_version.version_number,
            "published_at": target_version.created_at.isoformat() if target_version.created_at else None
        },
        "section": {
            "id": section.id,
            "name": section.name
        },
        "classes": sorted(classes, key=lambda c: (c["weekday"], c["start_minute"]))
    }


@router.get("/timetable/download")
def student_timetable_download(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """
    Downloads the high-resolution PNG timetable for the student's assigned section.
    """
    active_enr = db.query(Enrolment).filter(
        Enrolment.student_id == student.id,
        Enrolment.active.is_(True)
    ).first()

    if not active_enr:
        raise HTTPException(404, "Student is not enrolled in an active section")

    section = db.get(Section, active_enr.section_id)
    if not section:
        raise HTTPException(404, "Enrolled section not found")

    published_versions = db.scalars(
        select(TimetableVersion)
        .where(TimetableVersion.status == VersionStatus.PUBLISHED)
        .order_by(TimetableVersion.version_number.desc())
    ).all()

    target_version = None
    for v in published_versions:
        has_classes = db.scalar(
            select(ScheduledClass.id).where(
                ScheduledClass.version_id == v.id,
                ScheduledClass.section_id == section.id
            ).limit(1)
        )
        if has_classes:
            target_version = v
            break

    if not target_version:
        raise HTTPException(404, f"No published timetable available for Section {section.name}")

    # Generate PNG image
    image_record = generate_timetable_png(db, target_version.id, "STUDENT", section.id)
    db.commit()

    if not image_record or not os.path.exists(image_record.file_path):
        raise HTTPException(500, "Timetable image could not be generated on disk")

    sem = db.get(Semester, section.semester_id) if section.semester_id else None
    prog = db.get(Programme, section.programme_id) if section.programme_id else None
    prog_code = sanitize(prog.code) if prog else "UG"
    sem_num = sem.number if sem else 1
    sec_name = sanitize(section.name)

    download_filename = f"Timetable_{prog_code}_Sem{sem_num}_Sec{sec_name}.png"

    return FileResponse(
        image_record.file_path,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'},
        filename=download_filename
    )


@router.get("/announcements")
def student_announcements(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """
    Returns published announcements and version change notices.
    """
    published = db.scalars(
        select(TimetableVersion)
        .where(TimetableVersion.status == VersionStatus.PUBLISHED)
        .order_by(TimetableVersion.version_number.desc())
        .limit(5)
    ).all()

    announcements = []
    for v in published:
        announcements.append({
            "id": v.id,
            "title": f"Timetable Version {v.version_number} Published",
            "date": v.created_at.strftime("%Y-%m-%d %H:%M") if v.created_at else "Recently",
            "content": f"The official timetable Version {v.version_number} has been published by the academic administration. All classes and classroom assignments are now effective."
        })

    return announcements
