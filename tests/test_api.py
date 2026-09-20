"""End-to-end integration and unit tests for SBDMS FastAPI backend."""
import sys
import uuid
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "backend")

from main import app
from app.core.database import SessionLocal
from app.core.enums import (
    UserRole,
    BloodGroup,
    ComponentType,
    RequestUrgency,
    MatchResponseStatus,
    TransactionType,
    StockStatus,
    ParticipantRole,
)
from app.services.compatibility import get_compatible_donor_groups, is_blood_compatible
from app.services.inventory import calculate_stock_status
from app.services.matching import haversine_distance
from app.services.email_service import (
    send_single_donor_match_alert,
    send_emergency_broadcast_alert,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_external_email_dispatcher(monkeypatch):
    """Safely mock external Resend/SMTP network calls during test runs."""
    monkeypatch.setattr("app.services.email_service._dispatch_email", lambda *args, **kwargs: True)


def test_health_check():
    """Verify health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_compatibility_matrix():
    """Verify blood compatibility rules."""
    # O_NEGATIVE can only receive O_NEGATIVE
    assert get_compatible_donor_groups(BloodGroup.O_NEGATIVE) == [BloodGroup.O_NEGATIVE]
    assert is_blood_compatible(BloodGroup.O_NEGATIVE, BloodGroup.O_NEGATIVE) is True
    assert is_blood_compatible(BloodGroup.O_NEGATIVE, BloodGroup.O_POSITIVE) is False

    # AB_POSITIVE is universal recipient
    assert len(get_compatible_donor_groups(BloodGroup.AB_POSITIVE)) == 8
    assert is_blood_compatible(BloodGroup.AB_POSITIVE, BloodGroup.O_NEGATIVE) is True
    assert is_blood_compatible(BloodGroup.AB_POSITIVE, BloodGroup.A_POSITIVE) is True


def test_haversine_distance():
    """Verify spatial calculation."""
    # Dhaka center to Dhanmondi (~3-5 km)
    dist = haversine_distance(23.8103, 90.4125, 23.7465, 90.3760)
    assert 5.0 < dist < 12.0


def test_stock_status_calculator():
    """Verify stock status thresholds."""
    assert calculate_stock_status(0) == StockStatus.OUT_OF_STOCK
    assert calculate_stock_status(5) == StockStatus.CRITICAL  # 10%
    assert calculate_stock_status(15) == StockStatus.LOW_STOCK  # 30%
    assert calculate_stock_status(40) == StockStatus.HEALTHY  # 80%


def test_full_user_and_matching_flow():
    """Test full integration lifecycle:
    1. Register Donor
    2. Register Recipient
    3. Login & JWT authentication
    4. Eligibility check
    5. Recipient creates blood request -> Matching engine dispatches match
    6. Masked view verification (Contact Reveal Safeguard before accept -> 403 Forbidden)
    7. Donor accepts match
    8. Contact Reveal Safeguard verification (after accept -> 200 OK with phone/address)
    """
    unique_suffix = str(uuid.uuid4())[:8]

    # 1. Register Donor
    donor_email = f"donor_{unique_suffix}@example.com"
    donor_res = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Donor",
            "email": donor_email,
            "phone": "+8801711111111",
            "password": "Password123!",
            "role": "DONOR",
            "donor_profile": {
                "blood_group": "O_POSITIVE",
                "date_of_birth": "1995-05-15",
                "gender": "Male",
                "weight": 70.0,
                "address": "Banani, Dhaka",
                "latitude": 23.7937,
                "longitude": 90.4066,
                "hemoglobin_level": 14.5,
            },
        },
    )
    assert donor_res.status_code == 201
    donor_data = donor_res.json()
    registered_donor_id = donor_data["user_id"]

    # 2. Register Recipient
    recipient_email = f"recipient_{unique_suffix}@example.com"
    recipient_res = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Recipient",
            "email": recipient_email,
            "phone": "+8801822222222",
            "password": "Password123!",
            "role": "RECIPIENT",
            "recipient_profile": {
                "nid_passport_no": "199283746152",
                "address": "Gulshan 1, Dhaka",
                "relationship_to_patient": "Brother",
                "patient_name": "John Recipient",
            },
        },
    )
    assert recipient_res.status_code == 201

    # 3. Login as Donor
    donor_login = client.post(
        "/api/v1/auth/login",
        json={"email": donor_email, "password": "Password123!"},
    )
    assert donor_login.status_code == 200
    donor_tokens = donor_login.json()
    donor_auth_headers = {"Authorization": f"Bearer {donor_tokens['access_token']}"}

    # 4. Check Donor Eligibility
    elig_res = client.get("/api/v1/donors/eligibility", headers=donor_auth_headers)
    assert elig_res.status_code == 200
    assert elig_res.json()["is_eligible"] is True

    # 5. Login as Recipient
    recipient_login = client.post(
        "/api/v1/auth/login",
        json={"email": recipient_email, "password": "Password123!"},
    )
    assert recipient_login.status_code == 200
    recipient_tokens = recipient_login.json()
    recip_auth_headers = {"Authorization": f"Bearer {recipient_tokens['access_token']}"}

    # 6. Recipient creates blood request (Gulshan coordinates, nearby to Banani)
    req_res = client.post(
        "/api/v1/requests/",
        headers=recip_auth_headers,
        json={
            "blood_group": "O_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 2.0,
            "urgency": "URGENT",
            "required_location": "United Hospital, Gulshan",
            "latitude": 23.7998,
            "longitude": 90.4208,
            "notes": "Emergency surgery request",
        },
    )
    assert req_res.status_code == 201
    req_data = req_res.json()
    assert req_data["status"] in ["OPEN", "MATCHED"]
    assert len(req_data["matches"]) >= 1

    # Find the match corresponding to our newly registered donor
    our_matches = [m for m in req_data["matches"] if m["donor_id"] == registered_donor_id]
    assert len(our_matches) >= 1
    match = our_matches[0]
    match_id = match["match_id"]

    # Contact is masked
    assert match["contact_revealed"] is False
    assert "Donor" in match["donor_name_initial"]

    # 7. Recipient attempts to reveal contact before acceptance -> MUST return 403 Forbidden
    reveal_fail = client.get(
        f"/api/v1/matches/{match_id}/contact",
        headers=recip_auth_headers,
    )
    assert reveal_fail.status_code == 403
    assert "Contact information is masked" in reveal_fail.json()["detail"]

    # 8. Donor responds and ACCEPTS the match
    accept_res = client.post(
        f"/api/v1/matches/{match_id}/respond",
        headers=donor_auth_headers,
        json={"response": "ACCEPTED"},
    )
    assert accept_res.status_code == 200

    # 9. Recipient attempts to reveal contact after acceptance -> MUST return 200 OK with details
    reveal_success = client.get(
        f"/api/v1/matches/{match_id}/contact",
        headers=recip_auth_headers,
    )
    assert reveal_success.status_code == 200
    contact_info = reveal_success.json()
    assert contact_info["full_name"] == "Test Donor"
    assert contact_info["phone"] == "+8801711111111"
    assert contact_info["address"] == "Banani, Dhaka"
    assert contact_info["response_status"] == "ACCEPTED"


def test_hospital_inventory_and_expiry_flow():
    """Test hospital registration, inventory recording, stock transaction, and expiry scanning."""
    unique_suffix = str(uuid.uuid4())[:8]
    hosp_email = f"hospital_{unique_suffix}@example.com"

    # Register Hospital Admin
    hosp_reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Hospital Admin",
            "email": hosp_email,
            "phone": "+8801933333333",
            "password": "Password123!",
            "role": "HOSPITAL_ADMIN",
            "hospital_profile": {
                "hospital_name": "Evercare Hospital",
                "address": "Plot 81, Block E, Bashundhara R/A",
                "latitude": 23.8103,
                "longitude": 90.4312,
                "contact_number": "+88028401661",
            },
        },
    )
    assert hosp_reg.status_code == 201
    hosp_user_id = hosp_reg.json()["user_id"]

    # Login
    hosp_login = client.post(
        "/api/v1/auth/login",
        json={"email": hosp_email, "password": "Password123!"},
    )
    assert hosp_login.status_code == 200
    hosp_token = hosp_login.json()["access_token"]
    hosp_headers = {"Authorization": f"Bearer {hosp_token}"}

    # Populate an inventory item directly in DB for this newly registered hospital
    db = SessionLocal()
    from app.models.user import Hospital
    from app.models.inventory import BloodInventory
    hosp_obj = db.query(Hospital).filter(Hospital.user_id == hosp_user_id).first()
    assert hosp_obj is not None

    inv_item = BloodInventory(
        hospital_id=hosp_obj.hospital_id,
        blood_group=BloodGroup.A_POSITIVE,
        component_type=ComponentType.WHOLE_BLOOD,
        quantity=60.0,
        unit="ml/unit",
        expiry_date=date.today() + timedelta(days=2),  # Expiring within 48h (triggers 72h sweep)
        status=StockStatus.HEALTHY,
    )
    db.add(inv_item)
    db.commit()
    db.refresh(inv_item)
    inv_id = str(inv_item.inventory_id)
    db.close()

    # 1. Fetch Inventory via API
    inv_list_res = client.get("/api/v1/inventory/", headers=hosp_headers)
    assert inv_list_res.status_code == 200
    assert len(inv_list_res.json()) >= 1

    # 2. Record stock OUT transaction
    tx_res = client.post(
        "/api/v1/inventory/transaction",
        headers=hosp_headers,
        json={
            "inventory_id": inv_id,
            "type": "OUT",
            "quantity": 50.0,
            "reference_type": "REQUEST",
        },
    )
    assert tx_res.status_code == 201
    assert tx_res.json()["type"] == "OUT"

    # 3. Trigger Expiry Scan sweep
    scan_res = client.post("/api/v1/inventory/scan-expiries", headers=hosp_headers)
    assert scan_res.status_code == 200
    scan_data = scan_res.json()
    assert scan_data["scanned_count"] >= 1
    assert scan_data["expiring_soon_count"] >= 1


def test_events_notices_and_audit():
    """Test event creation & registration, campaign notices, and system audit logs."""
    unique_suffix = str(uuid.uuid4())[:8]

    # Create system admin
    admin_email = f"admin_{unique_suffix}@example.com"
    admin_reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "System Administrator",
            "email": admin_email,
            "phone": "+8801999999999",
            "password": "Password123!",
            "role": "SYSTEM_ADMIN",
        },
    )
    assert admin_reg.status_code == 201

    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": "Password123!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create Campaign Notice
    notice_res = client.post(
        "/api/v1/campaign-notices/",
        headers=admin_headers,
        json={
            "title": "National Blood Donation Day Campaign",
            "description": "Join our nationwide drive to replenish critical blood reserves.",
            "source": "Ministry of Health",
            "publish_date": str(date.today()),
            "expiry_date": str(date.today() + timedelta(days=30)),
            "link": "https://sbdms.gov/events/national-day",
        },
    )
    assert notice_res.status_code == 201
    assert notice_res.json()["title"] == "National Blood Donation Day Campaign"

    # Public notices listing
    public_notices = client.get("/api/v1/campaign-notices/")
    assert public_notices.status_code == 200
    assert len(public_notices.json()) >= 1

    # 2. Create Donation Event
    event_res = client.post(
        "/api/v1/events/",
        headers=admin_headers,
        json={
            "title": "Dhaka University Blood Drive",
            "description": "On-campus voluntary blood donation campaign.",
            "location": "Curzon Hall, University of Dhaka",
            "start_date": str(date.today()),
            "end_date": str(date.today() + timedelta(days=2)),
        },
    )
    assert event_res.status_code == 201
    event_id = event_res.json()["event_id"]

    # Public events listing
    events_list = client.get("/api/v1/events/")
    assert events_list.status_code == 200
    assert len(events_list.json()) >= 1

    # 3. System Admin reads System Logs
    logs_res = client.get("/api/v1/system-logs/", headers=admin_headers)
    assert logs_res.status_code == 200
    assert len(logs_res.json()) >= 1


def test_email_service_direct():
    """Verify email service in safe mock/fallback mode."""
    # 1. Single donor alert
    success = send_single_donor_match_alert(
        donor_email="test_donor@example.com",
        donor_name="Test Donor",
        blood_group="O_POSITIVE",
        hospital_name="Dhaka Medical College Hospital",
        match_id=str(uuid.uuid4()),
        distance_km=3.5,
    )
    assert success is True

    # 2. Emergency mass broadcast
    emails = ["donor1@example.com", "donor2@example.com", "donor3@example.com"]
    count = send_emergency_broadcast_alert(
        donor_emails=emails,
        blood_group="AB_NEGATIVE",
        hospital_name="Square Hospital Emergency Room",
        units_needed=2.0,
        request_id=str(uuid.uuid4()),
    )
    assert count == 3

    # 3. Empty input edge cases
    assert send_single_donor_match_alert("", "Name", "O+", "Hospital", "id") is False
    assert send_emergency_broadcast_alert([], "O+", "Hospital", 1.0, "id") == 0


def test_emergency_request_triggers_email_broadcast():
    """Verify that creating an emergency blood request triggers the matching engine
    and dispatches non-blocking emergency email broadcasts."""
    unique_suffix = str(uuid.uuid4())[:8]

    # Register eligible donor
    donor_email = f"donor_em_{unique_suffix}@example.com"
    donor_res = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Emergency Target Donor",
            "email": donor_email,
            "phone": "+8801733333333",
            "password": "Password123!",
            "role": "DONOR",
            "donor_profile": {
                "blood_group": "A_POSITIVE",
                "date_of_birth": "1997-08-20",
                "gender": "Female",
                "weight": 58.0,
                "address": "Dhanmondi, Dhaka",
                "latitude": 23.7465,
                "longitude": 90.3760,
                "hemoglobin_level": 13.8,
            },
        },
    )
    assert donor_res.status_code == 201

    # Register recipient
    recip_email = f"recip_em_{unique_suffix}@example.com"
    recip_res = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Emergency Recipient",
            "email": recip_email,
            "phone": "+8801844444444",
            "password": "Password123!",
            "role": "RECIPIENT",
            "recipient_profile": {
                "nid_passport_no": "199483726194",
                "address": "Dhanmondi 27, Dhaka",
                "relationship_to_patient": "Self",
                "patient_name": "Emergency Patient",
            },
        },
    )
    assert recip_res.status_code == 201

    # Login as recipient
    recip_login = client.post(
        "/api/v1/auth/login",
        json={"email": recip_email, "password": "Password123!"},
    )
    assert recip_login.status_code == 200
    recip_token = recip_login.json()["access_token"]
    recip_headers = {"Authorization": f"Bearer {recip_token}"}

    # Dispatch emergency request
    em_res = client.post(
        "/api/v1/requests/emergency",
        headers=recip_headers,
        json={
            "blood_group": "A_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "EMERGENCY",
            "required_location": "Ibn Sina Hospital, Dhanmondi",
            "latitude": 23.7470,
            "longitude": 90.3770,
            "notes": "Immediate ICU emergency blood required",
        },
    )
    assert em_res.status_code == 201
    em_data = em_res.json()
    assert em_data["urgency"] == "EMERGENCY"
    assert em_data["status"] in ["OPEN", "MATCHED"]
    assert len(em_data["matches"]) >= 1


def test_unified_user_dual_capabilities():
    """Phase 2 Verification: Verify that a single unified user account
    has BOTH Donor and Recipient capabilities simultaneously."""
    unique_suffix = str(uuid.uuid4())[:8]
    user_email = f"unified_{unique_suffix}@example.com"

    # 1. Register with top-level unified identity fields (single signup flow)
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Unified Member",
            "email": user_email,
            "phone": "+8801755555555",
            "password": "Password123!",
            "blood_group": "B_POSITIVE",
            "date_of_birth": "1996-03-25",
            "gender": "Male",
            "weight": 68.0,
            "address": "Mirpur 10, Dhaka",
            "latitude": 23.8041,
            "longitude": 90.3667,
        },
    )
    assert reg_res.status_code == 201
    user_data = reg_res.json()
    assert user_data["donor"] is not None
    assert user_data["donor"]["blood_group"] == "B_POSITIVE"
    assert user_data["recipient"] is not None
    assert user_data["recipient"]["patient_name"] == "Unified Member"

    # 2. Login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": user_email, "password": "Password123!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Donor Capability: Check Eligibility
    elig_res = client.get("/api/v1/donors/eligibility", headers=headers)
    assert elig_res.status_code == 200
    assert elig_res.json()["is_eligible"] is True

    # 4. Donor Capability: Toggle Availability Status
    avail_res = client.patch(
        "/api/v1/donors/availability",
        headers=headers,
        json={"availability_status": "UNAVAILABLE"},
    )
    assert avail_res.status_code == 200
    assert avail_res.json()["availability_status"] == "UNAVAILABLE"

    avail_res_on = client.patch(
        "/api/v1/donors/availability",
        headers=headers,
        json={"availability_status": "AVAILABLE"},
    )
    assert avail_res_on.status_code == 200
    assert avail_res_on.json()["availability_status"] == "AVAILABLE"

    # 5. Recipient Capability: Create Blood Request under the exact same login
    req_res = client.post(
        "/api/v1/requests/",
        headers=headers,
        json={
            "blood_group": "B_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "required_location": "Mirpur General Hospital, Dhaka",
            "latitude": 23.8050,
            "longitude": 90.3680,
            "notes": "Unified account request test",
        },
    )
    assert req_res.status_code == 201
    assert req_res.json()["blood_group"] == "B_POSITIVE"

    # 6. Recipient Capability: Create Emergency Request under the exact same login
    em_res = client.post(
        "/api/v1/requests/emergency",
        headers=headers,
        json={
            "blood_group": "B_POSITIVE",
            "component_type": "PLATELETS",
            "quantity": 2.0,
            "urgency": "EMERGENCY",
            "required_location": "National Heart Foundation, Mirpur",
            "latitude": 23.8060,
            "longitude": 90.3690,
            "notes": "Urgent platelets needed",
        },
    )
    assert em_res.status_code == 201
    assert em_res.json()["urgency"] == "EMERGENCY"


def test_blood_request_phase3_fields_and_privacy_masking():
    """Test Phase 3: Blood request schema with patient/hospital/area/volume/attendant phone,
    privacy phone masking for public viewers, and request status lifecycle.
    """
    uid_a = uuid.uuid4().hex[:8]
    email_a = f"req_owner_{uid_a}@example.com"
    reg_a = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Request Owner A",
            "email": email_a,
            "phone": "+8801711001122",
            "password": "Password123!",
            "blood_group": "A_POSITIVE",
            "address": "Dhanmondi, Dhaka",
        },
    )
    assert reg_a.status_code == 201
    token_a = client.post(
        "/api/v1/auth/login",
        json={"email": email_a, "password": "Password123!"},
    ).json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    uid_b = uuid.uuid4().hex[:8]
    email_b = f"req_viewer_{uid_b}@example.com"
    reg_b = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Donor Viewer B",
            "email": email_b,
            "phone": "+8801822003344",
            "password": "Password123!",
            "blood_group": "A_POSITIVE",
            "address": "Panthapath, Dhaka",
        },
    )
    assert reg_b.status_code == 201
    token_b = client.post(
        "/api/v1/auth/login",
        json={"email": email_b, "password": "Password123!"},
    ).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Create request with Phase 3 fields
    create_res = client.post(
        "/api/v1/requests/",
        headers=headers_a,
        json={
            "blood_group": "A_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 2.0,
            "urgency": "NORMAL",
            "required_location": "Square Hospital, Panthapath",
            "latitude": 23.7531,
            "longitude": 90.3817,
            "notes": "Emergency surgery support",
            "patient_name": "Test Patient Khan",
            "hospital_name": "Square Hospital",
            "area_zone": "Panthapath",
            "attendant_phone_number": "+8801711998877",
            "volume_ml": 900.0,
        },
    )
    assert create_res.status_code == 201
    req_data = create_res.json()
    req_id = req_data["request_id"]
    assert req_data["status"] == "OPEN"
    assert req_data["patient_name"] == "Test Patient Khan"
    assert req_data["hospital_name"] == "Square Hospital"
    assert req_data["area_zone"] == "Panthapath"
    assert req_data["volume_ml"] == 900.0
    # Owner sees full attendant phone
    assert req_data["attendant_phone_number"] == "+8801711998877"

    # 2. Viewer B (public/unmatched donor) retrieves request -> phone MUST be masked
    get_res_b = client.get(f"/api/v1/requests/{req_id}", headers=headers_b)
    assert get_res_b.status_code == 200
    viewer_b_data = get_res_b.json()
    assert viewer_b_data["attendant_phone_number"] != "+8801711998877"
    assert "*" in viewer_b_data["attendant_phone_number"]

    # 3. Status Lifecycle: Viewer B accepts the request
    accept_res = client.patch(
        f"/api/v1/requests/{req_id}/status",
        headers=headers_b,
        json={"status": "ACCEPTED"},
    )
    assert accept_res.status_code == 200
    accepted_data = accept_res.json()
    assert accepted_data["status"] == "ACCEPTED"
    assert accepted_data["accepted_donor_id"] is not None
    # Now that Viewer B is the accepted donor, they see the unmasked phone!
    assert accepted_data["attendant_phone_number"] == "+8801711998877"

    # 4. Status Lifecycle: Transition to PROCESSING
    proc_res = client.patch(
        f"/api/v1/requests/{req_id}/status",
        headers=headers_a,
        json={"status": "PROCESSING"},
    )
    assert proc_res.status_code == 200
    assert proc_res.json()["status"] == "PROCESSING"

    # 5. Status Lifecycle: Transition to COMPLETED
    comp_res = client.patch(
        f"/api/v1/requests/{req_id}/status",
        headers=headers_a,
        json={"status": "COMPLETED"},
    )
    assert comp_res.status_code == 200
    assert comp_res.json()["status"] == "COMPLETED"


def test_phase4_emergency_landing_accept_and_unmasking(monkeypatch):
    """Test Phase 4:
    1. Unauthenticated public access to /api/v1/requests/{id} with masked attendant phone.
    2. Donor acceptance via POST /api/v1/requests/{id}/accept with eligibility validation.
    3. Instant unmasking of attendant contact phone for accepted donor.
    4. Recipient access to accepted donor's name, phone, and area zone.
    5. Prevention of double acceptance and self-acceptance.
    6. send_donor_accepted_alert email dispatch.
    """
    monkeypatch.setattr("app.services.email_service._dispatch_email", lambda *args, **kwargs: True)
    from app.services.email_service import send_donor_accepted_alert

    # 1. Create Recipient User and a Blood Request
    uid_r = uuid.uuid4().hex[:8]
    email_r = f"recip_{uid_r}@example.com"
    reg_r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Emergency Recipient",
            "email": email_r,
            "phone": "+8801811223344",
            "password": "Password123!",
            "role": "RECIPIENT",
            "blood_group": "A_POSITIVE",
            "address": "Dhanmondi, Dhaka",
        },
    )
    assert reg_r.status_code == 201
    token_r = client.post(
        "/api/v1/auth/login",
        json={"email": email_r, "password": "Password123!"},
    ).json()["access_token"]
    headers_r = {"Authorization": f"Bearer {token_r}"}

    create_res = client.post(
        "/api/v1/requests/",
        headers=headers_r,
        json={
            "blood_group": "A_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 2.0,
            "volume_ml": 900.0,
            "urgency": "EMERGENCY",
            "patient_name": "Critical Patient X",
            "hospital_name": "Square Hospital, Dhaka",
            "area_zone": "West Dhanmondi",
            "attendant_phone_number": "+8801999888777",
            "required_location": "Square Hospital, Panthapath, Dhaka",
            "latitude": 23.7533,
            "longitude": 90.3837,
            "notes": "Emergency ICU transfusion",
        },
    )
    assert create_res.status_code == 201
    req_id = create_res.json()["request_id"]

    # 2. Public Unauthenticated Landing View
    public_res = client.get(f"/api/v1/requests/{req_id}")
    assert public_res.status_code == 200
    pub_data = public_res.json()
    assert pub_data["hospital_name"] == "Square Hospital, Dhaka"
    assert pub_data["status"] == "OPEN"
    # Attendant phone MUST be masked for public viewer
    assert pub_data["attendant_phone_number"] != "+8801999888777"
    assert "*" in pub_data["attendant_phone_number"]

    # 3. Create Volunteer Donor B
    uid_d = uuid.uuid4().hex[:8]
    email_d = f"donor_{uid_d}@example.com"
    reg_d = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Volunteer Donor Farhan",
            "email": email_d,
            "phone": "+8801777665544",
            "password": "Password123!",
            "role": "DONOR",
            "blood_group": "A_POSITIVE",
            "address": "Banani, Dhaka",
        },
    )
    assert reg_d.status_code == 201
    donor_d_id = reg_d.json()["user_id"]
    token_d = client.post(
        "/api/v1/auth/login",
        json={"email": email_d, "password": "Password123!"},
    ).json()["access_token"]
    headers_d = {"Authorization": f"Bearer {token_d}"}

    # Set Donor Medical Info so they pass eligibility check (Hb >= 12.5)
    med_res = client.post(
        "/api/v1/donors/medical-info",
        headers=headers_d,
        json={
            "hemoglobin_level": 14.5,
            "allergies": "None",
            "chronic_diseases": "None",
        },
    )
    assert med_res.status_code == 200

    # 4. Self-Acceptance Safeguard: Recipient cannot accept their own request
    self_accept = client.post(f"/api/v1/requests/{req_id}/accept", headers=headers_r)
    assert self_accept.status_code == 400
    assert "cannot accept your own" in self_accept.json()["detail"].lower()

    # 5. Donor Accepts the Request: POST /api/v1/requests/{req_id}/accept
    accept_res = client.post(f"/api/v1/requests/{req_id}/accept", headers=headers_d)
    assert accept_res.status_code == 200
    accepted_data = accept_res.json()
    assert accepted_data["status"] == "ACCEPTED"
    assert accepted_data["accepted_donor_id"] == donor_d_id
    # Unmasked phone revealed to accepted donor!
    assert accepted_data["attendant_phone_number"] == "+8801999888777"

    # 6. Recipient Checks Request: Sees Accepted Status and Donor Contact
    recip_view = client.get(f"/api/v1/requests/{req_id}", headers=headers_r)
    assert recip_view.status_code == 200
    recip_data = recip_view.json()
    assert recip_data["status"] == "ACCEPTED"
    assert recip_data["accepted_donor"] is not None
    assert recip_data["accepted_donor"]["full_name"] == "Volunteer Donor Farhan"
    assert recip_data["accepted_donor"]["phone"] == "+8801777665544"

    # 7. Another Donor C cannot accept an already accepted request
    uid_c = uuid.uuid4().hex[:8]
    email_c = f"donor_{uid_c}@example.com"
    reg_c = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Late Donor",
            "email": email_c,
            "phone": "+8801666554433",
            "password": "Password123!",
            "role": "DONOR",
            "blood_group": "A_POSITIVE",
            "address": "Uttara, Dhaka",
        },
    )
    assert reg_c.status_code == 201
    token_c = client.post(
        "/api/v1/auth/login",
        json={"email": email_c, "password": "Password123!"},
    ).json()["access_token"]
    headers_c = {"Authorization": f"Bearer {token_c}"}
    late_accept = client.post(f"/api/v1/requests/{req_id}/accept", headers=headers_c)
    assert late_accept.status_code == 400
    assert "already been accepted" in late_accept.json()["detail"].lower()

    # 8. Test transactional donor accepted email helper
    alert_sent = send_donor_accepted_alert(
        recipient_email=email_r,
        recipient_name="Emergency Recipient",
        donor_name="Volunteer Donor Farhan",
        donor_phone="+8801777665544",
        donor_area="Banani, Dhaka",
        request_id=req_id,
    )
    assert alert_sent is True


def test_phase5_approximate_coordinate_serialization_and_map_safeguard(monkeypatch):
    """Test Phase 5:
    1. Donor coordinates are serialized with ~1km privacy rounding (2 decimal places) on match cards.
    2. Exact residential coordinates are protected and not leaked in masked match cards.
    3. Request coordinates strictly reflect hospital/center location.
    """
    monkeypatch.setattr("app.services.email_service._dispatch_email", lambda *args, **kwargs: True)

    # 1. Register donor with high-precision exact coordinates
    uid_d = uuid.uuid4().hex[:8]
    email_d = f"donor_p5_{uid_d}@example.com"
    exact_lat = 23.792841
    exact_lng = 90.407819
    reg_d = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "High Precision Donor",
            "email": email_d,
            "phone": "+8801711224466",
            "password": "Password123!",
            "role": "DONOR",
            "blood_group": "AB_POSITIVE",
            "address": "Road 11, Block D, Banani, Dhaka",
        },
    )
    assert reg_d.status_code == 201
    token_d = client.post(
        "/api/v1/auth/login",
        json={"email": email_d, "password": "Password123!"},
    ).json()["access_token"]
    headers_d = {"Authorization": f"Bearer {token_d}"}

    # Update donor profile with high-precision coordinates
    upd_res = client.put(
        "/api/v1/donors/profile",
        headers=headers_d,
        json={
            "latitude": exact_lat,
            "longitude": exact_lng,
            "address": "Banani, Dhaka",
            "weight": 70.0,
        },
    )
    assert upd_res.status_code == 200

    # Ensure donor has medical info for eligibility
    client.post(
        "/api/v1/donors/medical-info",
        headers=headers_d,
        json={"hemoglobin_level": 14.0},
    )

    # 2. Register recipient and create a request at a specific hospital
    uid_r = uuid.uuid4().hex[:8]
    email_r = f"recip_p5_{uid_r}@example.com"
    reg_r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Hospital Recipient",
            "email": email_r,
            "phone": "+8801811335577",
            "password": "Password123!",
            "role": "RECIPIENT",
            "blood_group": "AB_POSITIVE",
            "address": "Home Address in Old Dhaka (Private)",
        },
    )
    assert reg_r.status_code == 201
    token_r = client.post(
        "/api/v1/auth/login",
        json={"email": email_r, "password": "Password123!"},
    ).json()["access_token"]
    headers_r = {"Authorization": f"Bearer {token_r}"}

    hospital_lat = 23.753312
    hospital_lng = 90.383745
    req_res = client.post(
        "/api/v1/requests/",
        headers=headers_r,
        json={
            "blood_group": "AB_POSITIVE",
            "component_type": "WHOLE_BLOOD",
            "quantity": 1.0,
            "urgency": "NORMAL",
            "hospital_name": "Square Hospital",
            "area_zone": "Panthapath",
            "attendant_phone_number": "+8801700112233",
            "required_location": "Square Hospital, Panthapath, Dhaka",
            "latitude": hospital_lat,
            "longitude": hospital_lng,
        },
    )
    assert req_res.status_code == 201
    req_data = req_res.json()
    req_id = req_data["request_id"]

    # Request coordinates strictly reflect the hospital
    assert req_data["latitude"] == hospital_lat
    assert req_data["longitude"] == hospital_lng
    assert "Square Hospital" in req_data["required_location"]

    # 3. Query matched donors
    matches_res = client.get(f"/api/v1/requests/{req_id}/matches", headers=headers_r)
    assert matches_res.status_code == 200
    matches = matches_res.json()
    assert len(matches) >= 1

    # Find the newly created high-precision donor match
    target_match = next((m for m in matches if m["donor_id"] == reg_d.json()["user_id"]), None)
    assert target_match is not None

    # Verification: Coordinates must be rounded to 2 decimal places (~1.1km accuracy)
    assert target_match["approx_latitude"] == 23.79
    assert target_match["approx_longitude"] == 90.41
    # Exact coordinates MUST NOT be exposed in the masked match card
    assert target_match["approx_latitude"] != exact_lat
    assert target_match["approx_longitude"] != exact_lng





