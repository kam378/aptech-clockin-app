from contextlib import asynccontextmanager
from datetime import datetime, timezone

from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.geofence import distance_metres
from app.models import AttendanceSession, OfficeLocation, Organization, OrganizationMembership, User
from app.schemas import (
    ActiveSessionResponse,
    ClockInRequest,
    ClockInResponse,
    ClockOutRequest,
    ClockOutResponse,
    LoginRequest,
    TokenResponse,
)
from app.security import create_access_token, hash_password, verify_password
from app.dependencies import get_current_user
from sqlalchemy.exc import IntegrityError


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


import traceback
from fastapi.responses import JSONResponse

app = FastAPI(title="Clock-In API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def debug_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "traceback": traceback.format_exc().splitlines()},
    )



@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))

    invalid_credentials = HTTPException(status_code=401, detail={"code": "INVALID_CREDENTIALS"})

    if user is None or user.password_hash is None:
        raise invalid_credentials
    if not verify_password(payload.password, user.password_hash):
        raise invalid_credentials
    if not user.is_active:
        raise HTTPException(status_code=403, detail={"code": "USER_INACTIVE"})

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@app.post("/development/seed")
def seed_development_data(db: Session = Depends(get_db)) -> dict[str, str]:
    """Create an approved Lagos admin, organization, and office once."""
    if get_settings().app_env != "development":
        raise HTTPException(status_code=404, detail="Not found")

    organization = db.scalar(select(Organization).where(Organization.name == "Demo Organization"))
    if organization is None:
        organization = Organization(name="Demo Organization")
        db.add(organization)
        db.flush()

    office = db.scalar(select(OfficeLocation).where(OfficeLocation.organization_id == organization.id))
    if office is None:
        office = OfficeLocation(
            organization_id=organization.id,
            name="Lagos Office",
            latitude=6.5244,
            longitude=3.3792,
            radius_m=150,
            max_accuracy_m=50,
        )
        db.add(office)
        db.flush()

    user = db.scalar(select(User).where(User.email == "ada@example.com"))
    if user is None:
        user = User(full_name="Ada Okafor", email="ada@example.com", password_hash=hash_password("password123"))
        db.add(user)
        db.flush()

    membership = db.scalar(select(OrganizationMembership).where(OrganizationMembership.user_id == user.id))
    if membership is None:
        membership = OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            role="admin",
            approval_status="active",
            joined_at=datetime.now(timezone.utc),
        )
        db.add(membership)

    db.commit()
    db.refresh(office)
    db.refresh(membership)

    return {"membership_id": str(membership.id), "office_location_id": str(office.id)}

def get_owned_membership_and_office(
    db: Session, current_user: User, membership_id, office_location_id
) -> tuple[OrganizationMembership, OfficeLocation]:
    membership = db.get(OrganizationMembership, membership_id)
    office = db.get(OfficeLocation, office_location_id)
    if membership is None or office is None or membership.organization_id != office.organization_id:
        raise HTTPException(status_code=404, detail={"code": "OFFICE_OR_MEMBERSHIP_NOT_FOUND"})
    if membership.user_id != current_user.id:
        raise HTTPException(status_code=404, detail={"code": "OFFICE_OR_MEMBERSHIP_NOT_FOUND"})
    if membership.approval_status != "active":
        raise HTTPException(status_code=403, detail={"code": "MEMBERSHIP_NOT_APPROVED"})
    return membership, office


