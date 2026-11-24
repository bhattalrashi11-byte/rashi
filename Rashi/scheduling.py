import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import (
    TimetableVersion,
    ScheduledClass,
    VersionStatus,
    Approval,
    Section,
    Semester,
    Programme,
    Faculty,
    Student,
    Enrolment,
    TimetableImage,
    DeliveryStatus,
)
from app.schemas import (
    ScheduleRequest,
    ApprovalRequest,
    ConflictCheckRequest,
    ManualRescheduleRequest
)
from app.services.scheduler import HybridScheduler
from app.services.timetable import (
    validate_timetable,
    section_timetable,
    faculty_timetable,
    get_version_classes,
    serialise_class,
)
from app.services.academic_helper import format_section_identity
from app.services.image_generator import generate_timetable_png, sanitize
from app.services.rescheduler import Rescheduler
from app.services.email import EmailService, notify_version_subscribers
from app.concurrency import acquire_generation_semaphore
from app.tasks.jobs import generate_timetable as generate_task
from app.audit import record_audit

router = APIRouter(
    prefix="/scheduling",
    tags=["Scheduling"],
    dependencies=[Depends(get_current_admin)]
)


@router.post("/generate")
def generate(
    request: ScheduleRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    if abs(
        request.priority_weight + request.sjf_weight - 1
    ) > 0.000001:
        raise HTTPException(400, "Weights must sum to 1")

    if any(d < 0 or d > 6 for d in request.weekdays):
        raise HTTPException(400, "Invalid weekday")

    start = request.day_start.hour * 60 + request.day_start.minute
    end = request.day_end.hour * 60 + request.day_end.minute

    if end <= start:
        raise HTTPException(400, "Invalid working hours")

    # Acquire both the in-process semaphore and PostgreSQL transaction advisory lock.
    # Guarantees single-tenant critical section execution without corruption.
    with acquire_generation_semaphore(db, scope="GLOBAL", timeout_seconds=2.0):
        scheduler = HybridScheduler(
            db,
            mode=request.mode,
            priority_weight=request.priority_weight,
            sjf_weight=request.sjf_weight,
            weekdays=request.weekdays,
            day_start=start,
            day_end=end,
            time_limit=request.time_limit_seconds,
            section_id=request.section_id,
            semester_id=request.semester_id,
            programme_id=request.programme_id,
            academic_year_id=request.academic_year_id
        )

        result = scheduler.solve()

        if result["status"] not in ("OPTIMAL", "FEASIBLE"):
            return result

        latest = db.scalar(
            select(TimetableVersion.version_number)
            .order_by(TimetableVersion.version_number.desc())
            .limit(1)
        ) or 0

        version = TimetableVersion(
            version_number=latest + 1,
            status=VersionStatus.DRAFT,
            algorithm=request.mode,
            priority_weight=request.priority_weight,
            sjf_weight=request.sjf_weight,
            quality_score=result["quality_score"],
            created_by=admin.id,
            statistics=result["statistics"],
            section_id=request.section_id,
            semester_id=request.semester_id,
            programme_id=request.programme_id,
            academic_year_id=request.academic_year_id
        )

        db.add(version)
        db.flush()

        for index, item in enumerate(result["classes"]):
            db.add(
                ScheduledClass(
                    version_id=version.id,
                    assignment_id=item["assignment_id"],
                    faculty_id=item["faculty_id"],
                    section_id=item["section_id"],
                    subject_id=item["subject_id"],
                    room_id=item["room_id"],
                    weekday=item["weekday"],
                    start_minute=item["start_minute"],
                    end_minute=item["end_minute"],
                    session_number=index + 1
                )
            )

        db.flush()

        validation = validate_timetable(db, version.id)

        version.statistics = {
            **result["statistics"],
            "validation": validation,
            "unscheduled": result["unscheduled"]
        }

        record_audit(
            db,
            "TIMETABLE_GENERATED",
            "TimetableVersion",
            version.id,
            admin.id,
            version.statistics
        )

        db.commit()

        return {
            "version_id": version.id,
            "version_number": version.version_number,
            "status": version.status.value,
            "quality_score": version.quality_score,
            "solver": result["status"],
            "validation": validation,
            "unscheduled": result["unscheduled"],
            "statistics": version.statistics
        }


@router.post("/generate-async")
def generate_async(
    request: ScheduleRequest,
    admin=Depends(get_current_admin)
):
    if abs(
        request.priority_weight + request.sjf_weight - 1
    ) > 0.000001:
        raise HTTPException(400, "Weights must sum to 1")

    start = request.day_start.hour * 60 + request.day_start.minute
    end = request.day_end.hour * 60 + request.day_end.minute

    if end <= start:
        raise HTTPException(400, "Invalid working hours")

    task = generate_task.delay({
        "mode": request.mode,
        "priority_weight": request.priority_weight,
        "sjf_weight": request.sjf_weight,
        "weekdays": request.weekdays,
        "day_start": start,
        "day_end": end,
        "time_limit": request.time_limit_seconds,
        "section_id": request.section_id,
        "semester_id": request.semester_id,
        "programme_id": request.programme_id,
        "academic_year_id": request.academic_year_id,
        "admin_id": admin.id,
    })

    return {
        "task_id": task.id,
        "status": "QUEUED"
    }


@router.get("/task/{task_id}")
def task_status(
    task_id: str,
    admin=Depends(get_current_admin)
):
    from app.tasks.celery_app import celery

    result = celery.AsyncResult(task_id)

    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None
    }


