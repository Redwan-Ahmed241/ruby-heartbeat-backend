"""Pydantic schemas for blood inventory and stock transactions."""
from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from app.core.enums import BloodGroup, ComponentType, StockStatus, TransactionType


class BloodInventoryResponse(BaseModel):
    inventory_id: UUID
    hospital_id: UUID
    blood_group: BloodGroup
    component_type: ComponentType
    quantity: float
    unit: str
    expiry_date: date
    status: StockStatus
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class InventoryTransactionCreate(BaseModel):
    inventory_id: UUID
    type: TransactionType
    quantity: float = Field(..., gt=0)
    reference_type: Optional[str] = Field(None, max_length=20)  # e.g., 'DONATION', 'REQUEST', 'EVENT', 'ADJUSTMENT'
    reference_id: Optional[UUID] = None


class InventoryTransactionResponse(BaseModel):
    transaction_id: UUID
    inventory_id: UUID
    type: TransactionType
    quantity: float
    reference_type: Optional[str]
    reference_id: Optional[UUID]
    created_by: UUID
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ExpiryScanItem(BaseModel):
    inventory_id: UUID
    hospital_name: str
    blood_group: BloodGroup
    component_type: ComponentType
    quantity: float
    expiry_date: date
    hours_remaining: float


class ExpiryScanResponse(BaseModel):
    scanned_count: int
    expiring_soon_count: int
    expiring_items: List[ExpiryScanItem]
    message: str
