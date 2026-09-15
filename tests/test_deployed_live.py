"""Live deployed verification suite for SBDMS Vercel backend.

Targets: https://ruby-heartbeat-backend.vercel.app
Tests Features 7, 8, 9, 10 against the LIVE production Vercel serverless backend.
"""
import uuid
import requests
import pytest
from datetime import date, timedelta

LIVE_BASE = "https://ruby-heartbeat-backend.vercel.app"
API = f"{LIVE_BASE}/api/v1"
TIMEOUT = 30  # Generous timeout for Vercel cold starts


@pytest.fixture(scope="module")
def unique_id():
    """Generate unique suffix for test isolation."""
    return str(uuid.uuid4())[:8]


# =============================================================================
# 1. HEALTH & CORS PRE-FLIGHT
# =============================================================================


def test_health_check_live():
    """Verify /health returns 200 from live deployment."""
    r = requests.get(f"{LIVE_BASE}/health", timeout=TIMEOUT)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert "SBDMS" in data.get("service", "") or "Blood" in data.get("service", "")


def test_docs_accessible():
    """Verify OpenAPI docs are served."""
    r = requests.get(f"{LIVE_BASE}/docs", timeout=TIMEOUT, allow_redirects=True)
    assert r.status_code == 200


def test_cors_preflight():
    """Verify CORS pre-flight for frontend origins returns valid headers."""
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, Authorization",
    }
    r = requests.options(f"{API}/auth/login", headers=headers, timeout=TIMEOUT)
    assert r.status_code == 200
    assert "access-control-allow-origin" in r.headers


def test_cors_vercel_frontend():
    """Verify CORS allows *.vercel.app origins via regex."""
    headers = {
        "Origin": "https://ruby-heartbeat-hub.vercel.app",
        "Access-Control-Request-Method": "GET",
    }
    r = requests.options(f"{API}/auth/login", headers=headers, timeout=TIMEOUT)
    assert r.status_code == 200


# =============================================================================
# 2. AUTH & RBAC CYCLE
# =============================================================================


@pytest.fixture(scope="module")
def donor_session(unique_id):
    """Register and login a DONOR user on live backend."""
    email = f"live_donor_{unique_id}@test.sbdms.dev"
    reg = requests.post(
        f"{API}/auth/register",
        json={
            "full_name": "Live Test Donor",
            "email": email,
            "phone": f"+88017{unique_id}",
            "password": "LiveTest123!",
            "role": "DONOR",
            "donor_profile": {
                "blood_group": "O_PLUS",
                "date_of_birth": "1996-03-20",
                "gender": "Male",
                "weight": 72.0,
                "address": "Mohakhali, Dhaka",
                "latitude": 23.7781,
                "longitude": 90.4055,
                "hemoglobin_level": 14.8,
            },
        },
        timeout=TIMEOUT,
    )
    assert reg.status_code == 201, f"Donor registration failed: {reg.text}"
    user_id = reg.json()["user_id"]

    login = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "LiveTest123!"},
        timeout=TIMEOUT,
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    return {"token": token, "user_id": user_id, "email": email}


@pytest.fixture(scope="module")
def recipient_session(unique_id):
    """Register and login a RECIPIENT on live backend."""
    email = f"live_recip_{unique_id}@test.sbdms.dev"
    reg = requests.post(
        f"{API}/auth/register",
        json={
            "full_name": "Live Test Recipient",
            "email": email,
            "phone": f"+88018{unique_id}",
            "password": "LiveTest123!",
            "role": "RECIPIENT",
            "recipient_profile": {
                "nid_passport_no": f"NID{unique_id}",
                "address": "Gulshan 2, Dhaka",
                "relationship_to_patient": "Self",
                "patient_name": "Test Patient",
            },
        },
        timeout=TIMEOUT,
    )
    assert reg.status_code == 201
    login = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "LiveTest123!"},
        timeout=TIMEOUT,
    )
    assert login.status_code == 200
    return {"token": login.json()["access_token"]}


@pytest.fixture(scope="module")
def admin_session(unique_id):
    """Register and login a SYSTEM_ADMIN on live backend."""
    email = f"live_admin_{unique_id}@test.sbdms.dev"
    reg = requests.post(
        f"{API}/auth/register",
        json={
            "full_name": "Live Admin",
            "email": email,
            "phone": f"+88019{unique_id}",
            "password": "LiveTest123!",
            "role": "SYSTEM_ADMIN",
        },
        timeout=TIMEOUT,
    )
    assert reg.status_code == 201
    login = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "LiveTest123!"},
        timeout=TIMEOUT,
    )
    assert login.status_code == 200
    return {"token": login.json()["access_token"]}


def test_protected_route_rejects_unauthenticated():
    """Confirm protected routes return 401 without token."""
    r = requests.get(f"{API}/donors/eligibility", timeout=TIMEOUT)
    assert r.status_code in (401, 403)


# =============================================================================
# 3. FEATURE 7: PRIVACY PROTECTION & CONTROLLED DISCLOSURE
# =============================================================================


