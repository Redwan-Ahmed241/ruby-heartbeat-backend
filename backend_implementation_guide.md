# LifeDrop Backend Implementation Guide for Partner Blood Banks & NGO Events

**Target System:** FastAPI (Python 3.10+) • PostgreSQL (Supabase) • SQLAlchemy ORM • Pydantic v2  
**Audience:** Backend Engineer / Teammate  
**Frontend Repository:** `ruby-heartbeat-hub` (TanStack Start + React 19)

---

## 1. Context & Architectural Overview

On the frontend, **hospitals and blood banks are no longer an internal consumer login role**. 
- Consumer authentication (`POST /api/v1/auth/register`) strictly accepts two roles: **`DONOR`** and **`RECIPIENT`**.
- Institutional blood banks (e.g., **Square Hospital**, **Dhaka Medical College**, **Evercare**) and humanitarian NGOs (e.g., **Bangladesh Red Crescent Society (BDRCS)**, **Quantum Foundation**) are external entities.
- These facilities manage live reserve matrices, broadcast emergency ICU blood deficits, and **host public donation campaigns & blood drives** that automatically sync to LifeDrop's consumer `/events` feed and homepage.

To achieve complete end-to-end integration, the backend needs:
1. **Enhanced Donation Events API (`/api/v1/events/`)** with rich organizer and campaign metadata (NGO vs Hospital attribution, target units, focus blood groups).
2. **Dedicated External Partner Blood Bank Router (`/api/v1/external/blood-banks/`)** for profile, inventory matrix sync, and deficit broadcasts.
3. **Contact Blood Bank Authorization Flow (`POST /api/v1/blood-banks/{facility_id}/request-contact`)**.

---

## 2. Database Schema Migrations

Run the following SQL migration on your PostgreSQL / Supabase database:

```sql
-- ============================================================================
-- 1. Enhance donation_events table with partner & NGO metadata
-- ============================================================================
ALTER TABLE donation_events 
  ADD COLUMN IF NOT EXISTS organizer_name VARCHAR(255),
  ADD COLUMN IF NOT EXISTS organizer_type VARCHAR(50) DEFAULT 'HOSPITAL', -- 'HOSPITAL' | 'NGO' | 'COMMUNITY'
  ADD COLUMN IF NOT EXISTS target_units INTEGER DEFAULT 100,
  ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50),
  ADD COLUMN IF NOT EXISTS focus_blood_groups JSONB DEFAULT '["O-", "Whole Blood"]'::jsonb;

-- Allow external partners/NGOs without a user_id to publish drives
ALTER TABLE donation_events 
  ALTER COLUMN organizer_id DROP NOT NULL;

-- Index for public drive listings sorted by start date
CREATE INDEX IF NOT EXISTS idx_donation_events_dates ON donation_events (start_date ASC, status);

-- ============================================================================
-- 2. Partner Blood Deficit Shortage Broadcasts Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS partner_blood_needs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id VARCHAR(50) NOT NULL,
    blood_group VARCHAR(10) NOT NULL,
    component VARCHAR(50) NOT NULL,
    required_units INTEGER NOT NULL DEFAULT 1,
    urgency VARCHAR(30) NOT NULL DEFAULT 'URGENT', -- 'CRITICAL_ICU' | 'URGENT' | 'ROUTINE'
    clinical_reason TEXT,
    deadline VARCHAR(50) DEFAULT 'Within 12 Hours',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE' | 'FULFILLED' | 'CANCELLED'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_partner_needs_facility ON partner_blood_needs (facility_id, status);

-- ============================================================================
-- 3. Direct Contact Access Authorizations Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS blood_bank_contact_requests (
    request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id VARCHAR(50) NOT NULL,
    user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    blood_group VARCHAR(10) NOT NULL,
    component VARCHAR(50) NOT NULL,
    urgency VARCHAR(30) NOT NULL,
    units INTEGER NOT NULL DEFAULT 1,
    clinical_notes TEXT,
    requester_phone VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'AUTHORIZED',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## 3. SQLAlchemy Models

### A. Update `backend/app/models/event.py`
Add the new columns to `DonationEvent`:

```python
# backend/app/models/event.py
import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column,
    String,
    Integer,
    Date,
    DateTime,
    Text,
    ForeignKey,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import EventStatus, ParticipantRole, ParticipantStatus

