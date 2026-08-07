from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LocationSample(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=10_000)
    captured_at: datetime

class ClockInRequest(BaseModel):
    membership_id: UUID
    office_location_id: UUID
    location: LocationSample

class ClockInResponse(BaseModel):
    session_id: UUID
    status: str
    clocked_in_at: datetime
    distance_m: float

class ClockOutRequest(BaseModel):
    membership_id: UUID
    office_location_id: UUID
    location: LocationSample

class ClockOutResponse(BaseModel):
    session_id: UUID
    status: str
    clocked_in_at: datetime
    clocked_out_at: datetime
    distance_m: float
    duration_minutes: float

class ActiveSessionResponse(BaseModel):
    session_id: UUID
    organization_id: UUID
    user_id: UUID
    office_location_id: UUID
    clocked_in_at: datetime

class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8)

class UserResponse(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)

class MembershipRequest(BaseModel):
    organization_id: UUID

class MembershipResponse(BaseModel):
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: str
    approval_status: str
    
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"