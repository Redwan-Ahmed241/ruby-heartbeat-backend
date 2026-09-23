import uuid
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_external_email(monkeypatch):
    monkeypatch.setattr("app.services.email_service._dispatch_email", lambda *args, **kwargs: True)

def test_user_profile_update_and_dynamic_cooldown():
    uid = uuid.uuid4().hex[:8]
    email = f"user_prof_{uid}@example.com"
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Original Name",
        "email": email,
        "phone": "+8801700000001",
        "password": "Password123!",
        "role": "DONOR",
        "blood_group": "A_POSITIVE",
        "address": "Dhanmondi, Dhaka",
    })
    assert reg.status_code == 201
    
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Update basic profile fields with backup_phone
    update_res = client.put("/api/v1/users/profile", headers=headers, json={
        "full_name": "Updated Member Name",
        "phone": "+8801700000002",
        "backup_phone": "+8801800000003",
        "address": "Mirpur, Dhaka",
        "blood_group": "B_POSITIVE",
    })
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["full_name"] == "Updated Member Name"
    assert data["phone"] == "+8801700000002"
    assert data["backup_phone"] == "+8801800000003"
    assert data["donor"]["blood_group"] == "B_POSITIVE"
    assert data["donor"]["address"] == "Mirpur, Dhaka"

    # 2. Update last_donation_date to 15 days ago -> Cooldown must become active (<90 days)
    recent_donation = str(date.today() - timedelta(days=15))
    cooldown_update = client.put("/api/v1/users/profile", headers=headers, json={
        "last_donation_date": recent_donation,
    })
    assert cooldown_update.status_code == 200
    c_data = cooldown_update.json()
    assert c_data["donor"]["availability_status"] == "UNAVAILABLE"

    # Check eligibility endpoint reflects the cooldown
    elig_res = client.get("/api/v1/donors/eligibility", headers=headers)
    assert elig_res.status_code == 200
    assert elig_res.json()["cooldown_active"] is True
    assert elig_res.json()["is_eligible"] is False

    # 3. Update last_donation_date to 100 days ago (>=90 days) -> Cooldown cleared
    old_donation = str(date.today() - timedelta(days=100))
    cleared_update = client.put("/api/v1/users/profile", headers=headers, json={
        "last_donation_date": old_donation,
    })
    assert cleared_update.status_code == 200
    cleared_data = cleared_update.json()
    assert cleared_data["donor"]["availability_status"] == "AVAILABLE"

    elig_res2 = client.get("/api/v1/donors/eligibility", headers=headers)
    assert elig_res2.status_code == 200
    assert elig_res2.json()["cooldown_active"] is False
    assert elig_res2.json()["is_eligible"] is True

def test_my_requests_endpoint():
    uid = uuid.uuid4().hex[:8]
    email = f"recip_my_{uid}@example.com"
    client.post("/api/v1/auth/register", json={
        "full_name": "Recipient My Requests",
        "email": email,
        "phone": "+8801711111111",
        "password": "Password123!",
        "role": "RECIPIENT",
        "blood_group": "O_POSITIVE",
        "address": "Gulshan, Dhaka",
    })
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post("/api/v1/requests/", headers=headers, json={
        "blood_group": "O_POSITIVE",
        "component_type": "WHOLE_BLOOD",
        "quantity": 1.0,
        "urgency": "NORMAL",
        "required_location": "United Hospital, Gulshan",
        "latitude": 23.7925,
        "longitude": 90.4078,
    })
    assert create_res.status_code == 201

    my_res = client.get("/api/v1/requests/my-requests", headers=headers)
    assert my_res.status_code == 200
    my_list = my_res.json()
    assert len(my_list) >= 1
    assert any(r["blood_group"] == "O_POSITIVE" for r in my_list)

