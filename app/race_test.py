import threading
import httpx
from datetime import datetime, timezone

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3MTIwOWJmMi0wZmQzLTRjOGMtODI1Ni1hZTQ4ZDc3NDQyMDgiLCJleHAiOjE3ODYxMTQ0MjZ9.FdBRr2wqC4QSnRzn6Yq2VLxudaw_MZVhf2Ybp6QE_tw"
MEMBERSHIP_ID = "b3022e69-7923-4ce8-9795-e58ef12a08a0"
OFFICE_ID = "e0564f01-b127-4f0a-8b76-48edda848347"

body = {
    "membership_id": MEMBERSHIP_ID,
    "office_location_id": OFFICE_ID,
    "location": {
        "latitude": 6.5244,
        "longitude": 3.3792,
        "accuracy_m": 10,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    },
}
headers = {"Authorization": f"Bearer {TOKEN}"}

results = []

def fire():
    r = httpx.post("http://127.0.0.1:8000/api/v1/attendance/clock-in", json=body, headers=headers)
    results.append((r.status_code, r.json()))

threads = [threading.Thread(target=fire) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()

for status, data in results:
    print(status, data)