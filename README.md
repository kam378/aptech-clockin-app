# Location-Based Clock-In Backend

## Purpose

This backend lets authenticated staff clock in and out from a mobile or web app only when they are physically close enough to an approved organization location. It uses FastAPI for the API layer and validates every attendance action on the server.

Location is used only at the moment a staff member requests an attendance action. Do not make continuous background tracking a requirement for the first release.

## Run the Current Starter API

1. Start PostgreSQL:

   ```powershell
   docker compose up -d
   ```

2. Create the local environment file from `.env.example` and set a non-default local database password if desired.

3. Activate the virtual environment and start FastAPI:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   uvicorn app.main:app --reload
   ```

4. Open `http://127.0.0.1:8000/docs`. The starter exposes `GET /health`, `POST /development/seed`, and `POST /api/v1/attendance/clock-in`.

Call `POST /development/seed` first. It returns the demo membership and office IDs needed for a clock-in request. The demo office is at latitude `6.5244`, longitude `3.3792`, with a 150-metre radius. Submit a fresh timestamp in `location.captured_at` and an accuracy no worse than 50 metres.

This is a development milestone, not a deployable authentication system. The clock-in request temporarily accepts `membership_id` in its JSON body so the geofence can be tested. Replace it with the authenticated user and active membership from a JWT before exposing the API outside local development.

## How It Works

1. An administrator creates an organization office location, with latitude, longitude, and an allowed radius in metres.
2. A staff member signs in on the phone app and grants foreground location permission.
3. The app obtains a recent GPS location sample and calls the clock-in endpoint with that sample.
4. The API authenticates the user, confirms they belong to the organization, calculates their distance from the office, and checks the allowed radius and GPS accuracy.
5. If valid, the API stores an immutable attendance event and returns the active attendance session.
6. Clock-out follows the same flow. The organization can choose whether clock-out also requires being inside the geofence.

The client can warn the user before submitting when they are outside the geofence, but the backend must always perform the final validation. Client-only checks can be bypassed.

## Recommended Stack

- **API:** FastAPI, Pydantic v2, Uvicorn
- **Database:** PostgreSQL
- **ORM/migrations:** SQLAlchemy 2.0 and Alembic
- **Authentication:** OAuth2 password/login flow with short-lived JWT access tokens and refresh tokens
- **Password hashing:** Argon2 or bcrypt via `pwdlib`/`passlib`
- **Background work:** Celery, RQ, or FastAPI background tasks for exports and notifications
- **Observability:** structured logs, Sentry, and metrics such as Prometheus/OpenTelemetry

PostgreSQL with PostGIS is useful when an organization has many sites or needs reporting by geography. For a small first version, latitude/longitude columns plus a Haversine distance calculation are sufficient.

## Core Features

### Staff attendance

- Sign in and securely refresh an expired session.
- Clock in, clock out, and view the current open attendance session.
- See personal attendance history, including server-recorded time and office name.
- Explain rejected requests: outside permitted area, location too inaccurate, location sample too old, duplicate clock-in, or insufficient permission.
- Submit optional notes, such as a reason for late arrival.

### Location and office management

- Create, update, enable, or archive office locations.
- Store an office name, address, latitude, longitude, radius, timezone, and permitted attendance rules.
- Support multiple branches per organization.
- Configure a default office or let staff select from assigned offices.
- Set a maximum accepted GPS accuracy, for example 50 metres, and a maximum location age, for example 60 seconds.

### Administrator and manager tools

- Invite/deactivate staff and assign roles: `staff`, `manager`, `admin`.
- Assign staff to one or more office locations.
- View daily attendance and late/absent status in the organization timezone.
- Correct attendance with a required reason and an audit record; never silently overwrite original events.
- Approve or reject manual attendance requests when a location check failed for a legitimate reason.
- Export attendance reports as CSV/XLSX.

### Scheduling (next phase)

- Work schedules, shift templates, grace periods, holidays, and leave.
- Compare actual clock-in time with the planned shift.
- Remote-work and off-site assignment approvals, which bypass or use a different geofence.
- Notifications for missed clock-out or late arrival.

## Data Model

Use UTC timestamps in the database. Convert to an office timezone only for display and reporting.