def test_clear_all_notifications():
    uid = uuid.uuid4().hex[:8]
    email = f"user_notif_{uid}@example.com"
    client.post("/api/v1/auth/register", json={
        "full_name": "Notif User",
        "email": email,
        "phone": "+8801722222222",
        "password": "Password123!",
        "role": "DONOR",
        "blood_group": "A_POSITIVE",
        "address": "Uttara, Dhaka",
    })
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    post_clear = client.post("/api/v1/notifications/clear-all", headers=headers)
    assert post_clear.status_code == 200
    assert "cleared_count" in post_clear.json()

    del_clear = client.delete("/api/v1/notifications/clear-all", headers=headers)
    assert del_clear.status_code == 200
    assert "cleared_count" in del_clear.json()

def test_admin_reset_cooldown_and_cancel_request():
    uid_d = uuid.uuid4().hex[:8]
    email_d = f"donor_cool_{uid_d}@example.com"
    reg_d = client.post("/api/v1/auth/register", json={
        "full_name": "Donor To Reset",
        "email": email_d,
        "phone": "+8801733333333",
        "password": "Password123!",
        "role": "DONOR",
        "blood_group": "O_POSITIVE",
        "address": "Panthapath, Dhaka",
    })
    donor_user_id = reg_d.json()["user_id"]
    token_d = client.post("/api/v1/auth/login", json={"email": email_d, "password": "Password123!"}).json()["access_token"]
    headers_d = {"Authorization": f"Bearer {token_d}"}

    client.put("/api/v1/users/profile", headers=headers_d, json={
        "last_donation_date": str(date.today() - timedelta(days=10)),
    })
    assert client.get("/api/v1/donors/eligibility", headers=headers_d).json()["cooldown_active"] is True

    uid_r = uuid.uuid4().hex[:8]
    email_r = f"recip_adm_{uid_r}@example.com"
    client.post("/api/v1/auth/register", json={
        "full_name": "Recipient For Admin Test",
        "email": email_r,
        "phone": "+8801744444444",
        "password": "Password123!",
        "role": "RECIPIENT",
        "blood_group": "O_POSITIVE",
        "address": "Panthapath, Dhaka",
    })
    token_r = client.post("/api/v1/auth/login", json={"email": email_r, "password": "Password123!"}).json()["access_token"]
    headers_r = {"Authorization": f"Bearer {token_r}"}

    req_res = client.post("/api/v1/requests/", headers=headers_r, json={
        "blood_group": "O_POSITIVE",
        "component_type": "WHOLE_BLOOD",
        "quantity": 1.0,
        "urgency": "NORMAL",
        "required_location": "Square Hospital, Panthapath",
        "latitude": 23.7533,
        "longitude": 90.3855,
    })
    request_id = req_res.json()["request_id"]

    non_admin_reset = client.post(f"/api/v1/admin/donors/{donor_user_id}/reset-cooldown", headers=headers_d)
    assert non_admin_reset.status_code == 403

    non_admin_cancel = client.post(f"/api/v1/admin/requests/{request_id}/cancel", headers=headers_d, json={"reason": "Spam"})
    assert non_admin_cancel.status_code == 403

    email_admin = f"sys_admin_{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/auth/register", json={
        "full_name": "Super Admin",
        "email": email_admin,
        "phone": "+8801799999999",
        "password": "Password123!",
        "role": "SYSTEM_ADMIN",
    })
    token_admin = client.post("/api/v1/auth/login", json={"email": email_admin, "password": "Password123!"}).json()["access_token"]
    headers_admin = {"Authorization": f"Bearer {token_admin}"}

    reset_res = client.post(f"/api/v1/admin/donors/{donor_user_id}/reset-cooldown", headers=headers_admin)
    assert reset_res.status_code == 200
    assert reset_res.json()["user_id"] == donor_user_id and reset_res.json()["donor"]["last_donation_date"] is None

    check_elig = client.get("/api/v1/donors/eligibility", headers=headers_d).json()
    assert check_elig["cooldown_active"] is False
    assert check_elig["is_eligible"] is True

    cancel_res = client.post(f"/api/v1/admin/requests/{request_id}/cancel", headers=headers_admin, json={"reason": "Spam detected during verification"})
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

