import os
import uuid
import pytest
import requests

TARGET_BASE_URL = os.getenv("TARGET_URL", "https://ruby-heartbeat-backend.vercel.app/api/v1").rstrip("/")
TIMEOUT = 30

DEMO_DONOR_EMAIL = "donor.demo@lifedrop.org"
DEMO_RECIPIENT_EMAIL = "recipient.demo@lifedrop.org"
DEMO_HOSPITAL_EMAIL = "hospital.demo@lifedrop.org"
DEMO_ADMIN_EMAIL = "admin.demo@lifedrop.org"
DEMO_PASSWORD = "DemoPass123!"

@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s

@pytest.fixture(scope="session")
def donor_auth(session):
    res = session.post(
        f"{TARGET_BASE_URL}/auth/login",
        json={"email": DEMO_DONOR_EMAIL, "password": DEMO_PASSWORD},
        timeout=TIMEOUT,
    )
    assert res.status_code == 200, f"Donor login failed: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="session")
def recipient_auth(session):
    res = session.post(
        f"{TARGET_BASE_URL}/auth/login",
        json={"email": DEMO_RECIPIENT_EMAIL, "password": DEMO_PASSWORD},
        timeout=TIMEOUT,
    )
    assert res.status_code == 200, f"Recipient login failed: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="session")
def hospital_auth(session):
    res = session.post(
        f"{TARGET_BASE_URL}/auth/login",
        json={"email": DEMO_HOSPITAL_EMAIL, "password": DEMO_PASSWORD},
        timeout=TIMEOUT,
    )
    assert res.status_code == 200, f"Hospital Admin login failed: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="session")
def admin_auth(session):
    res = session.post(
        f"{TARGET_BASE_URL}/auth/login",
        json={"email": DEMO_ADMIN_EMAIL, "password": DEMO_PASSWORD},
        timeout=TIMEOUT,
    )
    assert res.status_code == 200, f"System Admin login failed: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

class TestPositiveLifecycleFlows:
    def test_01_authentication_all_roles(self, donor_auth, recipient_auth, hospital_auth, admin_auth):
        assert "Authorization" in donor_auth
        assert "Authorization" in recipient_auth
        assert "Authorization" in hospital_auth
        assert "Authorization" in admin_auth

    def test_02_recipient_creates_request_and_matching_dispatches(self, session, recipient_auth):
        payload = {
            "blood_group": "O_PLUS",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "Dhaka Medical College Hospital",
            "latitude": 23.7259,
            "longitude": 90.3976,
            "notes": "Live audit positive lifecycle flow test",
        }
        res = session.post(f"{TARGET_BASE_URL}/requests/", headers=recipient_auth, json=payload, timeout=TIMEOUT)
        assert res.status_code == 201, f"Create request failed: {res.text}"
        data = res.json()
        assert data["status"] == "MATCHED"
        assert len(data["matches"]) >= 1
        first_match = data["matches"][0]
        assert "match_id" in first_match
        assert "donor_id" in first_match
        assert "distance_km" in first_match
        assert first_match["match_score"] > 0
        assert first_match["contact_revealed"] is False
        assert "donor_name_initial" in first_match

    def test_03_donor_accepts_match_and_contact_revealed(self, session, donor_auth, recipient_auth):
        req_res = session.post(
            f"{TARGET_BASE_URL}/requests/",
            headers=recipient_auth,
            json={
                "blood_group": "O_PLUS",
                "component_type": "WHOLE_BLOOD",
                "quantity": 1.0,
                "urgency": "URGENT",
                "required_location": "Banani Clinic, Dhaka",
                "latitude": 23.7937,
                "longitude": 90.4066,
                "notes": "Targeted donor match acceptance flow",
            },
            timeout=TIMEOUT,
        )
        assert req_res.status_code == 201
        matches = req_res.json().get("matches", [])
        assert len(matches) >= 1
        target_match = matches[0]
        match_id = target_match["match_id"]

        resp_res = session.post(
            f"{TARGET_BASE_URL}/matches/{match_id}/respond",
            headers=donor_auth,
            json={"response": "ACCEPTED"},
            timeout=TIMEOUT,
        )
        if resp_res.status_code == 200:
            assert resp_res.json()["response_status"] == "ACCEPTED"
            contact_res = session.get(f"{TARGET_BASE_URL}/matches/{match_id}/contact", headers=recipient_auth, timeout=TIMEOUT)
            assert contact_res.status_code == 200
            contact_data = contact_res.json()
            assert "phone" in contact_data
            assert "full_name" in contact_data
            assert contact_data["response_status"] == "ACCEPTED"
        else:
            assert resp_res.status_code in (403, 404)

    def test_04_hospital_admin_inventory_and_expiry_scan(self, session, hospital_auth, admin_auth):
        scan_res = session.post(f"{TARGET_BASE_URL}/inventory/scan-expiries", headers=hospital_auth, timeout=TIMEOUT)
        assert scan_res.status_code == 200, f"Scan expiries failed: {scan_res.text}"
        scan_data = scan_res.json()
        assert "scanned_count" in scan_data
        assert "expiring_soon_count" in scan_data
        assert "Expiry scan completed" in scan_data["message"]

        inv_res = session.get(f"{TARGET_BASE_URL}/inventory/", headers=admin_auth, timeout=TIMEOUT)
        assert inv_res.status_code == 200
        items = inv_res.json()
        assert len(items) >= 1
        test_inv_id = items[0]["inventory_id"]

        tx_res = session.post(
            f"{TARGET_BASE_URL}/inventory/transaction",
            headers=hospital_auth,
            json={
                "inventory_id": test_inv_id,
                "type": "IN",
                "quantity": 2.0,
                "reference_type": "MANUAL",
            },
            timeout=TIMEOUT,
        )
        assert tx_res.status_code == 201
        tx_data = tx_res.json()
        assert tx_data["type"] == "IN"
        assert tx_data["quantity"] == 2.0

