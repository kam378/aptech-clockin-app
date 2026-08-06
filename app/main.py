from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.geofence import distance_metres
from app.models import AttendanceSession, OfficeLocation, Organization, StaffMember
from app.schemas import ClockInRequest, ClockInResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Clock-In API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/development/seed")
def seed_development_data(db: Session = Depends(get_db)) -> dict[str, str]:
    """Create a Lagos demo organization, office, and staff member once."""
    if get_settings().app_env != "development":
        raise HTTPException(status_code=404, detail="Not found")

    staff = db.scalar(select(StaffMember).where(StaffMember.email == "ada@example.com"))
    if staff is None:
        organization = Organization(name="Demo Organization")
        db.add(organization)
        db.flush()
        office = OfficeLocation(
            organization_id=organization.id,
            name="Lagos Office",
            latitude=6.5244,
            longitude=3.3792,
            radius_m=150,
            max_accuracy_m=50,
        )
        staff = StaffMember(organization_id=organization.id, name="Ada Okafor", email="ada@example.com")
        db.add_all([office, staff])
        db.commit()
        db.refresh(office)
        db.refresh(staff)
    else:
        office = db.scalar(select(OfficeLocation).where(OfficeLocation.organization_id == staff.organization_id))

    return {"staff_member_id": str(staff.id), "office_location_id": str(office.id)}


@app.post("/api/v1/attendance/clock-in", response_model=ClockInResponse, status_code=status.HTTP_201_CREATED)
def clock_in(payload: ClockInRequest, db: Session = Depends(get_db)) -> ClockInResponse:
    staff = db.get(StaffMember, payload.staff_member_id)
    office = db.get(OfficeLocation, payload.office_location_id)
    if staff is None or office is None or staff.organization_id != office.organization_id:
        raise HTTPException(status_code=404, detail={"code": "OFFICE_OR_STAFF_NOT_FOUND"})

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
        select(AttendanceSession).where(AttendanceSession.staff_member_id == staff.id, AttendanceSession.clocked_out_at.is_(None))
    )
    if open_session:
        raise HTTPException(status_code=409, detail={"code": "OPEN_SESSION_EXISTS", "session_id": str(open_session.id)})

    session = AttendanceSession(staff_member_id=staff.id, office_location_id=office.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return ClockInResponse(session_id=session.id, status="clocked_in", clocked_in_at=session.clocked_in_at, distance_m=round(distance_m, 2))
