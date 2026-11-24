from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_admin

from app.models import (
    Department,
    Programme,
    AcademicYear,
    Semester,
    Section,
    Subject,
    Student,
    Faculty,
    FacultySubjectEligibility,
    FacultySemesterEligibility,
    FacultyAssignment,
    Enrolment,
    ScheduledClass,
    TimetableVersion,
    VersionStatus,
)

from app.schemas import (
    DepartmentCreate,
    ProgrammeCreate,
    ProgrammeUpdate,
    AcademicYearCreate,
    SectionCreate,
    SubjectCreate,
    SubjectUpdate,
    StudentCreate,
    StudentUpdate,
    StudentTransferRequest,
    FacultyCreate,
    FacultyUpdate,
    FacultyEligibilityUpdate,
    FacultyPasswordResetRequest,
    AssignmentCreate,
)

from app.security import hash_password
from app.services.academic_helper import format_section_identity

from app.audit import record_audit


router = APIRouter(
    prefix="/academic",
    tags=["Academic Management"],
    dependencies=[Depends(get_current_admin)]
)


# ============================================================
# COMMON HELPERS
# ============================================================

def create_record(db, model, values, admin, entity):
    try:
        record = model(**values)

        db.add(record)
        db.flush()

        record_audit(
            db,
            "CREATE",
            entity,
            record.id,
            admin.id,
            values
        )

        db.commit()
        db.refresh(record)

        return record

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"{entity} already exists or violates a database constraint."
        )


def generate_student_id(db, admission_year):
    """
    Format:
    YY + 7 digit serial number

    Example:
    Admission year 2024 -> 240000001
    """

    prefix = str(admission_year)[-2:]

    existing = db.query(Student.student_id).filter(
        Student.student_id.like(f"{prefix}%")
    ).all()

    highest = 0

    for row in existing:
        value = row[0]

        if (
            value
            and value.startswith(prefix)
            and value[len(prefix):].isdigit()
        ):
            highest = max(
                highest,
                int(value[len(prefix):])
            )

    return f"{prefix}{highest + 1:07d}"


def generate_faculty_id(db, department):
    """
    Format:
    FAC-DEPARTMENT-SERIAL

    Example:
    FAC-CS-001
    """

    prefix = f"FAC-{department.code.upper()}-"

    existing = db.query(Faculty.faculty_id).filter(
        Faculty.faculty_id.like(f"{prefix}%")
    ).all()

    highest = 0

    for row in existing:
        value = row[0]

        if value and value.startswith(prefix):
            suffix = value[len(prefix):]

            if suffix.isdigit():
                highest = max(highest, int(suffix))

    return f"{prefix}{highest + 1:03d}"


def get_values(data):
    return data.model_dump(exclude_none=True)


# ============================================================
# DEPARTMENTS
# ============================================================