class TestRBACViolations:
    def test_rbac_violation_1_donor_cannot_modify_inventory(self, session, donor_auth, admin_auth):
        inv_res = session.get(f"{TARGET_BASE_URL}/inventory/", headers=admin_auth, timeout=TIMEOUT)
        items = inv_res.json()
        assert len(items) >= 1
        inv_id = items[0]["inventory_id"]

        res = session.post(
            f"{TARGET_BASE_URL}/inventory/transaction",
            headers=donor_auth,
            json={
                "inventory_id": inv_id,
                "type": "OUT",
                "quantity": 1.0,
                "reference_type": "MANUAL",
            },
            timeout=TIMEOUT,
        )
        assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"

    def test_rbac_violation_2_recipient_cannot_read_system_logs(self, session, recipient_auth):
        res = session.get(f"{TARGET_BASE_URL}/system-logs/", headers=recipient_auth, timeout=TIMEOUT)
        assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"

    def test_rbac_violation_3_hospital_cannot_modify_donor_availability(self, session, hospital_auth):
        res = session.patch(
            f"{TARGET_BASE_URL}/donors/availability",
            headers=hospital_auth,
            json={"availability_status": "AVAILABLE"},
            timeout=TIMEOUT,
        )
        assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"

    def test_rbac_violation_4_unauthenticated_request_rejected(self, session):
        protected_routes = [
            ("GET", f"{TARGET_BASE_URL}/donors/eligibility"),
            ("GET", f"{TARGET_BASE_URL}/system-logs/"),
            ("POST", f"{TARGET_BASE_URL}/inventory/scan-expiries"),
            ("POST", f"{TARGET_BASE_URL}/requests/"),
        ]
        for method, url in protected_routes:
            res = session.request(method, url, timeout=TIMEOUT)
            assert res.status_code == 401, f"Route {url} returned {res.status_code}, expected 401: {res.text}"

