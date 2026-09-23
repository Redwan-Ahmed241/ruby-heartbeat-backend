"""Unit and integration tests for Age Verification and Validation in LifeDrop."""
import uuid
from datetime import date
import pytest
from fastapi.testclient import TestClient

from main import app
from app.models.user import Donor
from app.core.enums import BloodGroup, AvailabilityStatus, ComponentType
from app.services.eligibility import check_donor_eligibility

client = TestClient(app)


def test_donor_age_17_rejected_with_400():
    """Registering a donor with age 17 returns 400 Bad Request with message 'You must be at least 18 years old'."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Young Donor {unique}",
        "email": f"young_{unique}@example.com",
        "phone": "+8801700112233",
        "password": "Password123!",
        "role": "DONOR",
        "age": 17,
        "blood_group": "O_POSITIVE",
        "address": "Banani, Dhaka",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "You must be at least 18 years old" in response.text


def test_donor_age_over_65_rejected():
    """Registering a donor with age > 65 returns 400 Bad Request."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Senior Donor {unique}",
        "email": f"senior_{unique}@example.com",
        "phone": "+8801700112234",
        "password": "Password123!",
        "role": "DONOR",
        "age": 70,
        "blood_group": "A_POSITIVE",
        "address": "Dhanmondi, Dhaka",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "Maximum eligible age" in response.text


def test_donor_age_22_accepted_with_201():
    """Registering a donor with age 22 succeeds with 201 Created."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Eligible Donor {unique}",
        "email": f"eligible_{unique}@example.com",
        "phone": "+8801700112235",
        "password": "Password123!",
        "role": "DONOR",
        "age": 22,
        "blood_group": "B_POSITIVE",
        "address": "Gulshan, Dhaka",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "DONOR"
    assert data["donor"] is not None
    assert data["donor"]["age"] == 22


def test_recipient_without_age_succeeds():
    """Registering a recipient without age succeeds."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Recipient Patient {unique}",
        "email": f"recip_{unique}@example.com",
        "phone": "+8801800112233",
        "password": "Password123!",
        "role": "RECIPIENT",
        "address": "Mirpur, Dhaka",
        "nid_passport_no": "19951234567890",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "RECIPIENT"


def test_eligibility_service_underage_disqualified():
    """Eligibility check for donor under 18 returns Underage reason."""
    dummy_donor = Donor(
        donor_id=uuid.uuid4(),
        blood_group=BloodGroup.O_POSITIVE,
        date_of_birth=date(2010, 1, 1),
        age=16,
        gender="Male",
        weight=60.0,
        address="Dhaka",
        latitude=23.8103,
        longitude=90.4125,
        availability_status=AvailabilityStatus.AVAILABLE,
    )
    is_eligible, rejections, metrics = check_donor_eligibility(dummy_donor)
    assert is_eligible is False
    assert any("Underage: Must be at least 18 years old to donate blood." in r for r in rejections)
    assert metrics["age"] == 16


def test_update_profile_age():
    """Updating donor age via /api/v1/users/profile."""
    unique = uuid.uuid4().hex[:8]
    email = f"donor_{unique}@example.com"
    pwd = "Password123!"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Profile Age Donor",
            "email": email,
            "phone": "+8801700998877",
            "password": pwd,
            "role": "DONOR",
            "age": 20,
            "blood_group": "A_POSITIVE",
            "address": "Banani, Dhaka",
        },
    )
    assert reg.status_code == 201
    token_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
    )
    assert token_res.status_code == 200
    token = token_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Update age to 25
    update_res = client.put(
        "/api/v1/users/profile",
        headers=headers,
        json={"age": 25, "address": "Gulshan, Dhaka"},
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["donor"]["age"] == 25