@app.post("/api/v1/attendance/clock-in", response_model=ClockInResponse, status_code=status.HTTP_201_CREATED)
def clock_in(
    payload: ClockInRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClockInResponse:
    membership, office = get_owned_membership_and_office(
        db, current_user, payload.membership_id, payload.office_location_id
    )

    now = datetime.now(timezone.utc)
    captured_at = payload.location.captured_at
    if captured_at.tzinfo is None:
        raise HTTPException(status_code=422, detail={"code": "LOCATION_TIMESTAMP_TIMEZONE_REQUIRED"})
    if (now - captured_at.astimezone(timezone.utc)).total_seconds() > 60:
        raise HTTPException(status_code=422, detail={"code": "LOCATION_TOO_OLD"})
    if payload.location.accuracy_m > office.max_accuracy_m:
        raise HTTPException(status_code=422, detail={"code": "LOCATION_ACCURACY_TOO_LOW"})

    distance_m = distance_metres(office.latitude, office.longitude, payload.location.latitude, payload.location.longitude)
    if distance_m + payload.location.accuracy_m > office.radius_m:
        raise HTTPException(
            status_code=422,
            detail={"code": "OUTSIDE_GEOFENCE", "distance_m": round(distance_m, 2), "allowed_radius_m": office.radius_m},
        )

    open_session = db.scalar(
        select(AttendanceSession).where(AttendanceSession.user_id == membership.user_id, AttendanceSession.clocked_out_at.is_(None))
    )
    if open_session:
        raise HTTPException(status_code=409, detail={"code": "OPEN_SESSION_EXISTS", "session_id": str(open_session.id)})

    session = AttendanceSession(
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        office_location_id=office.id,
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "OPEN_SESSION_EXISTS"})
    db.refresh(session)
    return ClockInResponse(session_id=session.id, status="clocked_in", clocked_in_at=session.clocked_in_at, distance_m=round(distance_m, 2))


@app.get("/api/v1/attendance/active-session", response_model=ActiveSessionResponse)
def get_active_session(
    membership_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActiveSessionResponse:
    membership = db.get(OrganizationMembership, membership_id)
    if membership is None or membership.user_id != current_user.id:
        raise HTTPException(status_code=404, detail={"code": "MEMBERSHIP_NOT_FOUND"})

    session = db.scalar(
        select(AttendanceSession).where(
            AttendanceSession.user_id == membership.user_id,
            AttendanceSession.clocked_out_at.is_(None),
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "NO_ACTIVE_SESSION"})

    return ActiveSessionResponse(
        session_id=session.id,
        organization_id=session.organization_id,
        user_id=session.user_id,
        office_location_id=session.office_location_id,
        clocked_in_at=session.clocked_in_at,
    )


@app.post("/api/v1/attendance/clock-out", response_model=ClockOutResponse)
def clock_out(
    payload: ClockOutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClockOutResponse:
    membership, office = get_owned_membership_and_office(
        db, current_user, payload.membership_id, payload.office_location_id
    )

    session = db.scalar(
        select(AttendanceSession).where(
            AttendanceSession.user_id == membership.user_id,
            AttendanceSession.clocked_out_at.is_(None),
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "NO_ACTIVE_SESSION"})

    now = datetime.now(timezone.utc)
    captured_at = payload.location.captured_at
    if captured_at.tzinfo is None:
        raise HTTPException(status_code=422, detail={"code": "LOCATION_TIMESTAMP_TIMEZONE_REQUIRED"})
    if (now - captured_at.astimezone(timezone.utc)).total_seconds() > 60:
        raise HTTPException(status_code=422, detail={"code": "LOCATION_TOO_OLD"})
    if payload.location.accuracy_m > office.max_accuracy_m:
        raise HTTPException(status_code=422, detail={"code": "LOCATION_ACCURACY_TOO_LOW"})

    distance_m = distance_metres(office.latitude, office.longitude, payload.location.latitude, payload.location.longitude)
    if distance_m + payload.location.accuracy_m > office.radius_m:
        raise HTTPException(
            status_code=422,
            detail={"code": "OUTSIDE_GEOFENCE", "distance_m": round(distance_m, 2), "allowed_radius_m": office.radius_m},
        )

    session.clocked_out_at = now
    db.commit()
    db.refresh(session)

    clocked_in_dt = session.clocked_in_at
    if clocked_in_dt.tzinfo is None:
        clocked_in_dt = clocked_in_dt.replace(tzinfo=timezone.utc)

    duration_minutes = round((now - clocked_in_dt).total_seconds() / 60.0, 2)

    return ClockOutResponse(
        session_id=session.id,
        status="clocked_out",
        clocked_in_at=session.clocked_in_at,
        clocked_out_at=session.clocked_out_at,
        distance_m=round(distance_m, 2),
        duration_minutes=duration_minutes,
    )

