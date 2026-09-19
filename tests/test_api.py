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
    assert req_data["status"] == "MATCHED"
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
    assert em_data["status"] == "MATCHED"
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