@router.post("/departments")
def create_department(
    data: DepartmentCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    values = get_values(data)

    values["code"] = values["code"].upper().strip()

    return create_record(
        db,
        Department,
        values,
        admin,
        "Department"
    )


@router.get("/departments")
def departments(
    db: Session = Depends(get_db)
):
    return db.query(Department).order_by(
        Department.name
    ).all()


# ============================================================
# PROGRAMMES
# ============================================================

@router.post("/programmes")
def create_programme(
    data: ProgrammeCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    if not db.get(Department, data.department_id):
        raise HTTPException(404, "Department not found")

    return create_record(
        db,
        Programme,
        get_values(data),
        admin,
        "Programme"
    )


@router.get("/programmes")
def programmes(
    department_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Programme)
    if department_id:
        query = query.filter(Programme.department_id == department_id)
    records = query.order_by(Programme.name).all()
    result = []
    for p in records:
        dept = db.get(Department, p.department_id)
        sem_count = db.query(Semester).filter(Semester.programme_id == p.id).count()
        sec_count = db.query(Section).filter(Section.programme_id == p.id).count()
        stu_count = db.query(Student).filter(Student.programme_id == p.id).count()
        sub_count = db.query(Subject).filter(Subject.programme_id == p.id).count()
        result.append({
            "id": p.id,
            "name": p.name,
            "code": p.code,
            "duration_years": p.duration_years,
            "department_id": p.department_id,
            "department_name": dept.name if dept else "Unknown",
            "department_code": dept.code if dept else "",
            "semester_count": sem_count,
            "section_count": sec_count,
            "student_count": stu_count,
            "subject_count": sub_count
        })
    return result


@router.put("/programmes/{programme_id}")
def update_programme(
    programme_id: str,
    data: ProgrammeUpdate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    prog = db.get(Programme, programme_id)
    if not prog:
        raise HTTPException(404, "Programme not found")

    values = data.model_dump(exclude_unset=True)
    if "department_id" in values and values["department_id"]:
        if not db.get(Department, values["department_id"]):
            raise HTTPException(404, "Department not found")

    for k, v in values.items():
        if v is not None:
            setattr(prog, k, v)

    record_audit(db, "UPDATE", "Programme", prog.id, admin.id, values)
    db.commit()
    db.refresh(prog)
    return prog


@router.delete("/programmes/{programme_id}")
def delete_programme(
    programme_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    prog = db.get(Programme, programme_id)
    if not prog:
        raise HTTPException(404, "Programme not found")

    sem_count = db.query(Semester).filter(Semester.programme_id == programme_id).count()
    sec_count = db.query(Section).filter(Section.programme_id == programme_id).count()
    sub_count = db.query(Subject).filter(Subject.programme_id == programme_id).count()
    stu_count = db.query(Student).filter(Student.programme_id == programme_id).count()

    if sem_count > 0 or sec_count > 0 or sub_count > 0 or stu_count > 0:
        raise HTTPException(
            400,
            f"Cannot delete programme '{prog.name}'. It has {sem_count} semesters, {sec_count} sections, {sub_count} subjects, and {stu_count} enrolled students. Please reassign or remove dependent records first."
        )

    record_audit(db, "DELETE", "Programme", prog.id, admin.id, {"code": prog.code, "name": prog.name})
    db.delete(prog)
    db.commit()
    return {"status": "DELETED", "message": f"Programme '{prog.name}' deleted successfully."}


# ============================================================
# ACADEMIC YEARS
# ============================================================

@router.post("/academic-years")
def create_year(
    data: AcademicYearCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    if data.end_date <= data.start_date:
        raise HTTPException(
            400,
            "End date must be after start date"
        )

    return create_record(
        db,
        AcademicYear,
        get_values(data),
        admin,
        "AcademicYear"
    )


@router.get("/academic-years")
def academic_years(
    db: Session = Depends(get_db)
):
    return db.query(AcademicYear).order_by(
        AcademicYear.start_date.desc()
    ).all()


@router.post("/academic-years/{year_id}/activate")
def activate_academic_year(
    year_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    target = db.get(AcademicYear, year_id)
    if not target:
        raise HTTPException(404, "Academic year not found")

    all_years = db.query(AcademicYear).all()
    for ay in all_years:
        ay.active = (ay.id == year_id)

    record_audit(db, "ACTIVATE", "AcademicYear", target.id, admin.id, {"name": target.name})
    db.commit()
    return {"status": "ACTIVATED", "year_id": target.id, "name": target.name}


# ============================================================
# SEMESTERS
# ============================================================

@router.post("/semesters")
def create_semester(
    programme_id: str,
    academic_year_id: str,
    number: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    if not db.get(Programme, programme_id):
        raise HTTPException(404, "Programme not found")

    if not db.get(AcademicYear, academic_year_id):
        raise HTTPException(404, "Academic year not found")

    if not 1 <= number <= 12:
        raise HTTPException(400, "Invalid semester number")

    values = {
        "programme_id": programme_id,
        "academic_year_id": academic_year_id,
        "number": number
    }

    return create_record(
        db,
        Semester,
        values,
        admin,
        "Semester"
    )


@router.get("/semesters")
def semesters(
    programme_id: Optional[str] = None,
    academic_year_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Semester)
    if programme_id:
        query = query.filter(Semester.programme_id == programme_id)
    if academic_year_id:
        query = query.filter(Semester.academic_year_id == academic_year_id)
    records = query.order_by(Semester.number).all()

    result = []
    for sem in records:
        prog = db.get(Programme, sem.programme_id)
        ay = db.get(AcademicYear, sem.academic_year_id)
        prog_year = (sem.number + 1) // 2
        sec_count = db.query(Section).filter(Section.semester_id == sem.id).count()
        sub_count = db.query(Subject).filter(
            (Subject.semester_id == sem.id) |
            ((Subject.programme_id == sem.programme_id) & (Subject.semester_number == sem.number))
        ).count()
        result.append({
            "id": sem.id,
            "programme_id": sem.programme_id,
            "programme_name": prog.name if prog else "Unknown",
            "academic_year_id": sem.academic_year_id,
            "academic_year_name": ay.name if ay else "Unknown",
            "number": sem.number,
            "programme_year": prog_year,
            "section_count": sec_count,
            "subject_count": sub_count
        })
    return result


@router.delete("/semesters/{semester_id}")
def delete_semester(
    semester_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    sem = db.get(Semester, semester_id)
    if not sem:
        raise HTTPException(404, "Semester not found")

    sec_count = db.query(Section).filter(Section.semester_id == semester_id).count()
    sub_count = db.query(Subject).filter(Subject.semester_id == semester_id).count()

    if sec_count > 0 or sub_count > 0:
        raise HTTPException(
            400,
            f"Cannot delete semester {sem.number}. It has {sec_count} sections and {sub_count} subjects assigned to it. Please reassign or delete them first."
        )

    record_audit(db, "DELETE", "Semester", sem.id, admin.id, {"number": sem.number})
    db.delete(sem)
    db.commit()
    return {"status": "DELETED", "message": f"Semester {sem.number} deleted successfully."}


# ============================================================
# SECTIONS
# ============================================================

@router.post("/sections")
def create_section(
    data: SectionCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    if not db.get(Semester, data.semester_id):
        raise HTTPException(404, "Semester not found")

    if not db.get(Programme, data.programme_id):
        raise HTTPException(404, "Programme not found")

    return create_record(
        db,
        Section,
        get_values(data),
        admin,
        "Section"
    )


@router.get("/sections")
def sections(
    programme_id: Optional[str] = None,
    semester_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Section)
    if programme_id:
        query = query.filter(Section.programme_id == programme_id)
    if semester_id:
        query = query.filter(Section.semester_id == semester_id)
    records = query.order_by(Section.name).all()

    result = []
    for sec in records:
        sem = db.get(Semester, sec.semester_id)
        prog = db.get(Programme, sec.programme_id)
        prog_year = (sem.number + 1) // 2 if sem else 1
        active_enrolments = db.query(Enrolment).filter(
            Enrolment.section_id == sec.id,
            Enrolment.active.is_(True)
        ).count()
        sec_ident = format_section_identity(
            sec.name,
            prog.name if prog else None,
            prog.code if prog else None,
            sem.number if sem else None
        )
        result.append({
            "id": sec.id,
            "name": sec.name,
            "section_code": sec_ident["section_code"],
            "full_name": sec_ident["full_name"],
            "display_name": sec_ident["display_name"],
            "programme_id": sec.programme_id,
            "programme_name": prog.name if prog else "Unknown",
            "programme_code": prog.code if prog else "",
            "semester_id": sec.semester_id,
            "semester_number": sem.number if sem else None,
            "programme_year": prog_year,
            "student_count": max(sec.student_count, active_enrolments),
            "active_students": active_enrolments
        })
    return result


@router.delete("/sections/{section_id}")
def delete_section(
    section_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    sec = db.get(Section, section_id)
    if not sec:
        raise HTTPException(404, "Section not found")

    enr_count = db.query(Enrolment).filter(Enrolment.section_id == section_id, Enrolment.active.is_(True)).count()
    assign_count = db.query(FacultyAssignment).filter(FacultyAssignment.section_id == section_id).count()
    class_count = db.query(ScheduledClass).filter(ScheduledClass.section_id == section_id).count()

    if enr_count > 0 or assign_count > 0 or class_count > 0:
        raise HTTPException(
            400,
            f"Cannot delete section '{sec.name}'. It has {enr_count} enrolled students, {assign_count} faculty assignments, and {class_count} scheduled timetable classes. Please reassign or delete them first."
        )

    record_audit(db, "DELETE", "Section", sec.id, admin.id, {"name": sec.name})
    db.delete(sec)
    db.commit()
    return {"status": "DELETED", "message": f"Section '{sec.name}' deleted successfully."}


# ============================================================
# SUBJECTS
# ============================================================

@router.post("/subjects")
def create_subject(
    data: SubjectCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    if not db.get(Department, data.department_id):
        raise HTTPException(404, "Department not found")

    if data.programme_id and not db.get(Programme, data.programme_id):
        raise HTTPException(404, "Programme not found")

    values = get_values(data)
    values["code"] = values["code"].upper().strip()
    values["session_type"] = values["session_type"].upper()

    # Link semester if semester_id is provided
    if values.get("semester_id"):
        sem = db.get(Semester, values["semester_id"])
        if not sem:
            raise HTTPException(404, "Semester not found")
        if not values.get("semester_number"):
            values["semester_number"] = sem.number
        if not values.get("programme_id"):
            values["programme_id"] = sem.programme_id

    # Prevent accidental duplicate subjects in the same programme and semester
    if values.get("programme_id") and values.get("semester_number"):
        dup = db.query(Subject).filter(
            Subject.programme_id == values["programme_id"],
            Subject.semester_number == values["semester_number"],
            Subject.code == values["code"]
        ).first()
        if dup:
            raise HTTPException(
                409,
                f"Subject with code '{values['code']}' already exists in this programme and semester."
            )

    return create_record(
        db,
        Subject,
        values,
        admin,
        "Subject"
    )


@router.get("/subjects")
def subjects(
    programme_id: Optional[str] = None,
    semester_number: Optional[int] = None,
    semester_id: Optional[str] = None,
    department_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Subject)
    if programme_id:
        query = query.filter(Subject.programme_id == programme_id)
    if semester_number is not None:
        query = query.filter(Subject.semester_number == semester_number)
    if semester_id:
        sem = db.get(Semester, semester_id)
        if sem:
            query = query.filter(
                (Subject.semester_id == semester_id) |
                ((Subject.programme_id == sem.programme_id) & (Subject.semester_number == sem.number))
            )
    if department_id:
        query = query.filter(Subject.department_id == department_id)

    records = query.order_by(Subject.code).all()
    result = []
    for sub in records:
        dept = db.get(Department, sub.department_id)
        prog = db.get(Programme, sub.programme_id) if sub.programme_id else None
        sem_num = sub.semester_number
        if not sem_num and sub.semester_id:
            sem = db.get(Semester, sub.semester_id)
            if sem:
                sem_num = sem.number

        result.append({
            "id": sub.id,
            "code": sub.code,
            "name": sub.name,
            "department_id": sub.department_id,
            "department_name": dept.name if dept else "Unknown",
            "department_code": dept.code if dept else "",
            "programme_id": sub.programme_id,
            "programme_name": prog.name if prog else "None (General)",
            "semester_number": sem_num,
            "semester_id": sub.semester_id,
            "session_type": sub.session_type.value if hasattr(sub.session_type, "value") else str(sub.session_type),
            "default_duration": sub.default_duration
        })
    return result


@router.put("/subjects/{subject_id}")
def update_subject(
    subject_id: str,
    data: SubjectUpdate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    sub = db.get(Subject, subject_id)
    if not sub:
        raise HTTPException(404, "Subject not found")

    values = data.model_dump(exclude_unset=True)
    if "code" in values and values["code"]:
        values["code"] = values["code"].upper().strip()
    if "session_type" in values and values["session_type"]:
        values["session_type"] = values["session_type"].upper()

    for k, v in values.items():
        if v is not None:
            setattr(sub, k, v)

    record_audit(db, "UPDATE", "Subject", sub.id, admin.id, values)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/subjects/{subject_id}")
def delete_subject(
    subject_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    sub = db.get(Subject, subject_id)
    if not sub:
        raise HTTPException(404, "Subject not found")

    assign_count = db.query(FacultyAssignment).filter(FacultyAssignment.subject_id == subject_id).count()
    class_count = db.query(ScheduledClass).filter(ScheduledClass.subject_id == subject_id).count()

    if assign_count > 0 or class_count > 0:
        raise HTTPException(
            400,
            f"Cannot delete subject '{sub.name}' ({sub.code}). It is referenced by {assign_count} faculty assignments and {class_count} scheduled timetable classes. Please remove assignments or delete associated timetable sessions first."
        )

    record_audit(db, "DELETE", "Subject", sub.id, admin.id, {"code": sub.code, "name": sub.name})
    db.delete(sub)
    db.commit()
    return {"status": "DELETED", "message": f"Subject '{sub.name}' deleted successfully."}


# ============================================================
# FACULTY
# ============================================================

@router.post("/faculty")
def create_faculty(
    data: FacultyCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    department = db.get(
        Department,
        data.department_id
    )

    if not department:
        raise HTTPException(
            404,
            "Department not found"
        )

    values = get_values(data)
    eligible_subjects = values.pop("eligible_subject_ids", None) or []
    eligible_semesters = values.pop("eligible_semesters", None) or []
    raw_password = values.pop("password", None) or "schedulix2026"
    values["password_hash"] = hash_password(raw_password)

    if not values.get("faculty_id"):
        values["faculty_id"] = generate_faculty_id(
            db,
            department
        )

    values["faculty_id"] = values["faculty_id"].upper().strip()

    faculty_obj = create_record(
        db,
        Faculty,
        values,
        admin,
        "Faculty"
    )

    # Save initial subject eligibilities
    for sub_id in eligible_subjects:
        db.add(FacultySubjectEligibility(faculty_id=faculty_obj.id, subject_id=sub_id))

    # Save initial semester eligibilities
    for sem_num in eligible_semesters:
        db.add(FacultySemesterEligibility(faculty_id=faculty_obj.id, semester_number=int(sem_num)))

    db.commit()
    db.refresh(faculty_obj)
    return faculty_obj


@router.get("/faculty")
def faculty(
    department_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Faculty)
    if department_id:
        query = query.filter(Faculty.department_id == department_id)
    records = query.order_by(Faculty.full_name).all()

    result = []
    for f in records:
        dept = db.get(Department, f.department_id) if f.department_id else None
        subj_eligs = db.query(FacultySubjectEligibility).filter(
            FacultySubjectEligibility.faculty_id == f.id
        ).all()
        sem_eligs = db.query(FacultySemesterEligibility).filter(
            FacultySemesterEligibility.faculty_id == f.id
        ).all()

        eligible_subjects = []
        for se in subj_eligs:
            sub = db.get(Subject, se.subject_id)
            if sub:
                eligible_subjects.append({"id": sub.id, "code": sub.code, "name": sub.name})

        result.append({
            "id": f.id,
            "faculty_id": f.faculty_id,
            "full_name": f.full_name,
            "email": f.email,
            "phone": f.phone,
            "whatsapp_number": f.whatsapp_number,
            "department_id": f.department_id,
            "department_name": dept.name if dept else "Unknown",
            "department_code": dept.code if dept else "",
            "designation": f.designation or "Lecturer",
            "highest_qualification": f.highest_qualification or "Master's Degree",
            "specialisation": f.specialisation or "General",
            "max_classes_per_day": f.max_classes_per_day or 4,
            "max_classes_per_week": f.max_classes_per_week or 18,
            "max_consecutive_hours": f.max_consecutive_hours or 2,
            "min_break_minutes": f.min_break_minutes or 15,
            "cross_department_approved": f.cross_department_approved or False,
            "active": f.active,
            "eligible_subject_ids": [se.subject_id for se in subj_eligs],
            "eligible_subjects": eligible_subjects,
            "eligible_semesters": [se.semester_number for se in sem_eligs]
        })
    return result


@router.get("/faculty/{faculty_id}")
def get_faculty_detail(
    faculty_id: str,
    db: Session = Depends(get_db)
):
    f = db.get(Faculty, faculty_id)
    if not f:
        raise HTTPException(404, "Faculty member not found")

    dept = db.get(Department, f.department_id) if f.department_id else None
    subj_eligs = db.query(FacultySubjectEligibility).filter(
        FacultySubjectEligibility.faculty_id == f.id
    ).all()
    sem_eligs = db.query(FacultySemesterEligibility).filter(
        FacultySemesterEligibility.faculty_id == f.id
    ).all()

    eligible_subjects = []
    for se in subj_eligs:
        sub = db.get(Subject, se.subject_id)
        if sub:
            eligible_subjects.append({"id": sub.id, "code": sub.code, "name": sub.name})

    return {
        "id": f.id,
        "faculty_id": f.faculty_id,
        "full_name": f.full_name,
        "email": f.email,
        "phone": f.phone,
        "whatsapp_number": f.whatsapp_number,
        "department_id": f.department_id,
        "department_name": dept.name if dept else "Unknown",
        "department_code": dept.code if dept else "",
        "designation": f.designation,
        "highest_qualification": f.highest_qualification,
        "specialisation": f.specialisation,
        "max_classes_per_day": f.max_classes_per_day,
        "max_classes_per_week": f.max_classes_per_week,
        "max_consecutive_hours": f.max_consecutive_hours,
        "min_break_minutes": f.min_break_minutes,
        "cross_department_approved": f.cross_department_approved,
        "active": f.active,
        "eligible_subject_ids": [se.subject_id for se in subj_eligs],
        "eligible_subjects": eligible_subjects,
        "eligible_semesters": [se.semester_number for se in sem_eligs]
    }


@router.put("/faculty/{faculty_id}")
def update_faculty(
    faculty_id: str,
    data: FacultyUpdate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    faculty_obj = db.get(Faculty, faculty_id)
    if not faculty_obj:
        raise HTTPException(404, "Faculty member not found")

    values = data.model_dump(exclude_unset=True)
    raw_password = values.pop("password", None)
    if raw_password:
        values["password_hash"] = hash_password(raw_password)

    for k, v in values.items():
        if v is not None:
            setattr(faculty_obj, k, v)

    record_audit(db, "UPDATE_FACULTY", "Faculty", faculty_obj.id, admin.id, values)
    db.commit()
    db.refresh(faculty_obj)
    return faculty_obj


@router.post("/faculty/{faculty_id}/reset-password")
def reset_faculty_password(
    faculty_id: str,
    data: Optional[FacultyPasswordResetRequest] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    faculty_obj = db.get(Faculty, faculty_id)
    if not faculty_obj:
        raise HTTPException(404, "Faculty member not found")

    new_pwd = (data.new_password if data and data.new_password else None) or "schedulix2026"
    faculty_obj.password_hash = hash_password(new_pwd)

    record_audit(
        db,
        "RESET_FACULTY_PASSWORD",
        "Faculty",
        faculty_obj.id,
        admin.id,
        {"faculty_id": faculty_obj.faculty_id}
    )
    db.commit()
    return {
        "status": "SUCCESS",
        "message": f"Password for {faculty_obj.full_name} ({faculty_obj.faculty_id}) has been reset successfully."
    }


@router.post("/faculty/{faculty_id}/eligibility")
def update_faculty_eligibility(
    faculty_id: str,
    data: FacultyEligibilityUpdate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    faculty_obj = db.get(Faculty, faculty_id)
    if not faculty_obj:
        raise HTTPException(404, "Faculty member not found")

    if data.cross_department_approved is not None:
        faculty_obj.cross_department_approved = data.cross_department_approved

    # Replace subject eligibilities
    db.query(FacultySubjectEligibility).filter(
        FacultySubjectEligibility.faculty_id == faculty_id
    ).delete()
    for sub_id in data.subject_ids:
        sub = db.get(Subject, sub_id)
        if sub:
            db.add(FacultySubjectEligibility(faculty_id=faculty_id, subject_id=sub_id))

    # Replace semester eligibilities
    db.query(FacultySemesterEligibility).filter(
        FacultySemesterEligibility.faculty_id == faculty_id
    ).delete()
    for sem_num in data.eligible_semesters:
        db.add(FacultySemesterEligibility(faculty_id=faculty_id, semester_number=int(sem_num)))

    record_audit(db, "UPDATE_ELIGIBILITY", "Faculty", faculty_id, admin.id, {
        "subject_ids": data.subject_ids,
        "eligible_semesters": data.eligible_semesters,
        "cross_department_approved": faculty_obj.cross_department_approved
    })
    db.commit()
    db.refresh(faculty_obj)

    return {
        "status": "UPDATED",
        "faculty_id": faculty_id,
        "subject_count": len(data.subject_ids),
        "semester_count": len(data.eligible_semesters),
        "cross_department_approved": faculty_obj.cross_department_approved
    }


@router.get("/faculty-workload/overview")
def faculty_workload_overview(
    department_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Returns faculty workload statistics:
    - Classes per day
    - Weekly teaching hours
    - Remaining available workload
    - Workload distribution across departments
    """
    query = db.query(Faculty).filter(Faculty.active.is_(True))
    if department_id:
        query = query.filter(Faculty.department_id == department_id)
    faculty_list = query.all()

    # Get latest published or approved timetable version to inspect real scheduled classes
    latest_version = db.scalars(
        select(TimetableVersion)
        .where(TimetableVersion.status.in_([VersionStatus.PUBLISHED, VersionStatus.APPROVED, VersionStatus.DRAFT]))
        .order_by(TimetableVersion.version_number.desc())
        .limit(1)
    ).first()

    scheduled_by_faculty = {}
    if latest_version:
        classes = db.scalars(
            select(ScheduledClass).where(ScheduledClass.version_id == latest_version.id)
        ).all()
        for c in classes:
            if c.faculty_id not in scheduled_by_faculty:
                scheduled_by_faculty[c.faculty_id] = []
            scheduled_by_faculty[c.faculty_id].append(c)

    faculty_records = []
    dept_distribution = {}

    for f in faculty_list:
        dept = db.get(Department, f.department_id) if f.department_id else None
        dept_name = dept.name if dept else "General"

        # Count active assigned sessions from assignments
        assigned_sessions = db.scalar(
            select(func.sum(FacultyAssignment.sessions_per_week)).where(
                FacultyAssignment.faculty_id == f.id,
                FacultyAssignment.active.is_(True)
            )
        ) or 0

        # Classes per day from timetable or assignments
        f_classes = scheduled_by_faculty.get(f.id, [])
        days_count = {day: 0 for day in range(7)}
        total_minutes = 0
        for c in f_classes:
            days_count[c.weekday] = days_count.get(c.weekday, 0) + 1
            total_minutes += (c.end_minute - c.start_minute)

        actual_classes_week = len(f_classes) if f_classes else assigned_sessions
        weekly_hours = round(total_minutes / 60, 1) if total_minutes else round(assigned_sessions * 1.0, 1)
        remaining_workload = max(0, f.max_classes_per_week - actual_classes_week)

        # Workload status flag
        if actual_classes_week >= f.max_classes_per_week:
            status = "AT_CAPACITY"
        elif actual_classes_week >= f.max_classes_per_week * 0.8:
            status = "NEAR_LIMIT"
        else:
            status = "OPTIMAL"

        fac_assigns = db.query(FacultyAssignment).filter(
            FacultyAssignment.faculty_id == f.id,
            FacultyAssignment.active.is_(True)
        ).all()
        assignments_list = []
        for fa in fac_assigns:
            sub = db.get(Subject, fa.subject_id)
            sec = db.get(Section, fa.section_id)
            p = db.get(Programme, sec.programme_id) if sec else None
            sm = db.get(Semester, sec.semester_id) if sec else None
            sec_id = format_section_identity(
                sec.name if sec else "",
                p.name if p else None,
                p.code if p else None,
                sm.number if sm else None
            ) if sec else {"section_code": "", "section_display_name": ""}
            assignments_list.append({
                "id": fa.id,
                "subject_name": sub.name if sub else "",
                "subject_code": sub.code if sub else "",
                "section_id": fa.section_id,
                "section_name": sec.name if sec else "",
                "section_code": sec_id["section_code"],
                "section_display_name": sec_id["section_display_name"],
                "sessions_per_week": fa.sessions_per_week
            })

        record = {
            "id": f.id,
            "faculty_id": f.id,
            "faculty_code": f.faculty_id,
            "full_name": f.full_name,
            "department_id": f.department_id,
            "department_name": dept_name,
            "designation": f.designation or "Faculty",
            "highest_qualification": f.highest_qualification or "Ph.D.",
            "specialisation": f.specialisation or "General",
            "max_classes_per_day": f.max_classes_per_day,
            "max_classes_per_week": f.max_classes_per_week,
            "max_consecutive_hours": f.max_consecutive_hours,
            "min_break_minutes": f.min_break_minutes,
            "cross_department_approved": f.cross_department_approved,
            "assigned_sessions_per_week": assigned_sessions,
            "scheduled_classes_per_week": actual_classes_week,
            "weekly_teaching_hours": weekly_hours,
            "remaining_available_workload": remaining_workload,
            "classes_per_day": days_count,
            "assignments": assignments_list,
            "status": status
        }
        faculty_records.append(record)

        # Department aggregation
        if dept_name not in dept_distribution:
            dept_distribution[dept_name] = {
                "department_name": dept_name,
                "faculty_count": 0,
                "total_weekly_classes": 0,
                "total_weekly_hours": 0.0,
                "capacity": 0
            }
        dept_distribution[dept_name]["faculty_count"] += 1
        dept_distribution[dept_name]["total_weekly_classes"] += actual_classes_week
        dept_distribution[dept_name]["total_weekly_hours"] += weekly_hours
        dept_distribution[dept_name]["capacity"] += f.max_classes_per_week

    return {
        "version_id": latest_version.id if latest_version else None,
        "version_number": latest_version.version_number if latest_version else None,
        "total_faculty": len(faculty_records),
        "faculty_workload": faculty_records,
        "department_distribution": list(dept_distribution.values())
    }


# ============================================================
# STUDENTS & ENROLMENTS
# ============================================================

@router.post("/students")
def create_student(
    data: StudentCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    values = get_values(data)
    section_id = values.pop("section_id", None)
    raw_password = values.pop("password", None)

    if raw_password:
        values["password_hash"] = hash_password(raw_password)
    else:
        values["password_hash"] = hash_password("schedulix2026")

    if not values.get("student_id"):
        values["student_id"] = generate_student_id(
            db,
            data.admission_year
        )

    values["student_id"] = values["student_id"].strip()

    # Automatically infer academic hierarchy attributes if section_id is supplied
    if section_id:
        section = db.get(Section, section_id)
        if not section:
            raise HTTPException(404, "Selected section not found")
        semester = db.get(Semester, section.semester_id)
        programme = db.get(Programme, section.programme_id)
        if programme and not values.get("programme_id"):
            values["programme_id"] = programme.id
        if programme and not values.get("department_id"):
            values["department_id"] = programme.department_id
        if semester:
            if not values.get("current_semester"):
                values["current_semester"] = semester.number
            if not values.get("current_year"):
                values["current_year"] = (semester.number + 1) // 2

    student = create_record(
        db,
        Student,
        values,
        admin,
        "Student"
    )

    # Auto-enrol in section
    if section_id:
        enr = Enrolment(student_id=student.id, section_id=section_id, active=True)
        db.add(enr)
        # update section student count
        active_count = db.query(Enrolment).filter(
            Enrolment.section_id == section_id,
            Enrolment.active.is_(True)
        ).count()
        sec_obj = db.get(Section, section_id)
        if sec_obj:
            sec_obj.student_count = max(sec_obj.student_count, active_count)
        db.commit()
        db.refresh(student)

    return student


@router.get("/students")
def students(
    programme_id: Optional[str] = None,
    semester_id: Optional[str] = None,
    section_id: Optional[str] = None,
    department_id: Optional[str] = None,
    current_year: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Student)

    if section_id:
        query = query.join(Enrolment, Enrolment.student_id == Student.id).filter(
            Enrolment.section_id == section_id,
            Enrolment.active.is_(True)
        )
    elif semester_id:
        query = query.join(Enrolment, Enrolment.student_id == Student.id).join(
            Section, Section.id == Enrolment.section_id
        ).filter(
            Section.semester_id == semester_id,
            Enrolment.active.is_(True)
        )

    if programme_id:
        query = query.filter(Student.programme_id == programme_id)
    if department_id:
        query = query.filter(Student.department_id == department_id)
    if current_year:
        query = query.filter(Student.current_year == current_year)

    records = query.order_by(Student.student_id).all()
    result = []
    for stu in records:
        dept = db.get(Department, stu.department_id) if stu.department_id else None
        prog = db.get(Programme, stu.programme_id) if stu.programme_id else None

        # Fetch active enrolment
        active_enr = db.query(Enrolment).filter(
            Enrolment.student_id == stu.id,
            Enrolment.active.is_(True)
        ).first()

        active_section = None
        active_semester = None
        if active_enr:
            active_section = db.get(Section, active_enr.section_id)
            if active_section:
                active_semester = db.get(Semester, active_section.semester_id)
                if not prog and active_section.programme_id:
                    prog = db.get(Programme, active_section.programme_id)
                if not dept and prog and prog.department_id:
                    dept = db.get(Department, prog.department_id)

        sec_ident = format_section_identity(
            active_section.name,
            prog.name if prog else None,
            prog.code if prog else None,
            active_semester.number if active_semester else None
        ) if active_section else {"section_code": "", "section_display_name": "Unenrolled"}

        result.append({
            "id": stu.id,
            "student_id": stu.student_id,
            "full_name": stu.full_name,
            "email": stu.email,
            "phone": stu.phone,
            "whatsapp_number": stu.whatsapp_number,
            "admission_year": stu.admission_year,
            "department_id": stu.department_id,
            "department_name": dept.name if dept else "Not Assigned",
            "programme_id": stu.programme_id,
            "programme_name": prog.name if prog else "Not Assigned",
            "current_year": stu.current_year or ((active_semester.number + 1) // 2 if active_semester else None),
            "current_semester": stu.current_semester or (active_semester.number if active_semester else None),
            "active": stu.active,
            "section_id": active_section.id if active_section else None,
            "section_name": active_section.name if active_section else "Unenrolled",
            "section_code": sec_ident["section_code"] if active_section else None,
            "section_display_name": sec_ident["section_display_name"] if active_section else "Unenrolled",
            "enrolment_id": active_enr.id if active_enr else None
        })
    return result


@router.put("/students/{student_id}")
def update_student(
    student_id: str,
    data: StudentUpdate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    values = data.model_dump(exclude_unset=True)
    for k, v in values.items():
        if v is not None:
            setattr(student, k, v)

    record_audit(db, "UPDATE", "Student", student.id, admin.id, values)
    db.commit()
    db.refresh(student)
    return student


@router.post("/students/{student_id}/transfer")
def transfer_student(
    student_id: str,
    data: StudentTransferRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    new_section = db.get(Section, data.new_section_id)
    if not new_section:
        raise HTTPException(404, "Target section not found")

    new_sem = db.get(Semester, new_section.semester_id)
    new_prog = db.get(Programme, new_section.programme_id)

    # Deactivate existing active enrolments
    old_section_ids = []
    existing_enrolments = db.query(Enrolment).filter(Enrolment.student_id == student.id).all()
    for enr in existing_enrolments:
        if enr.active:
            old_section_ids.append(enr.section_id)
            enr.active = False

    # Check if target enrolment already exists
    target_enr = db.query(Enrolment).filter(
        Enrolment.student_id == student.id,
        Enrolment.section_id == new_section.id
    ).first()

    if target_enr:
        target_enr.active = True
    else:
        new_enr = Enrolment(student_id=student.id, section_id=new_section.id, active=True)
        db.add(new_enr)

    # Update student academic pointers
    student.programme_id = new_section.programme_id
    if new_prog:
        student.department_id = new_prog.department_id
    if new_sem:
        student.current_semester = new_sem.number
        student.current_year = (new_sem.number + 1) // 2

    db.flush()

    # Recalculate student counts for old sections and new section
    for sec_id in set(old_section_ids + [new_section.id]):
        sec_obj = db.get(Section, sec_id)
        if sec_obj:
            active_count = db.query(Enrolment).filter(
                Enrolment.section_id == sec_id,
                Enrolment.active.is_(True)
            ).count()
            sec_obj.student_count = active_count

    record_audit(
        db, "TRANSFER", "Student", student.id, admin.id,
        {"new_section_id": new_section.id, "old_sections": old_section_ids}
    )
    db.commit()
    db.refresh(student)

    return {
        "status": "TRANSFERRED",
        "message": f"Student {student.full_name} successfully transferred to Section {new_section.name}.",
        "student_id": student.id,
        "new_section_id": new_section.id
    }


@router.get("/students/{student_id}/assignment")
def student_assignment(
    student_id: str,
    db: Session = Depends(get_db)
):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    dept = db.get(Department, student.department_id) if student.department_id else None
    prog = db.get(Programme, student.programme_id) if student.programme_id else None

    active_enr = db.query(Enrolment).filter(
        Enrolment.student_id == student.id,
        Enrolment.active.is_(True)
    ).first()

    section = None
    semester = None
    academic_year = None
    classes = []
    subjects_list = []

    if active_enr:
        section = db.get(Section, active_enr.section_id)
        if section:
            semester = db.get(Semester, section.semester_id)
            if semester:
                academic_year = db.get(AcademicYear, semester.academic_year_id)
                # Load subjects for this programme & semester
                subjects_query = db.query(Subject).filter(
                    (Subject.semester_id == semester.id) |
                    ((Subject.programme_id == semester.programme_id) & (Subject.semester_number == semester.number))
                ).all()
                subjects_list = [
                    {
                        "id": sub.id,
                        "code": sub.code,
                        "name": sub.name,
                        "session_type": sub.session_type.value if hasattr(sub.session_type, "value") else str(sub.session_type),
                        "default_duration": sub.default_duration
                    }
                    for sub in subjects_query
                ]

            # Find latest published or approved timetable version for this section
            latest_version = db.query(TimetableVersion).filter(
                TimetableVersion.status.in_([VersionStatus.PUBLISHED, VersionStatus.APPROVED, VersionStatus.DRAFT])
            ).order_by(TimetableVersion.version_number.desc()).first()

            if latest_version:
                scheduled = db.query(ScheduledClass).filter(
                    ScheduledClass.version_id == latest_version.id,
                    ScheduledClass.section_id == section.id
                ).all()

                for sc in scheduled:
                    faculty = db.get(Faculty, sc.faculty_id)
                    subject = db.get(Subject, sc.subject_id)
                    from app.models import Room
                    room = db.get(Room, sc.room_id)
                    classes.append({
                        "id": sc.id,
                        "weekday": sc.weekday,
                        "start_minute": sc.start_minute,
                        "end_minute": sc.end_minute,
                        "faculty_name": faculty.full_name if faculty else "Unknown",
                        "subject_name": subject.name if subject else "Unknown",
                        "subject_code": subject.code if subject else "",
                        "room_name": room.name if room else "Unknown"
                    })

    return {
        "student": {
            "id": student.id,
            "student_id": student.student_id,
            "full_name": student.full_name,
            "email": student.email,
            "admission_year": student.admission_year,
            "current_year": student.current_year or ((semester.number + 1) // 2 if semester else None),
            "current_semester": student.current_semester or (semester.number if semester else None)
        },
        "department": {"id": dept.id, "name": dept.name, "code": dept.code} if dept else None,
        "programme": {"id": prog.id, "name": prog.name, "code": prog.code} if prog else None,
        "semester": {"id": semester.id, "number": semester.number} if semester else None,
        "academic_year": {"id": academic_year.id, "name": academic_year.name} if academic_year else None,
        "section": {"id": section.id, "name": section.name} if section else None,
        "subjects": subjects_list,
        "timetable_classes": classes
    }


@router.delete("/students/{student_id}")
def delete_student(
    student_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    # Remove enrolments
    enrolments = db.query(Enrolment).filter(Enrolment.student_id == student_id).all()
    section_ids = [e.section_id for e in enrolments]
    for e in enrolments:
        db.delete(e)

    record_audit(db, "DELETE", "Student", student.id, admin.id, {"student_id": student.student_id, "name": student.full_name})
    db.delete(student)
    db.commit()

    # Refresh section counts
    for sec_id in set(section_ids):
        sec_obj = db.get(Section, sec_id)
        if sec_obj:
            sec_obj.student_count = db.query(Enrolment).filter(
                Enrolment.section_id == sec_id,
                Enrolment.active.is_(True)
            ).count()
    db.commit()

    return {"status": "DELETED", "message": f"Student '{student.full_name}' deleted successfully."}


# ============================================================
# FACULTY ASSIGNMENTS
# ============================================================

@router.post("/assignments")
def create_assignment(
    data: AssignmentCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    faculty_record = db.get(
        Faculty,
        data.faculty_id
    )

    subject = db.get(
        Subject,
        data.subject_id
    )

    section = db.get(
        Section,
        data.section_id
    )

    if not all((faculty_record, subject, section)):
        raise HTTPException(
            404,
            "Faculty, subject or section not found"
        )

    if not faculty_record.active:
        raise HTTPException(
            400,
            "Faculty is inactive"
        )

    # 1. Department eligibility rule:
    # A faculty member can only teach subjects belonging to their department, unless administrator explicitly approves exception.
    if subject.department_id != faculty_record.department_id and not faculty_record.cross_department_approved:
        sub_dept = db.get(Department, subject.department_id)
        fac_dept = db.get(Department, faculty_record.department_id)
        sub_dept_name = sub_dept.name if sub_dept else "External"
        fac_dept_name = fac_dept.name if fac_dept else "External"
        raise HTTPException(
            400,
            f"Teaching eligibility violation: Faculty '{faculty_record.full_name}' belongs to '{fac_dept_name}' and cannot teach subject '{subject.name}' belonging to '{sub_dept_name}' without administrator cross-department approval."
        )

    # 2. Subject qualification eligibility rule:
    # If faculty has configured qualified subjects, ensure this subject is in their qualified list.
    subject_eligibilities = db.scalars(
        select(FacultySubjectEligibility.subject_id).where(
            FacultySubjectEligibility.faculty_id == faculty_record.id
        )
    ).all()
    if subject_eligibilities and subject.id not in subject_eligibilities:
        raise HTTPException(
            400,
            f"Teaching eligibility violation: Faculty '{faculty_record.full_name}' is not qualified to teach subject '{subject.name}' ({subject.code})."
        )

    # 3. Semester / academic level eligibility rule:
    # Check section's semester. If faculty has configured eligible semesters, ensure this semester is allowed.
    semester = db.get(Semester, section.semester_id) if section.semester_id else None
    if semester:
        semester_eligibilities = db.scalars(
            select(FacultySemesterEligibility.semester_number).where(
                FacultySemesterEligibility.faculty_id == faculty_record.id
            )
        ).all()
        if semester_eligibilities and semester.number not in semester_eligibilities:
            raise HTTPException(
                400,
                f"Teaching eligibility violation: Faculty '{faculty_record.full_name}' is not eligible to teach in Semester {semester.number}."
            )

    # 4. Workload limit safety check:
    current_weekly_sessions = db.scalar(
        select(func.sum(FacultyAssignment.sessions_per_week)).where(
            FacultyAssignment.faculty_id == faculty_record.id,
            FacultyAssignment.active.is_(True)
        )
    ) or 0
    if current_weekly_sessions + data.sessions_per_week > faculty_record.max_classes_per_week:
        raise HTTPException(
            400,
            f"Faculty workload limit exceeded: Assigning {data.sessions_per_week} weekly sessions would bring total to {current_weekly_sessions + data.sessions_per_week}, which exceeds faculty member's safety limit of {faculty_record.max_classes_per_week} classes per week."
        )

    return create_record(
        db,
        FacultyAssignment,
        get_values(data),
        admin,
        "FacultyAssignment"
    )


@router.get("/assignments")
def assignments(
    db: Session = Depends(get_db)
):
    records = db.query(FacultyAssignment).all()
    result = []
    for r in records:
        faculty = db.get(Faculty, r.faculty_id)
        subject = db.get(Subject, r.subject_id)
        section = db.get(Section, r.section_id)
        prog = db.get(Programme, section.programme_id) if section else None
        dept = db.get(Department, prog.department_id) if prog else None
        sem = db.get(Semester, section.semester_id) if section else None
        sec_ident = format_section_identity(
            section.name if section else "",
            prog.name if prog else None,
            prog.code if prog else None,
            sem.number if sem else None
        ) if section else {"section_code": "", "section_display_name": "", "full_name": ""}

        result.append({
            "id": r.id,
            "faculty_id": r.faculty_id,
            "faculty_name": faculty.full_name if faculty else "Unknown",
            "faculty_code": faculty.faculty_id if faculty else "",
            "subject_id": r.subject_id,
            "subject_name": subject.name if subject else "Unknown",
            "subject_code": subject.code if subject else "",
            "section_id": r.section_id,
            "section_name": section.name if section else "",
            "section_code": sec_ident["section_code"],
            "section_display_name": sec_ident["display_name"],
            "programme_name": prog.name if prog else "",
            "department_name": dept.name if dept else "",
            "semester_number": sem.number if sem else None,
            "sessions_per_week": r.sessions_per_week,
            "duration_minutes": r.duration_minutes,
            "priority": r.priority,
            "required_capacity": r.required_capacity,
            "required_room_type": r.required_room_type.value if hasattr(r.required_room_type, "value") else str(r.required_room_type),
            "active": r.active
        })
    return result


@router.put("/assignments/{assignment_id}")
def update_assignment(
    assignment_id: str,
    data: AssignmentCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    assignment = db.get(FacultyAssignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    values = get_values(data)
    for k, v in values.items():
        setattr(assignment, k, v)

    record_audit(
        db,
        "UPDATE_ASSIGNMENT",
        "FacultyAssignment",
        assignment_id,
        admin.id,
        values
    )
    db.commit()
    db.refresh(assignment)
    return assignment


@router.patch("/assignments/{assignment_id}/toggle")
def toggle_assignment(
    assignment_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    assignment = db.get(FacultyAssignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    assignment.active = not assignment.active
    record_audit(
        db,
        "TOGGLE_ASSIGNMENT",
        "FacultyAssignment",
        assignment_id,
        admin.id,
        {"active": assignment.active}
    )
    db.commit()
    return {"id": assignment_id, "active": assignment.active}


@router.delete("/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    assignment = db.get(FacultyAssignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    db.delete(assignment)
    record_audit(
        db,
        "DELETE_ASSIGNMENT",
        "FacultyAssignment",
        assignment_id,
        admin.id,
        {"deleted": True}
    )
    db.commit()
    return {"status": "DELETED", "id": assignment_id}


@router.get("/stats")
def dashboard_stats(
    db: Session = Depends(get_db)
):
    from app.models import Room, TimetableVersion
    total_students = db.query(Student).count()
    total_faculty = db.query(Faculty).count()
    total_subjects = db.query(Subject).count()
    total_classrooms = db.query(Room).count()
    total_sections = db.query(Section).count()
    active_assignments = db.query(FacultyAssignment).filter(FacultyAssignment.active.is_(True)).count()
    total_timetables = db.query(TimetableVersion).count()
    
    # Calculate unscheduled across latest version
    latest_version = db.query(TimetableVersion).order_by(TimetableVersion.version_number.desc()).first()
    unscheduled = 0
    if latest_version and latest_version.statistics:
        unscheduled = len(latest_version.statistics.get("unscheduled", []))

    return {
        "total_students": total_students,
        "total_faculty": total_faculty,
        "total_subjects": total_subjects,
        "total_classrooms": total_classrooms,
        "total_sections": total_sections,
        "active_assignments": active_assignments,
        "total_timetables": total_timetables,
        "unscheduled_sessions": unscheduled
    }


# ============================================================
# STUDENT ENROLMENTS
# ============================================================

@router.post("/enrolments")
def enrol_student(
    student_id: str,
    section_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    student = db.get(Student, student_id)

    if not student:
        raise HTTPException(
            404,
            "Student not found"
        )

    section = db.get(Section, section_id)

    if not section:
        raise HTTPException(
            404,
            "Section not found"
        )

    existing = db.query(Enrolment).filter_by(
        student_id=student_id,
        section_id=section_id
    ).first()

    if existing:
        raise HTTPException(
            409,
            "Student is already enrolled"
        )

    enrolment = Enrolment(
        student_id=student_id,
        section_id=section_id
    )

    db.add(enrolment)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Unable to create enrolment"
        )

    return {
        "status": "ENROLLED",
        "student_id": student.student_id,
        "section_id": section_id
    }


@router.get("/enrolments")
def get_enrolments(
    section_id: Optional[str] = None,
    student_id: Optional[str] = None,
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    query = db.query(Enrolment)
    if section_id:
        query = query.filter(Enrolment.section_id == section_id)
    if student_id:
        query = query.filter(Enrolment.student_id == student_id)
    if active_only:
        query = query.filter(Enrolment.active.is_(True))
    records = query.all()
    result = []
    for enr in records:
        stu = db.get(Student, enr.student_id)
        sec = db.get(Section, enr.section_id)
        prog = db.get(Programme, sec.programme_id) if sec else None
        sem = db.get(Semester, sec.semester_id) if sec else None
        sec_ident = format_section_identity(
            sec.name if sec else "",
            prog.name if prog else None,
            prog.code if prog else None,
            sem.number if sem else None
        ) if sec else {"section_code": "", "section_display_name": "Unknown", "full_name": "Unknown"}

        result.append({
            "id": enr.id,
            "student_id": enr.student_id,
            "student_name": stu.full_name if stu else "Unknown",
            "student_code": stu.student_id if stu else "",
            "section_id": enr.section_id,
            "section_name": sec.name if sec else "Unknown",
            "section_code": sec_ident["section_code"],
            "section_display_name": sec_ident["display_name"],
            "active": enr.active
        })
    return result