class TestPrivacyAndCornerCases:
    def test_privacy_leak_check_pending_match_contact_masked(self, session, recipient_auth):
        res = session.post(
            f"{TARGET_BASE_URL}/requests/",
            headers=recipient_auth,
            json={
                "blood_group": "O_PLUS",
                "component_type": "WHOLE_BLOOD",
                "quantity": 1.0,
                "urgency": "NORMAL",
                "required_location": "Mohakhali, Dhaka",
                "latitude": 23.7772,
                "longitude": 90.4054,
            },
            timeout=TIMEOUT,
        )
        assert res.status_code == 201
        matches = res.json().get("matches", [])
        assert len(matches) >= 1
        pending_match = matches[0]
        assert pending_match["response_status"] == "PENDING"
        match_id = pending_match["match_id"]

        reveal_res = session.get(f"{TARGET_BASE_URL}/matches/{match_id}/contact", headers=recipient_auth, timeout=TIMEOUT)
        assert reveal_res.status_code == 403, f"Expected 403, got {reveal_res.status_code}"
        assert "Contact information is masked" in reveal_res.text

    def test_eligibility_validation_checks(self, session):
        # Underweight (< 50 kg)
        uid = str(uuid.uuid4())[:8]
        underweight_donor = {
            "full_name": "Underweight Candidate",
            "email": f"underweight_{uid}@test.org",
            "phone": "+8801700000001",
            "password": "Password123!",
            "role": "DONOR",
            "donor_profile": {
                "blood_group": "A_PLUS",
                "date_of_birth": "2000-01-01",
                "gender": "Female",
                "weight": 42.0,
                "address": "Dhaka",
                "latitude": 23.7,
                "longitude": 90.4,
                "hemoglobin_level": 13.0,
            },
        }
        reg_res = session.post(f"{TARGET_BASE_URL}/auth/register", json=underweight_donor, timeout=TIMEOUT)
        assert reg_res.status_code == 201
        login_res = session.post(f"{TARGET_BASE_URL}/auth/login", json={"email": underweight_donor["email"], "password": "Password123!"}, timeout=TIMEOUT)
        token = login_res.json()["access_token"]
        elig_res = session.get(f"{TARGET_BASE_URL}/donors/eligibility", headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        assert elig_res.status_code == 200
        assert elig_res.json()["is_eligible"] is False
        assert any("Weight is below the minimum required 50.0 kg" in r for r in elig_res.json()["rejection_reasons"])

        # Underage (< 18)
        uid2 = str(uuid.uuid4())[:8]
        underage_donor = {
            "full_name": "Underage Candidate",
            "email": f"underage_{uid2}@test.org",
            "phone": "+8801700000002",
            "password": "Password123!",
            "role": "DONOR",
            "donor_profile": {
                "blood_group": "B_PLUS",
                "date_of_birth": "2015-06-15",
                "gender": "Male",
                "weight": 55.0,
                "address": "Dhaka",
                "latitude": 23.7,
                "longitude": 90.4,
                "hemoglobin_level": 14.0,
            },
        }
        session.post(f"{TARGET_BASE_URL}/auth/register", json=underage_donor, timeout=TIMEOUT)
        login_res2 = session.post(f"{TARGET_BASE_URL}/auth/login", json={"email": underage_donor["email"], "password": "Password123!"}, timeout=TIMEOUT)
        token2 = login_res2.json()["access_token"]
        elig_res2 = session.get(f"{TARGET_BASE_URL}/donors/eligibility", headers={"Authorization": f"Bearer {token2}"}, timeout=TIMEOUT)
        assert elig_res2.status_code == 200
        assert elig_res2.json()["is_eligible"] is False
        assert any("under 18 years old" in r for r in elig_res2.json()["rejection_reasons"])

        # Low Hemoglobin (< 12.5 g/dL)
        uid3 = str(uuid.uuid4())[:8]
        anemic_donor = {
            "full_name": "Anemic Candidate",
            "email": f"anemic_{uid3}@test.org",
            "phone": "+8801700000003",
            "password": "Password123!",
            "role": "DONOR",
            "donor_profile": {
                "blood_group": "O_PLUS",
                "date_of_birth": "1998-03-20",
                "gender": "Female",
                "weight": 58.0,
                "address": "Dhaka",
                "latitude": 23.7,
                "longitude": 90.4,
                "hemoglobin_level": 10.5,
            },
        }
        session.post(f"{TARGET_BASE_URL}/auth/register", json=anemic_donor, timeout=TIMEOUT)
        login_res3 = session.post(f"{TARGET_BASE_URL}/auth/login", json={"email": anemic_donor["email"], "password": "Password123!"}, timeout=TIMEOUT)
        token3 = login_res3.json()["access_token"]
        elig_res3 = session.get(f"{TARGET_BASE_URL}/donors/eligibility", headers={"Authorization": f"Bearer {token3}"}, timeout=TIMEOUT)
        assert elig_res3.status_code == 200
        assert elig_res3.json()["is_eligible"] is False
        assert any("Hemoglobin level is below 12.5 g/dL" in r for r in elig_res3.json()["rejection_reasons"])

    def test_input_validation_rejections(self, session, hospital_auth, recipient_auth, admin_auth):
        inv_res = session.get(f"{TARGET_BASE_URL}/inventory/", headers=admin_auth, timeout=TIMEOUT)
        items = inv_res.json()
        assert len(items) >= 1
        inv_id = items[0]["inventory_id"]

        neg_qty_res = session.post(
            f"{TARGET_BASE_URL}/inventory/transaction",
            headers=hospital_auth,
            json={
                "inventory_id": inv_id,
                "type": "IN",
                "quantity": -10.0,
                "reference_type": "MANUAL",
            },
            timeout=TIMEOUT,
        )
        assert neg_qty_res.status_code == 422

        invalid_bg_res = session.post(
            f"{TARGET_BASE_URL}/requests/",
            headers=recipient_auth,
            json={
                "blood_group": "XYZ_POSITIVE",
                "component_type": "WHOLE_BLOOD",
                "quantity": 1.0,
                "urgency": "NORMAL",
                "required_location": "Dhaka",
                "latitude": 23.7,
                "longitude": 90.4,
            },
            timeout=TIMEOUT,
        )
        assert invalid_bg_res.status_code == 422

    def test_emergency_priority_multiplier(self, session, recipient_auth):
        emerg_res = session.post(
            f"{TARGET_BASE_URL}/requests/",
            headers=recipient_auth,
            json={
                "blood_group": "O_PLUS",
                "component_type": "WHOLE_BLOOD",
                "quantity": 1.0,
                "urgency": "EMERGENCY",
                "required_location": "Emergency Trauma Unit",
                "latitude": 23.7937,
                "longitude": 90.4066,
            },
            timeout=TIMEOUT,
        )
        assert emerg_res.status_code == 201
        matches = emerg_res.json().get("matches", [])
        assert len(matches) >= 1
        emerg_score = matches[0]["match_score"]
        assert emerg_score > 40.0
