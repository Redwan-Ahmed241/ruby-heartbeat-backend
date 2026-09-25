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


def test_registration_without_dob_returns_422():
    """Negative test: Registration without mandatory date_of_birth returns 422 Unprocessable Entity."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"No DOB Donor {unique}",
        "email": f"nodob_{unique}@example.com",
        "phone": "+8801700112230",
        "password": "Password123!",
        "role": "DONOR",
        "blood_group": "O_POSITIVE",
        "address": "Banani, Dhaka",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert "date_of_birth" in response.text


def test_donor_age_under_18_rejected_with_400():
    """Negative test: Registering a donor with date_of_birth making age < 18 returns 400 Bad Request."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Young Donor {unique}",
        "email": f"young_{unique}@example.com",
        "phone": "+8801700112233",
        "password": "Password123!",
        "role": "DONOR",
        "date_of_birth": "2010-01-01",  # Underage (16 years old)
        "blood_group": "O_POSITIVE",
        "address": "Banani, Dhaka",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "at least 18 years old" in response.text


def test_donor_age_over_65_rejected():
    """Registering a donor with age > 65 returns 400 Bad Request."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Senior Donor {unique}",
        "email": f"senior_{unique}@example.com",
        "phone": "+8801700112234",
        "password": "Password123!",
        "role": "DONOR",
        "date_of_birth": "1950-01-01",  # 76 years old
        "blood_group": "A_POSITIVE",
        "address": "Dhanmondi, Dhaka",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "Maximum eligible age" in response.text


def test_donor_age_22_accepted_with_201():
    """Registering a donor with valid birthdate (age > 18) succeeds with 201 Created."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Eligible Donor {unique}",
        "email": f"eligible_{unique}@example.com",
        "phone": "+8801700112235",
        "password": "Password123!",
        "role": "DONOR",
        "date_of_birth": "2004-05-15",  # 22 years old
        "blood_group": "B_POSITIVE",
        "address": "Gulshan, Dhaka",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "DONOR"
    assert data["donor"] is not None
    assert data["donor"]["age"] == 22
    assert data["donor"]["date_of_birth"] == "2004-05-15"


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


def test_update_profile_dob_weight_hemoglobin():
    """Updating donor date_of_birth, weight, and hemoglobin via /api/v1/users/profile."""
    unique = uuid.uuid4().hex[:8]
    email = f"donor_{unique}@example.com"
    pwd = "Password123!"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Profile Editable Donor",
            "email": email,
            "phone": "+8801700998877",
            "password": pwd,
            "role": "DONOR",
            "date_of_birth": "2002-05-15",
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

    # Update date_of_birth, weight, and hemoglobin
    update_res = client.put(
        "/api/v1/users/profile",
        headers=headers,
        json={
            "date_of_birth": "1998-03-20",
            "weight": 72.5,
            "hemoglobin": 14.8,
            "address": "Gulshan, Dhaka",
        },
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["date_of_birth"] == "1998-03-20"
    assert data["donor"]["date_of_birth"] == "1998-03-20"
    assert data["donor"]["age"] == 28
    assert float(data["donor"]["weight"]) == 72.5
    assert float(data["donor"]["medical_info"]["hemoglobin_level"]) == 14.8