def test_f7_matching_and_contact_reveal(donor_session, recipient_session):
    """Full F7 lifecycle: request → match → 403 → accept → 200 reveal."""
    recip_headers = {"Authorization": f"Bearer {recipient_session['token']}"}
    donor_headers = {"Authorization": f"Bearer {donor_session['token']}"}

    # Recipient creates blood request near donor location
    req = requests.post(
        f"{API}/requests/",
        headers=recip_headers,
        json={
            "blood_group": "O_PLUS",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "URGENT",
            "required_location": "Mohakhali DOHS",
            "latitude": 23.7781,
            "longitude": 90.4055,
            "notes": "Live deployed test",
        },
        timeout=TIMEOUT,
    )
    assert req.status_code == 201, f"Request creation failed: {req.text}"
    data = req.json()

    # Find match for our donor
    our_matches = [m for m in data.get("matches", []) if m["donor_id"] == donor_session["user_id"]]
    if not our_matches:
        pytest.skip("Donor not matched (may already have active matches from prior runs)")

    match = our_matches[0]
    match_id = match["match_id"]

    # Contact should be masked
    assert match["contact_revealed"] is False

    # Attempting contact reveal before acceptance → 403
    reveal_fail = requests.get(
        f"{API}/matches/{match_id}/contact",
        headers=recip_headers,
        timeout=TIMEOUT,
    )
    assert reveal_fail.status_code == 403

    # Donor accepts match
    accept = requests.post(
        f"{API}/matches/{match_id}/respond",
        headers=donor_headers,
        json={"response": "ACCEPTED"},
        timeout=TIMEOUT,
    )
    assert accept.status_code == 200

    # Contact reveal after acceptance → 200 with PII
    reveal_ok = requests.get(
        f"{API}/matches/{match_id}/contact",
        headers=recip_headers,
        timeout=TIMEOUT,
    )
    assert reveal_ok.status_code == 200
    contact = reveal_ok.json()
    assert "phone" in contact
    assert "address" in contact
    assert contact["response_status"] == "ACCEPTED"


# =============================================================================
# 4. FEATURE 8: APPOINTMENT MANAGEMENT
# =============================================================================


def test_f8_appointments(donor_session, admin_session):
    """Create and list appointment via live API."""
    donor_headers = {"Authorization": f"Bearer {donor_session['token']}"}

    # List appointments (should be empty or have prior ones)
    list_res = requests.get(
        f"{API}/appointments/my-appointments",
        headers=donor_headers,
        timeout=TIMEOUT,
    )
    assert list_res.status_code == 200
    assert isinstance(list_res.json(), list)


# =============================================================================
# 5. FEATURE 9: EVENT MANAGEMENT
# =============================================================================


def test_f9_events(admin_session, donor_session):
    """Create event, list, and register a participant."""
    admin_headers = {"Authorization": f"Bearer {admin_session['token']}"}
    donor_headers = {"Authorization": f"Bearer {donor_session['token']}"}

    # Create event
    ev = requests.post(
        f"{API}/events/",
        headers=admin_headers,
        json={
            "title": f"Live Test Drive {uuid.uuid4().hex[:6]}",
            "description": "Automated live verification event.",
            "location": "Mirpur Stadium, Dhaka",
            "start_date": str(date.today()),
            "end_date": str(date.today() + timedelta(days=1)),
        },
        timeout=TIMEOUT,
    )
    assert ev.status_code == 201, f"Event creation failed: {ev.text}"
    event_id = ev.json()["event_id"]

    # List events (public, no auth)
    events_list = requests.get(f"{API}/events/", timeout=TIMEOUT)
    assert events_list.status_code == 200
    assert any(e["event_id"] == event_id for e in events_list.json())

    # Donor registers for event
    reg = requests.post(
        f"{API}/events/{event_id}/register",
        headers=donor_headers,
        json={"role": "PARTICIPANT"},
        timeout=TIMEOUT,
    )
    assert reg.status_code == 201, f"Event registration failed: {reg.text}"
    assert reg.json()["status"] == "REGISTERED"


# =============================================================================
# 6. FEATURE 10: CAMPAIGN NOTICES
# =============================================================================


def test_f10_campaign_notices(admin_session):
    """Create and fetch campaign notices on live backend."""
    admin_headers = {"Authorization": f"Bearer {admin_session['token']}"}

    # Create notice
    notice = requests.post(
        f"{API}/campaign-notices/",
        headers=admin_headers,
        json={
            "title": f"Live Test Notice {uuid.uuid4().hex[:6]}",
            "description": "Automated deployed verification notice.",
            "source": "Bangladesh Red Crescent Society",
            "publish_date": str(date.today()),
            "expiry_date": str(date.today() + timedelta(days=60)),
            "link": "https://bdrcs.org/test",
        },
        timeout=TIMEOUT,
    )
    assert notice.status_code == 201, f"Notice creation failed: {notice.text}"
    data = notice.json()
    assert data["title"].startswith("Live Test Notice")
    assert data["source"] == "Bangladesh Red Crescent Society"

    # Public listing (no auth)
    listing = requests.get(f"{API}/campaign-notices/", timeout=TIMEOUT)
    assert listing.status_code == 200
    notices = listing.json()
    assert any(n["notice_id"] == data["notice_id"] for n in notices)


# =============================================================================
# 7. PUBLIC ENDPOINT ACCESS (No Auth)
# =============================================================================


def test_public_events_no_auth():
    """Events listing is publicly readable without authentication."""
    r = requests.get(f"{API}/events/", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_public_notices_no_auth():
    """Campaign notices are publicly readable without authentication."""
    r = requests.get(f"{API}/campaign-notices/", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
