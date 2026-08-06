from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LocationSample(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=10_000)
    captured_at: datetime


class ClockInRequest(BaseModel):
    staff_member_id: UUID
    office_location_id: UUID
    location: LocationSample


class ClockInResponse(BaseModel):
    session_id: UUID
    status: str
    clocked_in_at: datetime
    distance_m: float