class DonationEvent(Base):
    __tablename__ = "donation_events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    
    # Optional organizer_id to support both registered admins and third-party facilities
    organizer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    organizer_name = Column(String(255), nullable=True)     # e.g. "Bangladesh Red Crescent Society (BDRCS)"
    organizer_type = Column(String(50), default="HOSPITAL") # "HOSPITAL" | "NGO" | "COMMUNITY"
    target_units = Column(Integer, default=100)
    contact_phone = Column(String(50), nullable=True)
    focus_blood_groups = Column(JSONB, default=list)        # ["O-", "B-", "Platelets"]

    location = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(
        SQLEnum(EventStatus, name="event_status_enum"),
        default=EventStatus.UPCOMING,
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    organizer = relationship("User", foreign_keys=[organizer_id])
    participants = relationship("EventParticipant", back_populates="event", cascade="all, delete-orphan")
```

### B. Create `backend/app/models/partner.py`

```python
# backend/app/models/partner.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class PartnerBloodNeed(Base):
    __tablename__ = "partner_blood_needs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id = Column(String(50), nullable=False, index=True)
    blood_group = Column(String(10), nullable=False)
    component = Column(String(50), nullable=False)
    required_units = Column(Integer, default=1, nullable=False)
    urgency = Column(String(30), default="URGENT", nullable=False)
    clinical_reason = Column(Text, nullable=True)
    deadline = Column(String(50), default="Within 12 Hours")
    status = Column(String(20), default="ACTIVE", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class BloodBankContactRequest(Base):
    __tablename__ = "blood_bank_contact_requests"

    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id = Column(String(50), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    blood_group = Column(String(10), nullable=False)
    component = Column(String(50), nullable=False)
    urgency = Column(String(30), nullable=False)
    units = Column(Integer, default=1, nullable=False)
    clinical_notes = Column(Text, nullable=True)
    requester_phone = Column(String(30), nullable=False)
    status = Column(String(20), default="AUTHORIZED")
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
```

---

## 4. Pydantic Schemas

Update `backend/app/schemas/appointment.py`:

```python
# backend/app/schemas/appointment.py
from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from app.core.enums import EventStatus, ParticipantRole, ParticipantStatus

class DonationEventCreate(BaseModel):
    title: str = Field(..., max_length=150)
    description: str
    location: str = Field(..., max_length=255)
    start_date: date
    end_date: date
    organizer_name: Optional[str] = None
    organizer_type: Optional[str] = "HOSPITAL" # "HOSPITAL" or "NGO"
    target_units: Optional[int] = 100
    contact_phone: Optional[str] = None
    focus_blood_groups: Optional[List[str]] = Field(default_factory=list)

class EventResponse(BaseModel):
    event_id: UUID
    title: str
    description: str
    organizer_id: Optional[UUID] = None
    organizer_name: Optional[str] = None
    organizer_type: Optional[str] = "HOSPITAL"
    target_units: Optional[int] = 100
    registered_count: Optional[int] = 0
    location: str
    start_date: date
    end_date: date
    status: EventStatus
    contact_phone: Optional[str] = None
    focus_blood_groups: Optional[List[str]] = None
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
```

Create `backend/app/schemas/partner.py`:

```python
# backend/app/schemas/partner.py
from datetime import datetime
from typing import Optional, Dict, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

class ReserveItem(BaseModel):
    whole_blood: int = 0
    platelets: int = 0
    plasma: int = 0

class PartnerInventoryMatrix(BaseModel):
    # Mapping of blood groups: "O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"
    matrix: Dict[str, ReserveItem]

class PartnerBloodNeedCreate(BaseModel):
    blood_group: str
    component: str
    required_units: int = Field(default=1, ge=1)
    urgency: str = "URGENT" # "CRITICAL_ICU" | "URGENT" | "ROUTINE"
    clinical_reason: Optional[str] = None
    deadline: str = "Within 4 Hours"

class PartnerBloodNeedResponse(BaseModel):
    id: UUID
    facility_id: str
    blood_group: str
    component: str
    required_units: int
    urgency: str
    clinical_reason: Optional[str] = None
    deadline: str
    status: str
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

class ContactAccessRequest(BaseModel):
    blood_group: str
    component: str
    urgency: str
    units: int = 1
    clinical_notes: Optional[str] = None
    requester_phone: str

class ContactAccessResponse(BaseModel):
    success: bool
    reference_id: str
    hotline_direct: str
    dispatch_officer: str
    notes: str
```

---

## 5. Router Implementations

### A. Update `backend/app/api/v1/events.py`
Remove the blocking `RequireRoles([UserRole.HOSPITAL_ADMIN])` dependency so that partner portals, NGOs, and admins can all dispatch events.

```python
# backend/app/api/v1/events.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.enums import EventStatus, ParticipantRole, ParticipantStatus
from app.models.event import DonationEvent, EventParticipant
from app.schemas.appointment import (
    DonationEventCreate,
    EventResponse,
    EventParticipantCreate,
    EventParticipantResponse,
)
from app.api.deps import get_current_active_user, get_optional_current_user

router = APIRouter(prefix="/events", tags=["Donation Events"])

@router.get("/", response_model=List[EventResponse])
def list_events(db: Session = Depends(get_db)):
    """List all donation drives with accurate donor RSVP counts."""
    events = db.query(DonationEvent).order_by(DonationEvent.start_date.asc()).all()
    
    # Calculate RSVP counts from EventParticipant
    participant_counts = dict(
        db.query(
            EventParticipant.event_id,
            func.count(EventParticipant.participant_id)
        )
        .group_by(EventParticipant.event_id)
        .all()
    )

    results = []
    for ev in events:
        resp = EventResponse.model_validate(ev)
        resp.registered_count = participant_counts.get(ev.event_id, 0)
        results.append(resp)
    return results

@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_donation_event(
    event_data: DonationEventCreate,
    current_user = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Publish a blood donation drive.
    Can be created by an NGO (e.g. Red Crescent) or Partner Hospital Blood Bank.
    """
    new_event = DonationEvent(
        title=event_data.title,
        description=event_data.description,
        organizer_id=current_user.user_id if current_user else None,
        organizer_name=event_data.organizer_name or "Partner Blood Bank",
        organizer_type=event_data.organizer_type or "HOSPITAL",
        target_units=event_data.target_units or 100,
        contact_phone=event_data.contact_phone,
        focus_blood_groups=event_data.focus_blood_groups or ["O-", "Whole Blood"],
        location=event_data.location,
        start_date=event_data.start_date,
        end_date=event_data.end_date,
        status=EventStatus.UPCOMING,
    )
    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    resp = EventResponse.model_validate(new_event)
    resp.registered_count = 0
    return resp

@router.post("/{event_id}/register", response_model=EventParticipantResponse, status_code=status.HTTP_201_CREATED)
def register_for_event(
    event_id: UUID,
    participant_data: EventParticipantCreate,
    current_user = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Register donor interest / RSVP for a blood drive."""
    event = db.query(DonationEvent).filter(DonationEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    existing = db.query(EventParticipant).filter(
        EventParticipant.event_id == event_id,
        EventParticipant.user_id == current_user.user_id,
    ).first()
    
    if existing:
        return existing

    participant = EventParticipant(
        event_id=event_id,
        user_id=current_user.user_id,
        role=participant_data.role,
        status=ParticipantStatus.REGISTERED,
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant
```

---

### B. Create `backend/app/api/v1/external_banks.py`
Mount this router in `backend/app/api/v1/__init__.py` under prefix `/external/blood-banks`.

```python
# backend/app/api/v1/external_banks.py
from typing import List
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.partner import PartnerBloodNeed, BloodBankContactRequest
from app.schemas.partner import (
    PartnerBloodNeedCreate,
    PartnerBloodNeedResponse,
    ContactAccessRequest,
    ContactAccessResponse,
)

router = APIRouter(prefix="/external/blood-banks", tags=["External Partner Blood Banks"])

# In-memory matrix cache or backed by Redis / PostgreSQL table
FACILITY_MATRICES = {}

@router.get("/{facility_id}/inventory")
def get_partner_inventory(facility_id: str):
    """Get the 8-group matrix reserves for a partner facility."""
    matrix = FACILITY_MATRICES.get(facility_id, {
        "O+": {"whole_blood": 14, "platelets": 9, "plasma": 12},
        "O-": {"whole_blood": 2, "platelets": 1, "plasma": 3},
        "A+": {"whole_blood": 10, "platelets": 6, "plasma": 8},
        "A-": {"whole_blood": 4, "platelets": 3, "plasma": 5},
        "B+": {"whole_blood": 12, "platelets": 8, "plasma": 11},
        "B-": {"whole_blood": 2, "platelets": 1, "plasma": 2},
        "AB+": {"whole_blood": 7, "platelets": 4, "plasma": 6},
        "AB-": {"whole_blood": 1, "platelets": 0, "plasma": 1},
    })
    return {
        "inventory": matrix,
        "last_synced": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }

@router.post("/{facility_id}/inventory")
def sync_partner_inventory(facility_id: str, payload: dict):
    """Sync matrix reserves submitted by the hospital/NGO shift staff."""
    if "inventory" in payload:
        FACILITY_MATRICES[facility_id] = payload["inventory"]
    return {
        "success": True,
        "last_synced": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }

@router.get("/{facility_id}/broadcast-needs", response_model=List[PartnerBloodNeedResponse])
def get_broadcast_needs(facility_id: str, db: Session = Depends(get_db)):
    """Fetch all active shortage alerts for a facility."""
    return db.query(PartnerBloodNeed).filter(
        PartnerBloodNeed.facility_id == facility_id,
        PartnerBloodNeed.status == "ACTIVE"
    ).order_by(PartnerBloodNeed.created_at.desc()).all()

@router.post("/{facility_id}/broadcast-needs", response_model=PartnerBloodNeedResponse, status_code=status.HTTP_201_CREATED)
def create_broadcast_need(facility_id: str, need: PartnerBloodNeedCreate, db: Session = Depends(get_db)):
    """Broadcast an urgent deficit into LifeDrop."""
    new_need = PartnerBloodNeed(
        facility_id=facility_id,
        blood_group=need.blood_group,
        component=need.component,
        required_units=need.required_units,
        urgency=need.urgency,
        clinical_reason=need.clinical_reason,
        deadline=need.deadline,
        status="ACTIVE"
    )
    db.add(new_need)
    db.commit()
    db.refresh(new_need)
    return new_need

@router.patch("/{facility_id}/broadcast-needs/{need_id}/status", response_model=PartnerBloodNeedResponse)
def update_need_status(facility_id: str, need_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Mark a shortage alert as FULFILLED or CANCELLED."""
    need = db.query(PartnerBloodNeed).filter(
        PartnerBloodNeed.id == need_id,
        PartnerBloodNeed.facility_id == facility_id
    ).first()
    if not need:
        raise HTTPException(status_code=404, detail="Shortage alert not found.")
    
    need.status = payload.get("status", need.status)
    db.commit()
    db.refresh(need)
    return need

@router.delete("/{facility_id}/broadcast-needs/{need_id}")
def delete_need(facility_id: str, need_id: UUID, db: Session = Depends(get_db)):
    need = db.query(PartnerBloodNeed).filter(
        PartnerBloodNeed.id == need_id,
        PartnerBloodNeed.facility_id == facility_id
    ).first()
    if need:
        db.delete(need)
        db.commit()
    return {"success": True}
```

---

### C. Direct Contact Authorization Endpoint

Add to `backend/app/api/v1/external_banks.py` (or a dedicated `blood_banks.py`):

```python
@router.post("/{facility_id}/request-contact", response_model=ContactAccessResponse)
def request_blood_bank_contact(
    facility_id: str,
    payload: ContactAccessRequest,
    db: Session = Depends(get_db),
):
    """
    Logs patient authorization request and reveals blood bank direct clinical lines.
    """
    req = BloodBankContactRequest(
        facility_id=facility_id,
        blood_group=payload.blood_group,
        component=payload.component,
        urgency=payload.urgency,
        units=payload.units,
        clinical_notes=payload.clinical_notes,
        requester_phone=payload.requester_phone,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    return ContactAccessResponse(
        success=True,
        reference_id=f"AUTH-{str(req.request_id)[:8].upper()}",
        hotline_direct="+880 2 8159457 / Ext: 441",
        dispatch_officer="Dr. Farhana Ahmed (Senior Transfusion Specialist)",
        notes="Official direct line revealed. Quote your authorization reference ID when calling.",
    )
```

---

## 6. Verification with cURL

### Test 1: Fetch All Events (Auto-Synced Drives)
```bash
curl -X GET "http://localhost:8000/api/v1/events/" -H "Accept: application/json"
```

### Test 2: Publish a Community Drive as an NGO (e.g., Red Crescent)
```bash
curl -X POST "http://localhost:8000/api/v1/events/" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Red Crescent National Voluntary Blood Donation Drive 2026",
    "description": "Annual nationwide community blood donation campaign organized by BDRCS.",
    "location": "Red Crescent National HQ, 684-686 Boro Moghbazar, Dhaka",
    "start_date": "2026-09-20",
    "end_date": "2026-09-22",
    "organizer_name": "Bangladesh Red Crescent Society (BDRCS)",
    "organizer_type": "NGO",
    "target_units": 350,
    "contact_phone": "+880 2 48310188",
    "focus_blood_groups": ["O-", "B-", "A+", "Platelets"]
  }'
```

### Test 3: Fetch Real-Time Partner Matrix
```bash
curl -X GET "http://localhost:8000/api/v1/external/blood-banks/square/inventory"
```

### Test 4: Request Contact Authorization for Critical Unit
```bash
curl -X POST "http://localhost:8000/api/v1/external/blood-banks/square/request-contact" \
  -H "Content-Type: application/json" \
  -d '{
    "blood_group": "O-",
    "component": "Whole Blood",
    "urgency": "CRITICAL_ICU",
    "units": 2,
    "clinical_notes": "Emergency ICU standby for bypass surgery.",
    "requester_phone": "+880 1711-000000"
  }'
```
