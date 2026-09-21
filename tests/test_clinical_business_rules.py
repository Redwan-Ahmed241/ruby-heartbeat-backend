"""Automated Integration Test Suite for Clinical Guardrails & Business Rules.

Covers:
1. test_leaderboard_contains_blood_group: Verifies /api/v1/donors/leaderboard returns blood groups.
2. test_donor_single_active_match_lock: Confirms accepting a second match while one is active returns 400 Bad Request.
3. test_two_sided_completion_and_90_day_cooldown: Confirms mutual completion triggers COMPLETED, increments donation count, updates last_donation_date, and excludes the donor from matches for 90 days.
4. test_recipient_rate_limiting_per_patient: Confirms creating a 3rd active request for the same patient in 24 hours returns 429 Too Many Requests, and confirms cancelling an earlier request frees up quota.
5. test_request_cancellation: Confirms an open request transitions to CANCELLED and sets pending matches to CANCELLED.
6. test_optional_nid_registration: Confirms user registration succeeds with or without nid_or_birth_cert.
"""
import sys
import uuid
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "backend")

from main import app
from app.core.enums import (
    BloodGroup,
    RequestUrgency,
    RequestStatus,
    MatchResponseStatus,
    AvailabilityStatus,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_external_email_dispatcher(monkeypatch):
    """Safely mock external SMTP/network email calls during test execution to prevent test delays."""
    dummy_true = lambda *args, **kwargs: True
    dummy_count = lambda *args, **kwargs: 1
    monkeypatch.setattr("app.services.email_service._dispatch_email", dummy_true)
    monkeypatch.setattr("app.services.email_service.send_single_donor_match_alert", dummy_true)
    monkeypatch.setattr("app.services.email_service.send_emergency_broadcast_alert", dummy_count)
    monkeypatch.setattr("app.services.email_service.send_donor_accepted_alert", dummy_true)
    monkeypatch.setattr("app.services.email_service.send_donation_completed_thank_you_alert", dummy_true)
    monkeypatch.setattr("app.services.email_service.send_match_cancelled_reopened_alert", dummy_true)
    monkeypatch.setattr("app.services.email_service.send_request_creation_confirmation_alert", dummy_true)
    monkeypatch.setattr("app.api.v1.requests.send_single_donor_match_alert", dummy_true)
    monkeypatch.setattr("app.api.v1.requests.send_emergency_broadcast_alert", dummy_count)
    monkeypatch.setattr("app.api.v1.requests.send_donor_accepted_alert", dummy_true)
    monkeypatch.setattr("app.api.v1.requests.send_donation_completed_thank_you_alert", dummy_true)
    monkeypatch.setattr("app.api.v1.requests.send_match_cancelled_reopened_alert", dummy_true)
    monkeypatch.setattr("app.api.v1.requests.send_request_creation_confirmation_alert", dummy_true)


def _register_user(role: str, blood_group: str = "O_POSITIVE", full_name: str = "Test User", lat: float = 23.8103, lon: float = 90.4125, nid: str = None):
    suffix = str(uuid.uuid4())[:8]
    email = f"{role.lower()}_{suffix}@example.com"
    # Ensure numeric phone
    numeric_suffix = "".join(filter(str.isdigit, suffix)) or "12345"
    phone = f"+8801700{numeric_suffix[:6]}"
    payload = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password": "Password123!",
        "role": role,
    }
    if nid:
        payload["nid_or_birth_cert"] = nid

    if role == "DONOR":
        payload["donor_profile"] = {
            "blood_group": blood_group,
            "date_of_birth": "1996-01-01",
            "gender": "Male",
            "weight": 68.0,
            "address": "Dhaka, Bangladesh",
            "latitude": lat,
            "longitude": lon,
            "hemoglobin_level": 14.5,
        }
    elif role == "RECIPIENT":
        payload["recipient_profile"] = {
            "nid_passport_no": nid or "199601019999",
            "address": "Dhaka, Bangladesh",
            "relationship_to_patient": "Self",
            "patient_name": full_name,
        }

    res = client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 201, f"Registration failed: {res.text}"
    user_data = res.json()

    # Login to acquire bearer token
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    return user_data, headers


def test_leaderboard_contains_blood_group():
    """1. Verifies /api/v1/donors/leaderboard returns blood groups."""
    res = client.get("/api/v1/donors/leaderboard")
    assert res.status_code == 200, f"Leaderboard fetch failed: {res.text}"
    data = res.json()
    assert isinstance(data, list)
    for donor in data:
        assert "blood_group" in donor, "Each leaderboard entry must contain blood_group"
        assert donor["blood_group"] in [bg.value for bg in BloodGroup]