| Table | Important fields | Notes |
| --- | --- | --- |
| `organizations` | `id`, `name`, `status` | Tenant boundary for all organization data. |
| `users` | `id`, `email`, `password_hash`, `is_active` | Authentication identity. |
| `organization_memberships` | `organization_id`, `user_id`, `role` | A user may belong to more than one organization. |
| `office_locations` | `id`, `organization_id`, `name`, `latitude`, `longitude`, `radius_m`, `timezone`, `max_accuracy_m`, `is_active` | The configured geofence. |
| `staff_office_assignments` | `user_id`, `office_location_id` | Limits staff to approved offices. |
| `attendance_sessions` | `id`, `organization_id`, `user_id`, `clock_in_at`, `clock_out_at`, `clock_in_event_id`, `clock_out_event_id`, `status` | Convenient read model for an open or completed work session. |
| `attendance_events` | `id`, `session_id`, `event_type`, `occurred_at`, `received_at`, `latitude`, `longitude`, `accuracy_m`, `distance_m`, `office_location_id`, `decision`, `reason_code`, `device_id` | Append-only evidence and audit trail. |
| `attendance_corrections` | `id`, `session_id`, `requested_by`, `approved_by`, `reason`, `before`, `after` | Keeps edits accountable. |
| `audit_logs` | `id`, `actor_id`, `action`, `entity_type`, `entity_id`, `metadata`, `created_at` | Tracks administrative activity. |

Encrypt sensitive location data at rest where possible. Apply a documented retention policy; for example, retain precise location evidence for 90 days, then keep only the attendance result and office identifier if legally appropriate for the organization.

## API Design

Prefix endpoints with `/api/v1` and use JSON. All non-auth endpoints require `Authorization: Bearer <access-token>`.

| Method | Endpoint | Access | Purpose |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | Public | Authenticate and return access/refresh tokens. |
| `POST` | `/auth/refresh` | Public | Exchange a refresh token for a new access token. |
| `GET` | `/me` | Authenticated | Return current user and memberships. |
| `GET` | `/offices/nearby` | Staff | List offices assigned to the user, optionally ordered by supplied position. |
| `POST` | `/attendance/clock-in` | Staff | Validate location and start a session. |
| `POST` | `/attendance/clock-out` | Staff | Validate location as configured and close a session. |
| `GET` | `/attendance/current` | Staff | Return the user’s open session, if any. |
| `GET` | `/attendance/me` | Staff | Paginated personal history. |
| `POST` | `/attendance/corrections` | Staff | Request a manual correction. |
| `GET` | `/admin/attendance` | Manager/Admin | Filter organization attendance. |
| `POST` | `/admin/offices` | Admin | Create an office geofence. |
| `PATCH` | `/admin/offices/{office_id}` | Admin | Update office configuration. |
| `POST` | `/admin/attendance/{session_id}/corrections` | Manager/Admin | Approve a correction with an audit record. |

### Clock-In Request

`POST /api/v1/attendance/clock-in`

```json
{
  "office_location_id": "0d2faef8-3068-41e4-8b90-b2b8b16f0b8f",
  "location": {
    "latitude": 6.5244,
    "longitude": 3.3792,
    "accuracy_m": 12.5,
    "captured_at": "2026-08-06T08:01:19Z"
  },
  "device_id": "app-generated-device-uuid",
  "idempotency_key": "2ac783d1-4a34-4be1-a7aa-14383b77f4c9"
}
```

Successful response (`201 Created`):

```json
{
  "session_id": "9ccb8e3d-9237-4d15-a506-184d6a171fc9",
  "status": "clocked_in",
  "clocked_in_at": "2026-08-06T08:01:22Z",
  "office": { "id": "0d2faef8-3068-41e4-8b90-b2b8b16f0b8f", "name": "Lagos Office" },
  "distance_m": 18.4
}
```

Example rejected response (`422 Unprocessable Entity`):

```json
{
  "detail": {
    "code": "OUTSIDE_GEOFENCE",
    "message": "Your location is outside the allowed clock-in area.",
    "distance_m": 212.7,
    "allowed_radius_m": 100
  }
}
```

Use consistent error codes: `LOCATION_ACCURACY_TOO_LOW`, `LOCATION_TOO_OLD`, `OUTSIDE_GEOFENCE`, `OFFICE_NOT_ASSIGNED`, `OPEN_SESSION_EXISTS`, `NO_OPEN_SESSION`, and `LOCATION_REQUIRED`.