@router.get("/versions")
def versions(
    section_id: str | None = None,
    semester_id: str | None = None,
    programme_id: str | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(TimetableVersion)
    if section_id:
        query = query.filter(TimetableVersion.section_id == section_id)
    if semester_id:
        query = query.filter(TimetableVersion.semester_id == semester_id)
    if programme_id:
        query = query.filter(TimetableVersion.programme_id == programme_id)

    records = query.order_by(TimetableVersion.version_number.desc()).all()
    result = []
    for v in records:
        sec = db.get(Section, v.section_id) if v.section_id else None
        sem = db.get(Semester, v.semester_id) if v.semester_id else (db.get(Semester, sec.semester_id) if sec else None)
        prog = db.get(Programme, v.programme_id) if v.programme_id else (db.get(Programme, sec.programme_id) if sec else None)
        sec_ident = format_section_identity(
            sec.name if sec else "",
            prog.name if prog else None,
            prog.code if prog else None,
            sem.number if sem else None
        ) if sec else {"section_code": "ALL", "section_display_name": "All Sections"}

        result.append({
            "id": v.id,
            "version_number": v.version_number,
            "status": v.status.value if hasattr(v.status, "value") else str(v.status),
            "algorithm": v.algorithm,
            "priority_weight": v.priority_weight,
            "sjf_weight": v.sjf_weight,
            "quality_score": v.quality_score,
            "statistics": v.statistics,
            "created_by": v.created_by,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "published_at": v.published_at.isoformat() if v.published_at else None,
            "section_id": v.section_id,
            "section_name": sec.name if sec else "All Sections",
            "section_code": sec_ident["section_code"] if sec else "ALL",
            "section_display_name": sec_ident["section_display_name"] if sec else "All Sections",
            "semester_id": v.semester_id or (sem.id if sem else None),
            "semester_number": sem.number if sem else None,
            "programme_id": v.programme_id or (prog.id if prog else None),
            "programme_name": prog.name if prog else "All Programmes"
        })
    return result


@router.get("/versions/{version_id}")
def version_details(
    version_id: str,
    db: Session = Depends(get_db)
):
    version = db.get(TimetableVersion, version_id)

    if not version:
        raise HTTPException(404, "Version not found")

    raw_classes = get_version_classes(db, version_id)
    classes = [serialise_class(db, item) for item in raw_classes]

    return {
        "version": version,
        "scheduled_classes": classes,
        "validation": validate_timetable(db, version_id)
    }


@router.get("/versions/{version_id}/section/{section_id}")
def section_schedule(
    version_id: str,
    section_id: str,
    db: Session = Depends(get_db)
):
    return section_timetable(db, version_id, section_id)


@router.get("/versions/{version_id}/faculty/{faculty_id}")
def faculty_schedule(
    version_id: str,
    faculty_id: str,
    db: Session = Depends(get_db)
):
    return faculty_timetable(db, version_id, faculty_id)


@router.post("/versions/{version_id}/approve")
def approve(
    version_id: str,
    data: ApprovalRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    version = db.execute(
        select(TimetableVersion)
        .where(TimetableVersion.id == version_id)
        .with_for_update()
    ).scalar_one_or_none()

    if not version:
        raise HTTPException(404, "Version not found")

    if version.status != VersionStatus.DRAFT:
        raise HTTPException(409, "Version is not a draft")

    validation = validate_timetable(db, version_id)

    if not validation["valid"]:
        raise HTTPException(409, detail=validation)

    if version.statistics.get("unscheduled"):
        raise HTTPException(
            409,
            "Cannot approve a timetable with unscheduled classes"
        )

    version.status = VersionStatus.APPROVED
    version.approved_by = admin.id

    db.add(
        Approval(
            version_id=version_id,
            admin_id=admin.id,
            decision="APPROVED",
            comments=data.comments
        )
    )

    record_audit(
        db, "TIMETABLE_APPROVED",
        "TimetableVersion", version_id, admin.id
    )

    db.commit()

    return {"status": "APPROVED"}


@router.post("/versions/{version_id}/publish")
def publish(
    version_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    version = db.execute(
        select(TimetableVersion)
        .where(TimetableVersion.id == version_id)
        .with_for_update()
    ).scalar_one_or_none()

    if not version:
        raise HTTPException(404, "Version not found")

    if version.status != VersionStatus.APPROVED:
        raise HTTPException(
            409, "Only approved versions can be published"
        )

    validation = validate_timetable(db, version_id)

    if not validation["valid"]:
        raise HTTPException(409, detail=validation)

    # Lock publication changes in one transaction.
    # If this version is for a specific section, only supersede previous published versions
    # for that section. If university-wide, supersede all previously published versions.
    query = select(TimetableVersion).where(TimetableVersion.status == VersionStatus.PUBLISHED)
    if version.section_id:
        query = query.where(TimetableVersion.section_id == version.section_id)

    previous = db.scalars(query.with_for_update()).all()

    for old in previous:
        old.status = VersionStatus.SUPERSEDED

    version.status = VersionStatus.PUBLISHED
    version.published_at = datetime.utcnow()

    record_audit(
        db,
        "TIMETABLE_PUBLISHED",
        "TimetableVersion",
        version_id,
        admin.id
    )

    db.commit()

    return {
        "status": "PUBLISHED",
        "version_id": version_id
    }


@router.post("/versions/{version_id}/reschedule")
def reschedule(
    version_id: str,
    reason: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    try:
        result = Rescheduler(db).create_proposal(
            version_id,
            reason,
            admin.id
        )

        db.commit()
        return result

    except Exception:
        db.rollback()
        raise


@router.post("/versions/{version_id}/images")
def generate_images(
    version_id: str,
    db: Session = Depends(get_db)
):
    version = db.get(TimetableVersion, version_id)

    if not version:
        raise HTTPException(404, "Version not found")

    if version.status not in (
        VersionStatus.DRAFT,
        VersionStatus.APPROVED,
        VersionStatus.PUBLISHED
    ):
        raise HTTPException(409, "Version must be approved first")

    output = []

    sections = db.scalars(
        select(Section).distinct()
        .join(ScheduledClass,
              ScheduledClass.section_id == Section.id)
        .where(ScheduledClass.version_id == version_id)
    ).all()

    faculty = db.scalars(
        select(Faculty).distinct()
        .join(ScheduledClass,
              ScheduledClass.faculty_id == Faculty.id)
        .where(ScheduledClass.version_id == version_id)
    ).all()

    try:
        for section in sections:
            image = generate_timetable_png(
                db, version_id, "STUDENT", section.id
            )
            output.append({
                "recipient_type": "STUDENT",
                "recipient_id": section.id,
                "image_id": image.id
            })

        for teacher in faculty:
            image = generate_timetable_png(
                db, version_id, "FACULTY", teacher.id
            )
            output.append({
                "recipient_type": "FACULTY",
                "recipient_id": teacher.id,
                "image_id": image.id
            })

        db.commit()

    except Exception:
        db.rollback()
        raise

    return {
        "generated": len(output),
        "images": output
    }


@router.post("/versions/{version_id}/notify")
def notify(
    version_id: str,
    db: Session = Depends(get_db)
):
    version = db.get(TimetableVersion, version_id)

    if not version or version.status != VersionStatus.PUBLISHED:
        raise HTTPException(409, "Version must be published")

    service = WhatsAppService()

    if not service.enabled:
        return {
            "status": "NOT_CONFIGURED",
            "message": "WhatsApp Cloud API credentials are missing"
        }

    images = db.scalars(
        select(TimetableImage).where(
            TimetableImage.version_id == version_id
        )
    ).all()

    queued = []

    for image in images:

        if image.recipient_type == "STUDENT":
            recipients = db.scalars(
                select(Student)
                .join(Enrolment)
                .where(
                    Enrolment.section_id == image.recipient_id,
                    Enrolment.active.is_(True),
                    Student.active.is_(True),
                    Student.whatsapp_consent.is_(True)
                )
            ).all()

        else:
            recipients = db.scalars(
                select(Faculty).where(
                    Faculty.id == image.recipient_id,
                    Faculty.active.is_(True),
                    Faculty.whatsapp_consent.is_(True)
                )
            ).all()

        for person in recipients:
            phone = person.whatsapp_number

            if not phone:
                continue

            from app.tasks.jobs import deliver_notification

            notification = WhatsAppNotification(
                image_id=image.id,
                recipient_type=image.recipient_type,
                recipient_id=person.id,
                phone_number=phone,
                status=DeliveryStatus.QUEUED
            )

            db.add(notification)
            db.flush()

            queued.append(notification.id)

    db.commit()

    for notification_id in queued:
        deliver_notification.delay(notification_id)

    return {
        "status": "QUEUED",
        "recipient_count": len(queued)
    }


# ============================================================================
# MANUAL RESCHEDULING & CONFLICT CHECKING (SECTION 9)
# ============================================================================

@router.post("/check-conflict")
def check_rescheduling_conflict(
    request: ConflictCheckRequest,
    db: Session = Depends(get_db)
):
    """
    Dry-run clash detection before saving a rescheduling change.
    Checks faculty availability/clashes, room availability/clashes/capacity,
    section clashes, and operating hours.
    """
    rescheduler = Rescheduler(db)
    return rescheduler.check_conflicts(
        version_id=request.version_id,
        class_id=request.class_id,
        new_weekday=request.new_weekday,
        new_start_minute=request.new_start_minute,
        new_end_minute=request.new_end_minute,
        new_room_id=request.new_room_id,
        new_faculty_id=request.new_faculty_id
    )


@router.post("/versions/{version_id}/manual-reschedule")
def manual_reschedule(
    version_id: str,
    request: ManualRescheduleRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """
    Manually moves a selected session to an alternative slot in a safe ACID transaction.
    If valid, creates a new timetable version to preserve recoverable history.
    If clashes exist, rejects the change with detailed explanation.
    """
    rescheduler = Rescheduler(db)
    try:
        return rescheduler.manual_reschedule(
            version_id=version_id,
            class_id=request.class_id,
            new_weekday=request.new_weekday,
            new_start_minute=request.new_start_minute,
            new_end_minute=request.new_end_minute,
            new_room_id=request.new_room_id,
            new_faculty_id=request.new_faculty_id,
            reason=request.reason,
            admin_id=admin.id
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


# ============================================================================
# PNG TIMETABLE DOWNLOAD & RETRIEVAL (SECTION 10)
# ============================================================================

@router.get("/versions/{version_id}/section/{section_id}/download")
def download_section_timetable(
    version_id: str,
    section_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """
    Direct authenticated download of high-resolution section timetable PNG.
    Generates image if not present, and serves with descriptive filename.
    """
    version = db.get(TimetableVersion, version_id)
    if not version:
        raise HTTPException(404, "Timetable version not found")

    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(404, "Section not found")

    class_count = db.scalar(
        select(func.count(ScheduledClass.id)).where(
            ScheduledClass.version_id == version_id,
            ScheduledClass.section_id == section_id
        )
    ) or 0

    if class_count == 0:
        raise HTTPException(
            400,
            f"No classes scheduled for Section '{section.name}' in Timetable Version {version.version_number}. Please generate a timetable first."
        )

    # Generate or refresh PNG
    img = generate_timetable_png(db, version_id, "STUDENT", section_id)
    db.commit()

    if not img or not os.path.exists(img.file_path):
        raise HTTPException(500, "Timetable image file could not be generated on disk")

    sem = db.get(Semester, section.semester_id) if section.semester_id else None
    prog = db.get(Programme, section.programme_id) if section.programme_id else None
    prog_code = sanitize(prog.code) if prog else "UG"
    sem_num = sem.number if sem else 1
    sec_name = sanitize(section.name)

    download_filename = f"Timetable_{prog_code}_Sem{sem_num}_Sec{sec_name}.png"

    return FileResponse(
        img.file_path,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'},
        filename=download_filename
    )


@router.get("/images/{image_id}/download")
def download_image(
    image_id: str,
    db: Session = Depends(get_db)
):
    """
    Serves the generated PNG timetable file for download.
    """
    img = db.get(TimetableImage, image_id)
    if not img or not os.path.exists(img.file_path):
        raise HTTPException(404, "Timetable image file not found")

    filename = os.path.basename(img.file_path)
    return FileResponse(
        img.file_path,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        filename=filename
    )


@router.get("/versions/{version_id}/images-list")
def list_version_images(
    version_id: str,
    db: Session = Depends(get_db)
):
    """
    Returns the list of generated PNG timetables for the version with download URLs.
    """
    images = db.scalars(
        select(TimetableImage).where(TimetableImage.version_id == version_id)
    ).all()

    return [
        {
            "id": img.id,
            "version_id": img.version_id,
            "recipient_type": img.recipient_type,
            "recipient_id": img.recipient_id,
            "file_path": img.file_path,
            "filename": os.path.basename(img.file_path),
            "download_url": f"/scheduling/images/{img.id}/download",
            "created_at": img.created_at.isoformat() if img.created_at else None
        }
        for img in images
    ]