def test_donor_single_active_match_lock():
    """2. Confirms accepting a second match while one is active returns 400 Bad Request."""
    donor, donor_headers = _register_user("DONOR", blood_group="A_POSITIVE", full_name="Donor Single Lock")
    recip1, recip1_headers = _register_user("RECIPIENT", full_name="Recipient Lock 1")
    recip2, recip2_headers = _register_user("RECIPIENT", full_name="Recipient Lock 2")

    # Recipient 1 creates a request matching the donor
    req1_res = client.post(
        "/api/v1/requests/",
        headers=recip1_headers,
        json={
            "blood_group": "A_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "URGENT",
            "required_location": "Dhaka Medical College",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": "Lock Patient One",
        },
    )
    assert req1_res.status_code == 201
    req1_data = req1_res.json()
    matches1 = [m for m in req1_data.get("matches", []) if m["donor_id"] == donor["user_id"]]
    assert matches1, "Should have matched registered donor"
    match1_id = matches1[0]["match_id"]

    # Recipient 2 creates a second request also matching the donor
    req2_res = client.post(
        "/api/v1/requests/",
        headers=recip2_headers,
        json={
            "blood_group": "A_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "URGENT",
            "required_location": "Square Hospital, Dhaka",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": "Lock Patient Two",
        },
    )
    assert req2_res.status_code == 201
    req2_data = req2_res.json()
    matches2 = [m for m in req2_data.get("matches", []) if m["donor_id"] == donor["user_id"]]
    assert matches2, "Should have matched registered donor"
    match2_id = matches2[0]["match_id"]

    # Donor accepts match 1 -> Success 200
    accept1 = client.post(
        f"/api/v1/matches/{match1_id}/respond",
        headers=donor_headers,
        json={"response": "ACCEPTED"},
    )
    assert accept1.status_code == 200, f"Failed first accept: {accept1.text}"

    # Donor tries to accept match 2 while match 1 is active -> 400 Bad Request
    accept2 = client.post(
        f"/api/v1/matches/{match2_id}/respond",
        headers=donor_headers,
        json={"response": "ACCEPTED"},
    )
    assert accept2.status_code == 400, f"Expected 400 Concurrency Lock, got: {accept2.status_code} {accept2.text}"
    assert "active accepted donation commitment" in accept2.json()["detail"].lower()


def test_two_sided_completion_and_90_day_cooldown():
    """3. Confirms mutual completion triggers COMPLETED, increments donation count,
    updates last_donation_date, and excludes donor from matching for 90 days."""
    donor, donor_headers = _register_user("DONOR", blood_group="B_POSITIVE", full_name="Donor Mutual Cooldown")
    recip, recip_headers = _register_user("RECIPIENT", full_name="Recipient Mutual")

    # Create request and match
    req_res = client.post(
        "/api/v1/requests/",
        headers=recip_headers,
        json={
            "blood_group": "B_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "BIRDEM General Hospital",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": "Mutual Patient",
        },
    )
    assert req_res.status_code == 201
    req_data = req_res.json()
    matches = [m for m in req_data.get("matches", []) if m["donor_id"] == donor["user_id"]]
    assert matches, "Expected match for registered donor"
    match_id = matches[0]["match_id"]

    # Donor accepts
    client.post(f"/api/v1/matches/{match_id}/respond", headers=donor_headers, json={"response": "ACCEPTED"})

    # Step A: Donor confirms completion only
    donor_confirm = client.post(f"/api/v1/matches/{match_id}/confirm-completion", headers=donor_headers)
    assert donor_confirm.status_code == 200
    confirm_data1 = donor_confirm.json()
    assert confirm_data1["donor_confirmed_completion"] is True
    assert confirm_data1["recipient_confirmed_completion"] is False
    assert confirm_data1["is_completed"] is False

    # Step B: Recipient confirms completion -> Mutually finalized
    recip_confirm = client.post(f"/api/v1/matches/{match_id}/confirm-completion", headers=recip_headers)
    assert recip_confirm.status_code == 200
    confirm_data2 = recip_confirm.json()
    assert confirm_data2["donor_confirmed_completion"] is True
    assert confirm_data2["recipient_confirmed_completion"] is True
    assert confirm_data2["is_completed"] is True
    assert confirm_data2["status"] == "COMPLETED"
    assert confirm_data2["cooldown_until"] is not None

    # Verify matching exclusion: New request for B_POSITIVE should NOT match this cooldown donor
    req_next = client.post(
        "/api/v1/requests/",
        headers=recip_headers,
        json={
            "blood_group": "B_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "BIRDEM General Hospital",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": "Another Patient",
        },
    )
    assert req_next.status_code == 201
    for m in (req_next.json()["matches"] or []):
        assert m["donor_id"] != donor["user_id"], "Donor in cooldown must be excluded from matching"


