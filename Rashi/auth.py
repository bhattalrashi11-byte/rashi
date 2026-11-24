from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Admin, Student, Faculty
from app.schemas import LoginRequest, TokenResponse, StudentLoginRequest, FacultyLoginRequest
from app.security import (
    verify_password,
    create_access_token,
    hash_password,
)
from app.audit import record_audit
from app.dependencies import get_current_admin, get_current_student, get_current_faculty

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(Admin).filter(
        Admin.username == data.username
    ).first()

    if (
        not admin
        or not admin.active
        or not verify_password(data.password, admin.password_hash)
    ):
        raise HTTPException(401, "Invalid credentials")

    record_audit(
        db,
        "ADMIN_LOGIN",
        "Admin",
        admin.id,
        admin.id,
        {"username": admin.username, "method": "json"}
    )
    db.commit()

    return TokenResponse(
        access_token=create_access_token(admin.id, role="ADMIN"),
        role="ADMIN"
    )


@router.post("/token", response_model=TokenResponse)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    admin = db.query(Admin).filter(
        Admin.username == form_data.username
    ).first()

    if (
        not admin
        or not admin.active
        or not verify_password(form_data.password, admin.password_hash)
    ):
        raise HTTPException(401, "Invalid credentials")

    record_audit(
        db,
        "ADMIN_LOGIN",
        "Admin",
        admin.id,
        admin.id,
        {"username": admin.username, "method": "oauth2_form"}
    )
    db.commit()

    return TokenResponse(
        access_token=create_access_token(admin.id, role="ADMIN"),
        role="ADMIN"
    )


@router.post("/student-login", response_model=TokenResponse)
def student_login(
    data: StudentLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Dedicated secure student login endpoint.
    Authenticates by student_id or email, returning a JWT with role 'STUDENT'.
    """
    ident = data.identifier.strip()
    student = db.query(Student).filter(
        (Student.student_id == ident) | (Student.email == ident.lower())
    ).first()

    if not student or not student.active:
        raise HTTPException(401, "Invalid student ID / email or account inactive")

    # If student has a password_hash, verify it.
    # If no password_hash was set yet, allow default initial password ('schedulix2026' or their student_id)
    valid_password = False
    if student.password_hash:
        valid_password = verify_password(data.password, student.password_hash)
    else:
        # Default fallback initial credentials
        if data.password in ("schedulix2026", student.student_id, "student123"):
            student.password_hash = hash_password(data.password)
            db.commit()
            valid_password = True

    if not valid_password:
        raise HTTPException(401, "Invalid student credentials")

    record_audit(
        db,
        "STUDENT_LOGIN",
        "Student",
        student.id,
        None,
        {"student_id": student.student_id, "email": student.email}
    )
    db.commit()

    return TokenResponse(
        access_token=create_access_token(student.id, role="STUDENT"),
        role="STUDENT"
    )


@router.get("/me")
def me(admin=Depends(get_current_admin)):
    return {
        "id": admin.id,
        "username": admin.username,
        "email": admin.email,
        "role": "ADMIN"
    }


@router.get("/student-me")
def student_me(student=Depends(get_current_student)):
    return {
        "id": student.id,
        "student_id": student.student_id,
        "full_name": student.full_name,
        "email": student.email,
        "role": "STUDENT"
    }


@router.post("/faculty-login", response_model=TokenResponse)
def faculty_login(
    data: FacultyLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Dedicated secure faculty login endpoint.
    Authenticates by faculty_id or email, returning a JWT with role 'FACULTY'.
    """
    ident = data.identifier.strip()
    faculty = db.query(Faculty).filter(
        (Faculty.faculty_id == ident) | (Faculty.email == ident.lower())
    ).first()

    if not faculty or not faculty.active:
        raise HTTPException(401, "Invalid faculty ID / email or account inactive")

    valid_password = False
    if faculty.password_hash:
        valid_password = verify_password(data.password, faculty.password_hash)
    else:
        # Default fallback initial credentials for existing faculty
        if data.password in ("schedulix2026", faculty.faculty_id, "faculty123"):
            faculty.password_hash = hash_password(data.password)
            db.commit()
            valid_password = True

    if not valid_password:
        raise HTTPException(401, "Invalid faculty credentials")

    record_audit(
        db,
        "FACULTY_LOGIN",
        "Faculty",
        faculty.id,
        None,
        {"faculty_id": faculty.faculty_id, "email": faculty.email}
    )
    db.commit()

    return TokenResponse(
        access_token=create_access_token(faculty.id, role="FACULTY"),
        role="FACULTY"
    )


@router.get("/faculty-me")
def faculty_me(faculty=Depends(get_current_faculty)):
    return {
        "id": faculty.id,
        "faculty_id": faculty.faculty_id,
        "full_name": faculty.full_name,
        "email": faculty.email,
        "department_id": faculty.department_id,
        "designation": faculty.designation,
        "role": "FACULTY"
    }