## Server-Side Validation Rules

For a clock-in request, the API should:

1. Validate the JWT, active user status, and organization membership.
2. Confirm the selected office exists, is active, and is assigned to the staff member.
3. Validate coordinate ranges: latitude `-90..90`, longitude `-180..180`, accuracy greater than zero.
4. Reject a location sample older than the configured maximum age. Compare `captured_at` to server time and tolerate a small client clock skew.
5. Reject an accuracy value worse than the office maximum. A position 5 metres inside a boundary with 100-metre accuracy is not reliable.
6. Calculate the geodesic distance from the office coordinate to the supplied coordinate using Haversine or PostGIS `ST_DWithin`.
7. Allow the event only when the distance is within the radius. A conservative policy is `distance_m + accuracy_m <= radius_m`.
8. Use the server receipt time as the official attendance time. Keep the client capture time only as evidence.
9. Lock or transactionally check the user’s current open session, so simultaneous retries cannot create two sessions.
10. Store both accepted and rejected requests as attendance events, subject to the location-retention policy.

An `Idempotency-Key` header or body field is important for mobile networks. Repeating the same request should return the original response instead of recording a second clock-in.

## FastAPI Project Structure

```text
app/
  main.py
  api/
    v1/
      auth.py
      attendance.py
      offices.py
      admin.py
  core/
    config.py
    security.py
    dependencies.py
  db/
    session.py
    models/
    migrations/
  schemas/
    attendance.py
    office.py
    user.py
  services/
    attendance_service.py
    geofence_service.py
    audit_service.py
  tests/
    api/
    services/
```

Keep route handlers thin. Put distance calculation, rules, session transitions, and database transactions in `attendance_service.py`; this makes the critical clock-in logic straightforward to test.

## Security, Privacy, and Fraud Controls

- Require HTTPS, secure token storage on devices, rate limiting, and account lockout or throttling for repeated failed logins.
- Scope every database query by `organization_id`; never trust an organization ID supplied by the client without checking membership.
- Record the server timestamp, request ID, device ID, GPS accuracy, calculated distance, and decision reason.
- Treat phone-provided coordinates as evidence, not proof. Rooted devices, developer options, GPS spoofing apps, and compromised clients can fake location.
- Add layered fraud signals where needed: device integrity attestation (Play Integrity/App Attest), emulator/root detection performed by the app, impossible-travel checks, repeated boundary attempts, and manager review queues.
- Do not use IP address or Wi-Fi SSID as the only location verification. They can be useful weak signals but are not reliable proof of physical presence.
- Request the minimum mobile permission needed, clearly state why it is needed, and avoid continuous tracking by default.
- Obtain local legal/privacy review before deployment. Staff location data is personal data and may have employment-law requirements.

## Key Decisions Before Implementation

- What radius fits each office? Start around 75-150 metres, then calibrate based on building density and GPS quality.
- Must clock-out happen at the office, or can it happen remotely?
- Are users allowed to select an office, or should the server select the nearest assigned office?
- What is the manual fallback when GPS is unavailable: manager approval, QR code at reception, or an approved remote-work request?
- How long should exact coordinates and rejected events be retained?
- Which timezone defines work days, late arrivals, and reports for each office?

## Delivery Plan

1. Build authentication, organization membership, office CRUD, and migrations.
2. Implement the clock-in/clock-out endpoints, Haversine validation, idempotency, and audit events.
3. Add staff history, manager attendance views, correction workflow, and CSV export.
4. Build the phone app location-permission and retry flows; test poor GPS and weak-network conditions on real devices.
5. Add schedules, notifications, fraud signals, monitoring, backups, and retention jobs.

## Test Checklist

- Distance calculator: same coordinate, boundary, just inside, just outside, and coordinates across hemispheres.
- Requests with stale, inaccurate, missing, or invalid location data.
- Staff accessing an office outside their assignment or another organization.
- Two simultaneous clock-in requests and repeated requests with the same idempotency key.
- Clock-out without an open session and clock-in with an existing open session.
- Timezone boundaries, daylight-saving transitions for offices that use DST, and report date ranges.
- Authorization tests for every manager and admin endpoint.
- Load tests around common arrival times, such as 8:00-9:00 AM.