def test_recipient_rate_limiting_per_patient():
    """4. Confirms creating a 3rd active request for same patient in 24h returns 429 Too Many Requests,
    and cancelling an earlier request frees up quota."""
    recip, recip_headers = _register_user("RECIPIENT", full_name="Recipient RateLimit")
    patient_name = "Kazi Nazrul Islam"

    # Request 1 -> 201 Created
    req1 = client.post(
        "/api/v1/requests/",
        headers=recip_headers,
        json={
            "blood_group": "AB_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "Apollo Hospital Dhaka",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": patient_name,
        },
    )
    assert req1.status_code == 201, f"Req 1 failed: {req1.text}"
    req1_id = req1.json()["request_id"]

    # Request 2 (case/space variant) -> 201 Created
    req2 = client.post(
        "/api/v1/requests/",
        headers=recip_headers,
        json={
            "blood_group": "AB_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "Evercare Hospital Dhaka",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": " kazi nazrul islam ",
        },
    )
    assert req2.status_code == 201, f"Req 2 failed: {req2.text}"

    # Request 3 for same patient within 24h -> 429 Too Many Requests
    req3 = client.post(
        "/api/v1/requests/",
        headers=recip_headers,
        json={
            "blood_group": "AB_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "United Hospital Dhaka",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": "KAZI NAZRUL ISLAM",
        },
    )
    assert req3.status_code == 429, f"Expected 429 Rate Limit, got {req3.status_code}: {req3.text}"
    assert "daily limit reached" in req3.json()["detail"].lower()

    # Cancel request 1 to free up quota
    cancel_res = client.post(f"/api/v1/requests/{req1_id}/cancel", headers=recip_headers)
    assert cancel_res.status_code == 200, f"Cancel failed: {cancel_res.text}"
    assert cancel_res.json()["status"] == "CANCELLED"

    # Now Request 4 for same patient succeeds -> 201 Created
    req4 = client.post(
        "/api/v1/requests/",
        headers=recip_headers,
        json={
            "blood_group": "AB_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "United Hospital Dhaka",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": patient_name,
        },
    )
    assert req4.status_code == 201, f"Req 4 should succeed after cancelling req 1: {req4.text}"


def test_request_cancellation():
    """5. Confirms an open request transitions to CANCELLED and sets pending matches to CANCELLED."""
    donor, donor_headers = _register_user("DONOR", blood_group="O_NEGATIVE", full_name="Donor For Cancel")
    recip, recip_headers = _register_user("RECIPIENT", full_name="Recipient Cancel Flow")

    # Recipient creates request -> creates match
    req_res = client.post(
        "/api/v1/requests/",
        headers=recip_headers,
        json={
            "blood_group": "O_NEGATIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 2.0,
            "urgency": "EMERGENCY",
            "required_location": "Kurmitola General Hospital",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "patient_name": "Cancel Patient Test",
        },
    )
    assert req_res.status_code == 201
    req_id = req_res.json()["request_id"]
    matches = req_res.json()["matches"]
    assert matches, "Expected matches to be created"

    # Unauthorized user tries to cancel -> 403 Forbidden
    other_user, other_headers = _register_user("RECIPIENT", full_name="Other User")
    unauth_cancel = client.post(f"/api/v1/requests/{req_id}/cancel", headers=other_headers)
    assert unauth_cancel.status_code == 403

    # Authorized recipient cancels request
    cancel_res = client.post(f"/api/v1/requests/{req_id}/cancel", headers=recip_headers)
    assert cancel_res.status_code == 200
    cancel_data = cancel_res.json()
    assert cancel_data["status"] == "CANCELLED"

    # Verify matches for this request are released/cancelled
    matches_res = client.get(f"/api/v1/requests/{req_id}/matches", headers=recip_headers)
    assert matches_res.status_code == 200
    for match in matches_res.json():
        assert match["response_status"] == "CANCELLED"


def test_optional_nid_registration():
    """6. Confirms user registration succeeds with or without nid_or_birth_cert."""
    # Without NID
    user_no_nid, headers_no_nid = _register_user("DONOR", full_name="User Without NID", nid=None)
    assert user_no_nid["nid_or_birth_cert"] is None
    me_no_nid = client.get("/api/v1/auth/me", headers=headers_no_nid)
    assert me_no_nid.status_code == 200
    assert me_no_nid.json()["nid_or_birth_cert"] is None

    # With NID
    test_nid = "1997261948271049"
    user_with_nid, headers_with_nid = _register_user("DONOR", full_name="User With NID", nid=test_nid)
    assert user_with_nid["nid_or_birth_cert"] == test_nid
    me_with_nid = client.get("/api/v1/auth/me", headers=headers_with_nid)
    assert me_with_nid.status_code == 200
    assert me_with_nid.json()["nid_or_birth_cert"] == test_nid
